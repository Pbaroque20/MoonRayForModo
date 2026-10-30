// The arithmetic of MoonRay's adaptive error trees, shared by the host
// (async_adaptive.h) and the GPU's pass chain (async_adaptive.cu), so both build
// the same trees, and so the same tile masks, from the same errors.
//
// Adapted from MoonRay rndr/adaptive/AdaptiveRegionTree.{h,cc} and
// ActivePixelMask.h, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC;
// see MOONRAY_LICENSE.txt. Products and sums that a CUDA compiler could fuse are
// written with mulRn and addRn (async_integrator.h).
#pragma once
#include "async_integrator.h"

namespace xpu2::interactive::async::adaptive {

struct IBox {
    int x0, y0, x1, y1;
};
struct FBox {
    float x0, y0, x1, y1;
};

// A tree node: its bounds, the first of its two children (-1: a leaf), and
// whether it has converged (an inner node has once both children have).
struct Node {
    FBox bounds;
    int children;
    int complete;
};

constexpr float MinNodeSize = 1.27201964951407f;  // sqrt of the golden ratio
constexpr float MaxNodeSize = 16.0f;
constexpr float SplitThreshold = 256.0f;
constexpr float NoSplit = -1.0f;

X2_HD inline int imin(int a, int b) { return b < a ? b : a; }
X2_HD inline int imax(int a, int b) { return a < b ? b : a; }
X2_HD inline float fmin2(float a, float b) { return b < a ? b : a; }
X2_HD inline float fmax2(float a, float b) { return a < b ? b : a; }

X2_HD inline IBox roundLarger(const FBox& b) {
    return {int(floorf(b.x0)), int(floorf(b.y0)), int(ceilf(b.x1)), int(ceilf(b.y1))};
}

// MoonRay's most nodes a region's tree can have (AdaptiveRegionTree::maxNodes).
X2_HD inline int maxNodes(const IBox& b) {
    const int w = b.x1 - b.x0, h = b.y1 - b.y0;
    if (w <= 0 || h <= 0) return 0;
    return 2 * int(ceilf(mulRn(float(w) / MinNodeSize, float(h) / MinNodeSize))) - 1;
}

// A node's error, from its summed pixel error and area; MoonRay hard-codes the
// image area, so regions of any image size are judged alike.
X2_HD inline float areaError(float error, float area) {
    constexpr float imageArea = ((815.0f - 0.0f) * (1943.0f - -24.0f)) / 4.0f;
    return error / sqrtf(mulRn(area, imageArea));
}
X2_HD inline float splitHelper(float location, float length) {
    if (mulRn(length, location) >= MinNodeSize) return location;
    if (length >= MinNodeSize * 2) return MinNodeSize / length;
    return NoSplit;
}
X2_HD inline float splitLocation(float location, float length) {
    if (location <= 0.5f) return splitHelper(location, length);
    const float h = splitHelper(1.0f - location, length);
    return h == NoSplit ? NoSplit : 1.0f - h;
}

// A region's summed-area table of pixel errors: (width + 1) x (height + 1)
// doubles, the first row and column zero, for the region with corner (x0, y0).
struct Sat {
    const double* s;
    int x0, y0, w1;
    // The summed error of the pixels in [ax, bx) x [ay, by), image coordinates.
    X2_HD double rect(int ax, int ay, int bx, int by) const {
        auto at = [&](int x, int y) { return s[size_t(y - y0) * size_t(w1) + size_t(x - x0)]; };
        return at(bx, by) - at(ax, by) - at(bx, ay) + at(ax, ay);
    }
};

// A node's partial sums of the error marginals along its split axis: entry i
// sums its first i + 1 columns (rows when vertical). They never decrease.
struct Marginals {
    const Sat& sat;
    IBox ib;
    bool horizontal;
    int n;
    X2_HD float operator()(int i) const {
        return horizontal ? float(sat.rect(ib.x0, ib.y0, ib.x0 + i + 1, ib.y1))
                          : float(sat.rect(ib.x0, ib.y0, ib.x1, ib.y0 + i + 1));
    }
    X2_HD float total() const { return n > 0 ? (*this)(n - 1) : 0.f; }
};

// The fraction along a node that halves its accumulated error; the first entry
// above half is found by bisection (std::upper_bound over the entries).
X2_HD inline float midpoint(const Marginals& m) {
    const float total = m.total(), half = mulRn(total, 0.5f);
    int i = m.n / 2;
    if (total != 0.f) {
        int lo = 0, hi = m.n;
        while (lo < hi) {
            const int mid = (lo + hi) / 2;
            if (m(mid) > half) hi = mid;
            else lo = mid + 1;
        }
        i = lo;
    }
    i = imin(imax(i, 1), m.n - 1);
    const float lower = m(i - 1), higher = m(i), delta = higher - lower;
    const float offset = delta > 0 ? (half - lower) / delta : 0.5f;
    return addRn(float(i), offset) / float(m.n);
}

enum NodeFate : int { Unconverged = 0, Converged = 1, Split = 2 };

// What becomes of a node of the tree rooted at root (AdaptiveRegionTree::
// updateImpl): it has converged, it splits into left and right at the midpoint
// of its error along its longer side, or it stays an unconverged leaf.
X2_HD inline int decide(const Sat& sat, const IBox& root, const FBox& b, float target, FBox& left, FBox& right) {
    const float w = b.x1 - b.x0, h = b.y1 - b.y0;
    const bool horizontal = w > h;
    const float length = horizontal ? w : h;
    IBox ib = roundLarger(b);
    ib = {imax(ib.x0, root.x0), imax(ib.y0, root.y0), imin(ib.x1, root.x1), imin(ib.y1, root.y1)};
    const Marginals m{sat, ib, horizontal, horizontal ? ib.x1 - ib.x0 : ib.y1 - ib.y0};
    const float error = areaError(m.total(), mulRn(w, h));
    if (error < target && length < MaxNodeSize) return Converged;
    if (error < mulRn(target, SplitThreshold) && length > MinNodeSize * 2) {
        const float offset = splitLocation(midpoint(m), length);
        if (offset == NoSplit) return Unconverged;
        left = right = b;
        if (horizontal) left.x1 = right.x0 = addRn(b.x0, mulRn(offset, w));
        else left.y1 = right.y0 = addRn(b.y0, mulRn(offset, h));
        return Split;
    }
    return Unconverged;
}

// ActivePixelMask::fillGaps: every pixel within the rows and columns the active
// ones span.
X2_HD inline U64 fillGaps(U64 m) {
    if (!m) return 0;
    int rowLo = 8, rowHi = -1, colLo = 8, colHi = -1;
    for (int b = 0; b < 64; ++b)
        if (m >> b & 1) {
            rowLo = imin(rowLo, b / 8);
            rowHi = imax(rowHi, b / 8);
            colLo = imin(colLo, b % 8);
            colHi = imax(colHi, b % 8);
        }
    U64 out = 0;
    for (int y = rowLo; y <= rowHi; ++y)
        for (int x = colLo; x <= colHi; ++x) out |= U64(1) << (y * 8 + x);
    return out;
}

constexpr int SampleAreaStack = 128;

// The pixels of the 8x8 tile at (tx, ty) a tree still samples (bit y*8+x),
// filled to their bounding rectangle (AdaptiveRegionTree::getSampleArea). A tree
// deeper than the stack (never in practice) samples the whole tile.
X2_HD inline U64 sampleArea(const Node* nodes, int tx, int ty) {
    const FBox tile{float(tx), float(ty), float(tx + 8), float(ty + 8)};
    int stack[SampleAreaStack], top = 0;
    stack[top++] = 0;
    U64 mask = 0;
    while (top) {
        const Node n = nodes[stack[--top]];
        if (n.complete) continue;
        const FBox i{fmax2(n.bounds.x0, tile.x0), fmax2(n.bounds.y0, tile.y0), fmin2(n.bounds.x1, tile.x1),
                     fmin2(n.bounds.y1, tile.y1)};
        if (i.x1 <= i.x0 || i.y1 <= i.y0) continue;
        if (n.children >= 0) {
            if (top + 2 > SampleAreaStack) return ~U64(0);
            stack[top++] = n.children;
            stack[top++] = n.children + 1;
            continue;
        }
        const IBox r = roundLarger(i);
        for (int y = imax(r.y0, ty); y < imin(r.y1, ty + 8); ++y)
            for (int x = imax(r.x0, tx); x < imin(r.x1, tx + 8); ++x) mask |= U64(1) << ((y - ty) * 8 + (x - tx));
    }
    return fillGaps(mask);
}

// The overlapping regions' layout (OverlappingRegions): up to 4x4 regions of
// whole 8-pixel tiles, each widened by 8 pixels of overlap. A tile reads the tree
// of the region its corner lies in.
struct Layout {
    int perDim = 1, regionW = 0, regionH = 0;
    X2_HD int regionOf(int tx, int ty) const {
        return imin(ty / regionH, perDim - 1) * perDim + imin(tx / regionW, perDim - 1);
    }
};

}  // namespace xpu2::interactive::async::adaptive
