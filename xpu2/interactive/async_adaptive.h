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

}  // namespace xpu2::interactive::async::adaptive
