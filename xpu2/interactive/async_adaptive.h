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
#include "async_integrator.h"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
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

struct IBox {
    int x0, y0, x1, y1;
};
struct FBox {
    float x0, y0, x1, y1;
};

// One region's error tree (AdaptiveRegionTree).
class Tree {
public:
    Tree(IBox root, float target) : root_(root), target_(target), sat_(size_t(width() + 1) * (height() + 1), 0.0) {
        nodes_.push_back({{float(root.x0), float(root.y0), float(root.x1), float(root.y1)}, -1, false});
    }

    // Rebuilds the tree from the image's per-pixel errors (pixelError, async_integrator.h), row by row with the
    // given stride. Returns the largest leaf error.
    float update(const float* errors, int stride) {
        nodes_.resize(1);
        nodes_[0].children = -1;
        nodes_[0].complete = false;
        // A summed-area table of the errors: any node's marginal sums in O(length).
        const size_t w1 = size_t(width()) + 1;
        for (int y = root_.y0; y < root_.y1; ++y) {
            double row = 0;
            const size_t r = size_t(y - root_.y0);
            for (int x = root_.x0; x < root_.x1; ++x) {
                const float e = errors[size_t(y) * stride + x];
                // Not every pixel has both halves yet: sample everything.
                if (e < 0) return std::numeric_limits<float>::infinity();
                row += e;
                const size_t c = size_t(x - root_.x0) + 1;
                sat_[(r + 1) * w1 + c] = sat_[r * w1 + c] + row;
            }
        }
        return updateNode(0);
    }
    bool done() const { return nodes_[0].complete; }

    // The pixels of an 8x8 tile at (tx, ty) still to sample (bit y*8+x), filled to their bounding rectangle.
    std::uint64_t sampleArea(int tx, int ty) const {
        std::uint64_t mask = sampleAreaOf(0, {float(tx), float(ty), float(tx + 8), float(ty + 8)}, tx, ty);
        return fillGaps(mask);
    }

private:
    struct Node {
        FBox bounds;
        int children;  // index of the first of two children, or -1
        bool complete;
    };
    static constexpr float MinNodeSize = 1.27201964951407f;  // sqrt of the golden ratio
    static constexpr float MaxNodeSize = 16.0f;
    static constexpr float SplitThreshold = 256.0f;

    int width() const { return root_.x1 - root_.x0; }
    int height() const { return root_.y1 - root_.y0; }

    // The node's error, from its summed pixel error and area; MoonRay hard-codes the image area.
    static float areaError(float error, float area) {
        constexpr float imageArea = ((815.0f - 0.0f) * (1943.0f - -24.0f)) / 4.0f;
        return error / std::sqrt(area * imageArea);
    }
    static float splitHelper(float location, float length) {
        if (length * location >= MinNodeSize) return location;
        if (length >= MinNodeSize * 2) return MinNodeSize / length;
        return std::numeric_limits<float>::quiet_NaN();
    }
    static float splitLocation(float location, float length) {
        return location <= 0.5f ? splitHelper(location, length) : 1.0f - splitHelper(1.0f - location, length);
    }
    // A node's partial sums of the error marginals along its split axis: entry i
    // sums its first i + 1 columns (rows when vertical). They never decrease.
    struct Marginals {
        const Tree& tree;
        IBox ib;
        bool horizontal;
        int n;
        float operator()(int i) const {
            return horizontal ? float(tree.rect(ib.x0, ib.y0, ib.x0 + i + 1, ib.y1))
                              : float(tree.rect(ib.x0, ib.y0, ib.x1, ib.y0 + i + 1));
        }
        float total() const { return n > 0 ? (*this)(n - 1) : 0.f; }
    };
    // The fraction along a node that halves its accumulated error; the first entry
    // above half is found by bisection (std::upper_bound over the entries).
    static float midpoint(const Marginals& m) {
        const float half = m.total() * 0.5f;
        int i = m.n / 2;
        if (m.total() != 0.f) {
            int lo = 0, hi = m.n;
            while (lo < hi) {
                const int mid = (lo + hi) / 2;
                if (m(mid) > half) hi = mid;
                else lo = mid + 1;
            }
            i = lo;
        }
        i = std::min(std::max(i, 1), m.n - 1);
        const float lower = m(i - 1), higher = m(i), delta = higher - lower;
        const float offset = delta > 0 ? (half - lower) / delta : 0.5f;
        return (float(i) + offset) / float(m.n);
    }
    static IBox roundLarger(const FBox& b) {
        return {int(std::floor(b.x0)), int(std::floor(b.y0)), int(std::ceil(b.x1)), int(std::ceil(b.y1))};
    }

    float updateNode(int index) {
        const FBox b = nodes_[index].bounds;
        const float w = b.x1 - b.x0, h = b.y1 - b.y0;
        const bool horizontal = w > h;
        const float length = std::max(w, h);
        IBox ib = roundLarger(b);
        ib = {std::max(ib.x0, root_.x0), std::max(ib.y0, root_.y0), std::min(ib.x1, root_.x1), std::min(ib.y1, root_.y1)};
        const Marginals accumulated{*this, ib, horizontal, horizontal ? ib.x1 - ib.x0 : ib.y1 - ib.y0};
        const float error = areaError(accumulated.total(), w * h);
        if (error < target_ && length < MaxNodeSize) {
            nodes_[index].complete = true;
            return error;
        }
        if (error < target_ * SplitThreshold && length > MinNodeSize * 2) {
            const float offset = splitLocation(midpoint(accumulated), length);
            if (std::isnan(offset)) return error;
            const int first = int(nodes_.size());
            FBox left = b, right = b;
            if (horizontal) left.x1 = right.x0 = b.x0 + offset * w;
            else left.y1 = right.y0 = b.y0 + offset * h;
            nodes_.push_back({left, -1, false});
            nodes_.push_back({right, -1, false});
            nodes_[index].children = first;
            const float a = updateNode(first), c = updateNode(first + 1);
            if (nodes_[first].complete && nodes_[first + 1].complete) nodes_[index].complete = true;
            return std::max(a, c);
        }
        return error;
    }

    std::uint64_t sampleAreaOf(int index, const FBox& tile, int tx, int ty) const {
        const Node& n = nodes_[index];
        if (n.complete) return 0;
        const FBox i{std::max(n.bounds.x0, tile.x0), std::max(n.bounds.y0, tile.y0), std::min(n.bounds.x1, tile.x1),
                     std::min(n.bounds.y1, tile.y1)};
        if (i.x1 <= i.x0 || i.y1 <= i.y0) return 0;
        if (n.children >= 0)
            return sampleAreaOf(n.children, tile, tx, ty) | sampleAreaOf(n.children + 1, tile, tx, ty);
        std::uint64_t mask = 0;
        const IBox r = roundLarger(i);
        for (int y = r.y0; y < r.y1; ++y)
            for (int x = r.x0; x < r.x1; ++x)
                if (x >= tx && x < tx + 8 && y >= ty && y < ty + 8) mask |= 1ull << ((y - ty) * 8 + (x - tx));
        return mask;
    }
    // ActivePixelMask::fillGaps: every pixel within the rows and columns the active ones span.
    static std::uint64_t fillGaps(std::uint64_t m) {
        if (!m) return 0;
        int rowLo = 8, rowHi = -1, colLo = 8, colHi = -1;
        for (int b = 0; b < 64; ++b)
            if (m >> b & 1) {
                rowLo = std::min(rowLo, b / 8);
                rowHi = std::max(rowHi, b / 8);
                colLo = std::min(colLo, b % 8);
                colHi = std::max(colHi, b % 8);
            }
        std::uint64_t out = 0;
        for (int y = rowLo; y <= rowHi; ++y)
            for (int x = colLo; x <= colHi; ++x) out |= 1ull << (y * 8 + x);
        return out;
    }

    // The summed error of the pixels in [x0, x1) x [y0, y1), image coordinates.
    double rect(int x0, int y0, int x1, int y1) const {
        const size_t w1 = size_t(width()) + 1;
        auto s = [&](int x, int y) { return sat_[size_t(y - root_.y0) * w1 + size_t(x - root_.x0)]; };
        return s(x1, y1) - s(x0, y1) - s(x1, y0) + s(x0, y0);
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
    Regions(int width, int height, float target) : width_(width), height_(height) {
        constexpr int tile = 8, overlap = 8, desired = 4;
        const int minW = tile + overlap, minH = tile + overlap;
        if (minW >= width || minH >= height) {
            regionW_ = width;
            regionH_ = height;
            perDim_ = 1;
        } else {
            perDim_ = std::max(1, std::min(desired, std::min(width / minW, height / minH)));
            regionW_ = roundUp(1 + (width - 1) / perDim_, tile);
            regionH_ = roundUp(1 + (height - 1) / perDim_, tile);
        }
        for (int i = 0; i < perDim_ * perDim_; ++i) {
            const int rx = i % perDim_, ry = i / perDim_;
            IBox b{rx * regionW_ - overlap, ry * regionH_ - overlap, (rx + 1) * regionW_ + overlap, (ry + 1) * regionH_ + overlap};
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
    std::uint64_t sampleArea(int tx, int ty) const {
        const int index = std::min(ty / regionH_, perDim_ - 1) * perDim_ + std::min(tx / regionW_, perDim_ - 1);
        return trees_[size_t(index)].sampleArea(tx, ty);
    }

private:
    static int roundUp(int n, int m) { return n % m ? n + m - n % m : n; }
    int width_, height_, regionW_ = 0, regionH_ = 0, perDim_ = 1;
    std::vector<Tree> trees_;
    std::vector<char> done_;  // not vector<bool>: regions are written from different threads
};

}  // namespace xpu2::interactive::async::adaptive
