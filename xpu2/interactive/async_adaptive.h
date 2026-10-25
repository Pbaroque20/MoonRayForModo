// MoonRay's adaptive sampling for the asynchronous renderer, host side.
//
// Adapted from MoonRay rndr/adaptive/AdaptiveRegionTree.{h,cc}, OverlappingRegions.h, ActivePixelMask.h and
// RenderDriver.cc (refineProgressivePasses), Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC; see
// MOONRAY_LICENSE.txt. The error measure, region layout, split and stopping rules and pass schedule are MoonRay's
// (after Dammertz et al., "A hierarchical automatic stopping condition for Monte Carlo global illumination").
//
// How it fits the work grid: a pass is a range of sample counts. Its work is chunks over the tiles that still have
// active pixels, each tile carrying an 8x8 mask, appended to the tiles' cells, so unconverged cells are the ones
// under pressure. Each pass's masks come from trees that have seen every pass before it, as each of MoonRay's
// tiles reads trees its region rebuilt when the region finished the pass before (AdaptiveRegions::update).
#pragma once
#include "async_adaptive_core.h"
#include <algorithm>
#include <cstdint>
#include <vector>

namespace xpu2::interactive::async::adaptive {

struct Pass {
    U32 start, end;  // sample counts: each active pixel goes from start to end samples
};

// MoonRay's batch adaptive passes (it renders them progressively): one sample, then 4, 6, 8, ... more.
inline std::vector<Pass> schedule(U32 maxSamples) {
    std::vector<Pass> passes{{0, 1}};
    U32 current = 1, remaining = maxSamples - 1, size = 4;
    while (remaining > size && passes.size() < 999) {
        passes.push_back({current, current + size});
        remaining -= size;
        current += size;
        size += 2;
    }
    if (remaining) passes.push_back({current, current + remaining});
    return passes;
}

// One region's error tree (AdaptiveRegionTree), built with the arithmetic the GPU's chain shares
// (async_adaptive_core.h).
class Tree {
public:
    Tree(IBox root, float target) : root_(root), target_(target), sat_(size_t(width() + 1) * (height() + 1), 0.0) {
        nodes_.push_back({{float(root.x0), float(root.y0), float(root.x1), float(root.y1)}, -1, 0});
    }

    // Rebuilds the tree from the image's per-pixel errors (pixelError, async_integrator.h), row by row with the
    // given stride.
    void update(const float* errors, int stride) {
        nodes_.resize(1);
        nodes_[0].children = -1;
        nodes_[0].complete = 0;
        // A summed-area table of the errors: any node's marginal sums in O(length).
        const size_t w1 = size_t(width()) + 1;
        for (int y = root_.y0; y < root_.y1; ++y) {
            double row = 0;
            const size_t r = size_t(y - root_.y0);
            for (int x = root_.x0; x < root_.x1; ++x) {
                const float e = errors[size_t(y) * stride + x];
                // Not every pixel has both halves yet: sample everything.
                if (e < 0) return;
                row += e;
                const size_t c = size_t(x - root_.x0) + 1;
                sat_[(r + 1) * w1 + c] = sat_[r * w1 + c] + row;
            }
        }
        updateNode(0);
    }
    bool done() const { return nodes_[0].complete != 0; }
    IBox root() const { return root_; }
    const std::vector<Node>& nodes() const { return nodes_; }

    // The pixels of an 8x8 tile at (tx, ty) still to sample (bit y*8+x), filled to their bounding rectangle.
    std::uint64_t sampleArea(int tx, int ty) const { return adaptive::sampleArea(nodes_.data(), tx, ty); }

private:
    int width() const { return root_.x1 - root_.x0; }
    int height() const { return root_.y1 - root_.y0; }

    void updateNode(int index) {
        FBox left, right;
        const Sat sat{sat_.data(), root_.x0, root_.y0, width() + 1};
        const int fate = decide(sat, root_, nodes_[index].bounds, target_, left, right);
        if (fate == Converged) nodes_[index].complete = 1;
        if (fate != Split) return;
        const int first = int(nodes_.size());
        nodes_.push_back({left, -1, 0});
        nodes_.push_back({right, -1, 0});
        nodes_[index].children = first;
        updateNode(first);
        updateNode(first + 1);
        if (nodes_[first].complete && nodes_[first + 1].complete) nodes_[index].complete = 1;
    }

    IBox root_;
    float target_;
    std::vector<double> sat_;  // (width + 1) x (height + 1), the first row and column zero
    std::vector<Node> nodes_;
};

// The image's overlapping regions (OverlappingRegions with 8-pixel tiles, an 8-pixel overlap and up to 4x4
// regions), each with its own tree. A tile's mask comes from the region its corner lies in.
class Regions {
public:
    Regions(int width, int height, float target) : width_(width), height_(height), target_(target) {
        constexpr int tile = 8, overlap = 8, desired = 4;
        const int minW = tile + overlap, minH = tile + overlap;
        if (minW >= width || minH >= height) {
            layout_.regionW = width;
            layout_.regionH = height;
            layout_.perDim = 1;
        } else {
            layout_.perDim = std::max(1, std::min(desired, std::min(width / minW, height / minH)));
            layout_.regionW = roundUp(1 + (width - 1) / layout_.perDim, tile);
            layout_.regionH = roundUp(1 + (height - 1) / layout_.perDim, tile);
        }
        const int perDim = layout_.perDim, regionW = layout_.regionW, regionH = layout_.regionH;
        for (int i = 0; i < perDim * perDim; ++i) {
            const int rx = i % perDim, ry = i / perDim;
            IBox b{rx * regionW - overlap, ry * regionH - overlap, (rx + 1) * regionW + overlap, (ry + 1) * regionH + overlap};
            b = {std::max(b.x0, 0), std::max(b.y0, 0), std::min(b.x1, width), std::min(b.y1, height)};
            trees_.emplace_back(b, target);
            done_.push_back(false);
        }
    }
    size_t count() const { return trees_.size(); }
    // Rebuilds region i's tree; regions are independent, so they may rebuild at once.
    void update(size_t i, const float* errors) {
        trees_[i].update(errors, width_);
        done_[i] = trees_[i].done() ? 1 : 0;
    }
    bool done() const { return std::all_of(done_.begin(), done_.end(), [](char d) { return d != 0; }); }
    std::uint64_t sampleArea(int tx, int ty) const { return trees_[size_t(layout_.regionOf(tx, ty))].sampleArea(tx, ty); }
    const Layout& layout() const { return layout_; }
    const Tree& tree(size_t i) const { return trees_[i]; }
    float target() const { return target_; }

private:
    static int roundUp(int n, int m) { return n % m ? n + m - n % m : n; }
    int width_, height_;
    float target_;
    Layout layout_;
    std::vector<Tree> trees_;
    std::vector<char> done_;  // not vector<bool>: regions are written from different threads
};

// Cellular generations (the preview session's default; MoonRay's trees above are the option). Each adaptive pass is
// a generation of the image's 8x8 tiles as cells, and a live tile samples all its pixels in the pass. A tile's error
// is MoonRay's node error over it (areaError of its pixels' summed error: the test MoonRay's trees put to a leaf) over
// the target. Its own error keeps a tile alive at 1 or more; live neighbours (of its eight) keep it alive down to
// Survive when at least SurviveNeighbours are alive, and bring a dead tile back from Birth when at least
// BirthNeighbours are (it takes more to come back than to stay, so tiles do not flicker). A tile with a pixel still
// missing one of its halves stays alive. The rules decide only where samples go: every sample is MoonRay's estimator,
// so the image converges to MoonRay's.
class Cellular {
public:
    static constexpr float Survive = 0.5f, Birth = 0.75f;
    static constexpr int SurviveNeighbours = 3, BirthNeighbours = 5;

    Cellular(int width, int height, float target)
        : width_(width), height_(height), tilesX_((width + 7) / 8), tilesY_((height + 7) / 8), target_(target),
          alive_(size_t(tilesX_) * tilesY_, 1), next_(alive_.size(), 0), ratio_(alive_.size(), 0.0f) {}

    // Tiles outside the render region never live (inImage: each tile's pixels in the image).
    void deadForever(const std::vector<std::uint64_t>& inImage) {
        dead_.assign(alive_.size(), 0);
        for (size_t t = 0; t < alive_.size() && t < inImage.size(); ++t)
            if (!inImage[t]) dead_[t] = 1, alive_[t] = 0;
    }
    // The next generation from the image's per-pixel errors (pixelError, width a row); the live tiles' count.
    size_t update(const float* errors) {
        for (int ty = 0; ty < tilesY_; ++ty)
            for (int tx = 0; tx < tilesX_; ++tx) {
                double sum = 0;
                int n = 0;
                bool unknown = false;
                for (int y = ty * 8; y < std::min(height_, ty * 8 + 8); ++y)
                    for (int x = tx * 8; x < std::min(width_, tx * 8 + 8); ++x) {
                        const float e = errors[size_t(y) * size_t(width_) + size_t(x)];
                        if (e < 0) unknown = true;
                        else sum += e;
                        ++n;
                    }
                ratio_[size_t(ty) * tilesX_ + tx] = unknown ? 3.4e38f : areaError(float(sum), float(n)) / target_;
            }
        size_t live = 0;
        for (int ty = 0; ty < tilesY_; ++ty)
            for (int tx = 0; tx < tilesX_; ++tx) {
                const size_t t = size_t(ty) * tilesX_ + tx;
                int k = 0;
                for (int dy = -1; dy <= 1; ++dy)
                    for (int dx = -1; dx <= 1; ++dx) {
                        const int x = tx + dx, y = ty + dy;
                        if ((dx || dy) && x >= 0 && y >= 0 && x < tilesX_ && y < tilesY_ && alive_[size_t(y) * tilesX_ + x]) ++k;
                    }
                const float r = ratio_[t];
                next_[t] = alive_[t] ? (r >= 1.0f || (r >= Survive && k >= SurviveNeighbours))
                                     : (r >= 1.0f || (r >= Birth && k >= BirthNeighbours));
                if (!dead_.empty() && dead_[t]) next_[t] = 0;
                live += next_[t] ? 1 : 0;
            }
        alive_.swap(next_);
        ++generation_;
        return live;
    }
    bool alive(size_t tile) const { return alive_[tile] != 0; }
    U32 generation() const { return generation_; }

private:
    int width_, height_, tilesX_, tilesY_;
    float target_;
    std::vector<char> alive_, next_, dead_;
    std::vector<float> ratio_;
    U32 generation_ = 0;
};

}  // namespace xpu2::interactive::async::adaptive
