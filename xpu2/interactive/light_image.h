// MoonRay's image distributions for textured lights, shared by the CPU and CUDA lanes: a light's texture as its
// pixels and, for each mip level, a 2D distribution (a conditional 1D distribution a row and a marginal one over the
// rows) that samples the texture by luminance, with MoonRay's four texture filters, its texture transform and
// border colour.
//
// Adapted from MoonRay pbr/core/Distribution.cc and Distribution.ispc (GuideDistribution1D, Distribution2D,
// ImageDistribution) and pbr/light/EnvLight.ispc, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC; see
// MOONRAY_LICENSE.txt. XPU's light sampling is the ISPC code, which matches the C++ step for step.
#pragma once
#include "surface_core.h"

namespace xpu2::interactive::lights {
using surface::V3;
using sample::U32;

constexpr float SEpsilon = 1e-6f;  // scene_rdl2 sEpsilon (C++ and ISPC)
constexpr float SOneMinusEpsilon = 1.0f - 1e-6f;

enum TextureFilter : U32 { FilterNearest = 0, FilterBilinear = 1, FilterNearestMipNearest = 2, FilterBilinearMipNearest = 3 };

// One GuideDistribution1D: its cdf and guide entries (offset, size) and its cached values.
struct Dist1D {
    U32 offset, size;
    float totalWeight, invTotalWeight, invSize;
    float thresholdLow, thresholdHigh, linearCoeffLow, linearCoeffHigh;
    U32 pad[3];
};
// One mip level: its size, its first pixel (a float offset, three floats a pixel), and its distributions: the
// conditional of each row, then the marginal.
struct ImageLevel {
    U32 width, height, pixels, dists;
};
// A light's ImageDistribution. Its rows run from the bottom of the picture, as MoonRay flips it on reading.
struct Image {
    const float* pixels;
    const float* cdf;
    const U32* guide;
    const Dist1D* dists;
    const ImageLevel* levels;
    U32 levelCount, width, height, transformed;
    float m[9];  // the texture transform (MoonRay's mTransformation), rows
    float repsU, repsV;
    U32 mirrorU, mirrorV;
    float border[3];
    U32 pad;
};

X2_HD inline void intAndFrac(float x, int& i, float& f) {
    const float fl = floorf(x);
    i = int(fl);
    f = x - fl;
}
X2_HD inline float lerpF(float a, float b, float t) { return (b - a) * t + a; }  // scene_rdl2 lerp
X2_HD inline V3 lerpV(V3 a, V3 b, float t) { return {lerpF(a.x, b.x, t), lerpF(a.y, b.y, t), lerpF(a.z, b.z, t)}; }

// ---- GuideDistribution1D
X2_HD inline int guideIndex(const Image& im, const Dist1D& d, float r) {
    const float rj = r * float(d.size);
    U32 j = U32(int(rj));
    j = j < d.size - 1 ? j : d.size - 1;
    return int(im.guide[d.offset + j]);
}
X2_HD inline float pdfContinuous(const Image& im, const Dist1D& d, float u) {
    U32 i = U32(u * float(d.size));
    i = i < d.size - 1 ? i : d.size - 1;
    const float* cdf = im.cdf + d.offset;
    const float prev = i > 0 ? cdf[i - 1] : 0.0f;
    return (cdf[i] - prev) * d.invTotalWeight * float(d.size);
}
X2_HD inline float sampleContinuous(const Image& im, const Dist1D& d, float r, float* pdf, U32* index) {
    U32 i = U32(guideIndex(im, d, r));
    const float* cdf = im.cdf + d.offset;
    const float rw = r * d.totalWeight;
    while (cdf[i] < rw && i + 1 < d.size) ++i;
    if (index) *index = i;
    const float prev = i > 0 ? cdf[i - 1] : 0.0f;
    float invCdf = (float(i) + (rw - prev) / (cdf[i] - prev)) * d.invSize;
    invCdf = fminf(invCdf, SOneMinusEpsilon);
    if (pdf) *pdf = (cdf[i] - prev) * d.invTotalWeight * float(d.size);
    return invCdf;
}
X2_HD inline float quadraticHelper(float c0, float c1, float c2, float twoK, float& p) {
    const float p0 = c1 - c0, p1 = c2 - c1;
    const float A = p1 - p0, B = p0, C = c0 + c1 - twoK;
    const float discrim = B * B - A * C;
    const float denom = -B - sqrtf(discrim);
    const float t = denom != 0.0f ? C / denom : 0.0f;
    p = lerpF(p0, p1, t);
    return t;
}
X2_HD inline float sampleLinear(const Image& im, const Dist1D& d, float r, float* pdf) {
    if (r <= d.thresholdLow) return fminf(r * d.linearCoeffLow, SOneMinusEpsilon);
    if (r >= d.thresholdHigh) return fminf(1.0f - (1.0f - r) * d.linearCoeffHigh, SOneMinusEpsilon);
    const float* cdf = im.cdf + d.offset;
    int i = guideIndex(im, d, r);
    i = i > 1 ? i : 1;
    const float twoWr = 2.0f * d.totalWeight * r;
    float c0 = i >= 2 ? cdf[i - 2] : 0.0f, c1 = cdf[i - 1], c2 = cdf[i];
    while (c1 + c2 < twoWr && i + 1 < int(d.size)) {
        ++i;
        c0 = c1;
        c1 = c2;
        c2 = cdf[i];
    }
    float p;
    const float t = quadraticHelper(c0, c1, c2, twoWr, p);
    if (pdf) *pdf = p * d.invTotalWeight * float(d.size);
    return fminf((float(i) + 0.5f + t) * d.invSize, SOneMinusEpsilon);
}
// Distribution.cc's sampleLinearBlended: sampleLinear over two rows' cdfs blended by s.
X2_HD inline float sampleLinearBlended(const Image& im, float r, float* pdf, const Dist1D& a, const Dist1D& b, float s) {
    if (r <= lerpF(a.thresholdLow, b.thresholdLow, s)) return fminf(r * lerpF(a.linearCoeffLow, b.linearCoeffLow, s), SOneMinusEpsilon);
    if (r >= lerpF(a.thresholdHigh, b.thresholdHigh, s))
        return fminf(1.0f - (1.0f - r) * lerpF(a.linearCoeffHigh, b.linearCoeffHigh, s), SOneMinusEpsilon);
    int i = guideIndex(im, a, r), ib = guideIndex(im, b, r);
    i = i < ib ? i : ib;
    i = i > 1 ? i : 1;
    const float w = lerpF(a.totalWeight, b.totalWeight, s);
    const float twoWr = 2.0f * w * r;
    const float* cdf0 = im.cdf + a.offset;
    const float* cdf1 = im.cdf + b.offset;
    float c0 = i >= 2 ? lerpF(cdf0[i - 2], cdf1[i - 2], s) : 0.0f;
    float c1 = lerpF(cdf0[i - 1], cdf1[i - 1], s);
    float c2 = lerpF(cdf0[i], cdf1[i], s);
    const int n = int(a.size);
    while (c1 + c2 < twoWr) {
        ++i;
        if (i >= n) return fminf(1.0f - (1.0f - r) * lerpF(a.linearCoeffHigh, b.linearCoeffHigh, s), SOneMinusEpsilon);
        c0 = c1;
        c1 = c2;
        c2 = lerpF(cdf0[i], cdf1[i], s);
    }
    float p;
    const float t = quadraticHelper(c0, c1, c2, twoWr, p);
    if (pdf) *pdf = p * a.invSize / w;
    return fminf((float(i) + 0.5f + t) * a.invSize, SOneMinusEpsilon);
}

// ---- Distribution2D of one mip level
X2_HD inline const Dist1D& conditional(const Image& im, const ImageLevel& lv, U32 row) { return im.dists[lv.dists + row]; }
X2_HD inline const Dist1D& marginal(const Image& im, const ImageLevel& lv) { return im.dists[lv.dists + lv.height]; }
X2_HD inline float pdfNearest2D(const Image& im, const ImageLevel& lv, float u, float v) {
    const Dist1D& marg = marginal(im, lv);
    U32 vi = U32(v * float(marg.size));
    vi = vi < marg.size - 1 ? vi : marg.size - 1;
    return pdfContinuous(im, marg, v) * pdfContinuous(im, conditional(im, lv, vi), u);
}
X2_HD inline float pdfBilinear2D(const Image& im, const ImageLevel& lv, float u, float v) {
    if (u < 0.0f || u >= 1.0f || v < 0.0f || v >= 1.0f) return 0.0f;
    const Dist1D& marg = marginal(im, lv);
    const float pMarg = pdfContinuous(im, marg, v);
    const int n = int(marg.size);
    int i1;
    float s;
    intAndFrac(v * float(n) + 0.5f, i1, s);
    int i0 = i1 - 1;
    i0 = i0 > 0 ? i0 : 0;
    i1 = i1 < n - 1 ? i1 : n - 1;
    const float pCond = lerpF(pdfContinuous(im, conditional(im, lv, U32(i0)), u), pdfContinuous(im, conditional(im, lv, U32(i1)), u), s);
    return pMarg * pCond;
}
X2_HD inline void sampleNearest2D(const Image& im, const ImageLevel& lv, float ru, float rv, float& u, float& v, float* pdf) {
    U32 row;
    float pdfMarg, pdfCond;
    v = sampleContinuous(im, marginal(im, lv), rv, &pdfMarg, &row);
    u = sampleContinuous(im, conditional(im, lv, row), ru, &pdfCond, nullptr);
    if (pdf) *pdf = pdfMarg * pdfCond;
}
X2_HD inline void sampleBilinear2D(const Image& im, const ImageLevel& lv, float ru, float rv, float& u, float& v, float* pdf) {
    float pMarg, pCond;
    const Dist1D& marg = marginal(im, lv);
    v = sampleLinear(im, marg, rv, &pMarg);
    const int n = int(marg.size);
    int i1;
    float s;
    intAndFrac(v * float(n), i1, s);
    int i0 = i1 - 1;
    i0 = i0 > 0 ? i0 : 0;
    i1 = i1 < n - 1 ? i1 : n - 1;
    u = sampleLinearBlended(im, ru, &pCond, conditional(im, lv, U32(i0)), conditional(im, lv, U32(i1)), s);
    if (pdf) *pdf = pMarg * pCond;
}

// ---- ImageDistribution
X2_HD inline U32 mipOf(const Image& im, float mipLevel) {
    float m = fminf(fmaxf(mipLevel, 0.0f), float(im.levelCount - 1));
    if (!(m == m)) m = 0.0f;  // a footprint of -infinity minus a finite angle stays -infinity: level 0
    return U32(int(roundf(m)));
}
X2_HD inline V3 lookup(const Image& im, int xi, int yi, U32 level) {
    const ImageLevel& lv = im.levels[level];
    const int w = int(lv.width), h = int(lv.height);
    xi = xi < 0 ? 0 : xi >= w ? w - 1 : xi;
    yi = yi < 0 ? 0 : yi >= h ? h - 1 : yi;
    const float* p = im.pixels + lv.pixels + size_t(yi * w + xi) * 3;
    return {p[0], p[1], p[2]};
}
X2_HD inline V3 bilerpV(V3 c00, V3 c10, V3 c01, V3 c11, float s, float t) { return lerpV(lerpV(c00, c10, s), lerpV(c01, c11, s), t); }
X2_HD inline V3 filterNearestAt(const Image& im, float u, float v, U32 level) {
    const ImageLevel& lv = im.levels[level];
    return lookup(im, int(floorf(u * float(lv.width))), int(floorf(v * float(lv.height))), level);
}
X2_HD inline V3 filterBilinearAt(const Image& im, float u, float v, U32 level) {
    const ImageLevel& lv = im.levels[level];
    int xi, yi;
    float xf, yf;
    intAndFrac(u * float(lv.width) - 0.5f, xi, xf);
    intAndFrac(v * float(lv.height) - 0.5f, yi, yf);
    return bilerpV(lookup(im, xi, yi, level), lookup(im, xi + 1, yi, level), lookup(im, xi, yi + 1, level),
                   lookup(im, xi + 1, yi + 1, level), xf, yf);
}
X2_HD inline V3 applyTexFilter(const Image& im, float u, float v, float mipLevel, U32 filter) {
    switch (filter) {
    case FilterBilinear: return filterBilinearAt(im, u, v, 0);
    case FilterNearestMipNearest: return filterNearestAt(im, u, v, mipOf(im, mipLevel));
    case FilterBilinearMipNearest: return filterBilinearAt(im, u, v, mipOf(im, mipLevel));
    default: return filterNearestAt(im, u, v, 0);
    }
}
X2_HD inline V3 imageEval(const Image& im, float u, float v, float mipLevel, U32 filter) {
    if (!im.transformed) {
        if (u < 0.0f || u > 1.0f || v < 0.0f || v > 1.0f) return {im.border[0], im.border[1], im.border[2]};
        return applyTexFilter(im, u, v, mipLevel, filter);
    }
    // textureLookupTransformed: (u, v, 1) times the transform, as MoonRay's row vectors.
    float tu = u * im.m[0] + v * im.m[3] + im.m[6];
    float tv = u * im.m[1] + v * im.m[4] + im.m[7];
    if (tu < 0.0f || tu > im.repsU || tv < 0.0f || tv > im.repsV) return {im.border[0], im.border[1], im.border[2]};
    const float uFloor = floorf(tu), vFloor = floorf(tv);
    tu -= uFloor;
    tv -= vFloor;
    if (im.mirrorU && (int(uFloor) & 1)) tu = 1.0f - tu;
    if (im.mirrorV && (int(vFloor) & 1)) tv = 1.0f - tv;
    return applyTexFilter(im, tu, tv, mipLevel, filter);
}
X2_HD inline float imagePdf(const Image& im, float u, float v, float mipLevel, U32 filter) {
    switch (filter) {
    case FilterBilinear: return pdfBilinear2D(im, im.levels[0], u, v);
    case FilterNearestMipNearest: return pdfNearest2D(im, im.levels[mipOf(im, mipLevel)], u, v);
    case FilterBilinearMipNearest: return pdfBilinear2D(im, im.levels[mipOf(im, mipLevel)], u, v);
    default: return pdfNearest2D(im, im.levels[0], u, v);
    }
}
X2_HD inline void imageSample(const Image& im, float ru, float rv, float mipLevel, U32 filter, float& u, float& v) {
    switch (filter) {
    case FilterBilinear: sampleBilinear2D(im, im.levels[0], ru, rv, u, v, nullptr); break;
    case FilterNearestMipNearest: sampleNearest2D(im, im.levels[mipOf(im, mipLevel)], ru, rv, u, v, nullptr); break;
    case FilterBilinearMipNearest: sampleBilinear2D(im, im.levels[mipOf(im, mipLevel)], ru, rv, u, v, nullptr); break;
    default: sampleNearest2D(im, im.levels[0], ru, rv, u, v, nullptr); break;
    }
}

// ---- Latitude-longitude mapping (EnvLight, SphereLight)
// ISPC's dw_acos (scene_rdl2 Transcendental.ispc): XPU's lights meet BSDF rays through it.
X2_HD inline float dwAcos(float x) {
    const float c0 = 1.5707963039207744f, c1 = -0.2145986966117427f, c2 = 0.08897731218991513f, c3 = -0.05016418844436275f,
                c4 = 0.030862751448600963f, c5 = -0.017045102007693682f, c6 = 0.006638618338665405f, c7 = -0.0012534570550072417f;
    const float c0t = 1.5707964f, c3t = -0.0501641f;
    if (x >= 0.0f) {
        const float p = c0 + x * (c1 + x * (c2 + x * (c3t + x * (c4 + x * (c5 + x * (c6 + x * c7))))));
        return p * sqrtf(1.0f - x);
    }
    const float p = c0t - x * (c1 - x * (c2 - x * (c3 - x * (c4 - x * (c5 - x * (c6 - x * c7))))));
    return 3.14159265f - p * sqrtf(1.0f + x);
}
// local2uv: ISPC (dw_acos) at shading points, C++ (acos) for camera rays.
X2_HD inline void local2uv(V3 dir, bool ispc, float& u, float& v) {
    const float z = fminf(fmaxf(dir.z, -1.0f), 1.0f);
    const float theta = ispc ? dwAcos(z) : acosf(z);
    const float phi = atan2f(dir.y, dir.x);
    u = phi * 0.15915494309189533577f;
    v = 1.0f - theta * 0.31830988618379067154f;
    if (v < 0.0005f || v > 0.9995f) u = 0.0f;
    else if (u < 0.0f) u += 1.0f;
    u = 1.0f - u;
}
X2_HD inline V3 uv2local(float u, float v) {
    const float phi = (1.0f - u) * 6.28318530717958647692f, theta = (1.0f - v) * 3.14159265358979323846f;
    float sinTheta, cosTheta, sinPhi, cosPhi;
    surface::sincosSample(theta, sinTheta, cosTheta);
    surface::sincosSample(phi, sinPhi, cosPhi);
    return {sinTheta * cosPhi, sinTheta * sinPhi, cosTheta};
}

}  // namespace xpu2::interactive::lights
