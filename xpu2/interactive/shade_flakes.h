// Private XPU2 shading library, shared CPU/CUDA: glitter's flake tables and the stochastic flakes lobe
// (shading/ispc/bsdf/BsdfStochasticFlakes.ispc) over glitter's micro flakes. Derived from MoonRay Apache-2.0
// (BsdfStochasticFlakes.ispc, Util.isph; moonshine lib/material/glitter Glitter.ispc computeFlakeColor;
// lib/common/noise Worley.ispc checkCell), Copyright 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "shade_lobes.h"
#include "shade_colorcorrect.h"
#include "shade_fresnel.h"
namespace xpu2 { namespace interactive { namespace shade {

// A glitter's tables in the material pool, in floats from its offset: Worley's static permutation (int bits) and
// feature points (NOISE_WORLEY_GLITTER_FLAKES_SIZE each), the flake normals for its randomness, its colour random
// table (seeded with its seed + 100) and the Poisson point-count bounds.
constexpr U32 GlitterTableSize = 16384, GlitterRandomSize = 10000;
enum GlitterTable : U32 {
    GlitterPerm = 0,
    GlitterPointsX = GlitterTableSize,
    GlitterPointsY = 2 * GlitterTableSize,
    GlitterPointsZ = 3 * GlitterTableSize,
    GlitterNormalsX = 4 * GlitterTableSize,
    GlitterNormalsY = 5 * GlitterTableSize,
    GlitterNormalsZ = 6 * GlitterTableSize,
    GlitterRandom = 7 * GlitterTableSize,
    GlitterProbLow = 7 * GlitterTableSize + GlitterRandomSize,
    GlitterProbHigh = GlitterProbLow + 10,
    GlitterTablesFloats = GlitterProbHigh + 10
};
X2_HD inline int glitterPerm(const float* t, int i) { return reinterpret_cast<const int*>(t + GlitterPerm)[i & int(GlitterTableSize - 1)]; }
// checkCell's flake normal: the table's, plus its disk offset over dNdx and dNdy (zero for glitter), normalized.
X2_HD inline V3 glitterFlakeNormal(const float* t, int id) {
    return normalize(V3{t[GlitterNormalsX + id], t[GlitterNormalsY + id], t[GlitterNormalsZ + id]});
}
X2_HD inline bool isZero3(V3 v) { return isZero(v.x) && isZero(v.y) && isZero(v.z); }
// computeFlakeColor: the base colour varied in HSV by three entries of the random table from the flake's id.
X2_HD inline Color glitterFlakeColor(const float* t, int flakeID, Color baseColor, V3 colorVariation) {
    if (isZero3(colorVariation)) return baseColor;
    const int tabMask = int(GlitterRandomSize) - 1;
    const float* r = t + GlitterRandom;
    const float rx = r[(flakeID + 0) % tabMask] - 0.5f, ry = r[(flakeID + 1) % tabMask] * 2.0f - 1.0f,
                rz = r[(flakeID + 2) % tabMask] * 2.0f - 1.0f;
    const Color hsv = rgbToHsv(baseColor);
    // applyColorVariationInHsv
    float h = hsv.x + colorVariation.x * rx;
    h = h - floorf(h);
    const float s = saturate(hsv.y + colorVariation.y * ry), v = saturate(hsv.z + colorVariation.z * rz);
    return hsvToRgb(Color{h, s, v});
}
// The set's flake i: its normal in the reference frame and its colour.
X2_HD inline V3 flakeSetNormal(const GlitterFlakeSet& f, U32 i) { return localToGlobal(f.refFrame, glitterFlakeNormal(f.tables, f.ids[i])); }
X2_HD inline Color flakeSetColor(const GlitterFlakeSet& f, U32 i) {
    return glitterFlakeColor(f.tables, f.ids[i], f.baseColors[(i + f.offset) % f.macroCount], f.hsvVariation);
}

// Util.isph sampleLocalSphericalCapUniform
X2_HD inline V3 sampleLocalSphericalCapUniform(float r1, float r2, float cosThetaMax) {
    float cosTheta = 1.0f - r1 * (1.0f - cosThetaMax);
    cosTheta = cosTheta > 1.0f ? 1.0f : cosTheta;
    const float sinTheta = sqrtf(1.0f - cosTheta * cosTheta);
    return localSpherical(cosTheta, sinTheta, r2 * TwoPi);
}

namespace flakes {
// The reflection caches of wo and wi (computeReflectionCache) and both computeD sums, in one pass over the flakes
// in MoonRay's order: each flake's weight is its cosine to the direction, its reflection the direction's mirror.
struct Sums {
    float totalO = 0, totalI = 0, kO = 0, kI = 0;
    Color cO{0, 0, 0}, cI{0, 0, 0};
};
X2_HD inline void sums(const Bsdf& b, const Lobe& l, V3 wo, V3 wi, Sums& s) {
    const GlitterFlakeSet& f = b.flakeSet;
    for (U32 i = 0; i < l.flakes.count; ++i) {
        const V3 n = flakeSetNormal(f, i);
        const Color color = flakeSetColor(f, i);
        V3 ro, ri;
        const float wO = fmaxf(0.0f, computeReflectionDirection(n, wo, ro)), wI = fmaxf(0.0f, computeReflectionDirection(n, wi, ri));
        if (dot(wi, ro) >= l.flakes.cosGamma) {
            s.kO += wO;
            s.cO = s.cO + color * wO;
        }
        s.totalO += wO;
        if (dot(wo, ri) >= l.flakes.cosGamma) {
            s.kI += wI;
            s.cI = s.cI + color * wI;
        }
        s.totalI += wI;
    }
}
// StochasticFlakeBsdfLobe_computeGeometryTerm
X2_HD inline float geometryTerm(float cosNO, float cosNI, float randomness) {
    const float invCosNO = 1.0f / cosNO, invCosNI = 1.0f / cosNI;
    const float ao = 1.0f / (randomness * sqrtf((1.0f - cosNO * cosNO) * (invCosNO * invCosNO)));
    const float ai = 1.0f / (randomness * sqrtf((1.0f - cosNI * cosNI) * (invCosNI * invCosNI)));
    const float G1o = ao < 1.6f ? (3.535f * ao + 2.181f * ao * ao) / (1.0f + 2.276f * ao + 2.577f * ao * ao) : 1.0f;
    const float G1i = ai < 1.6f ? (3.535f * ai + 2.181f * ai * ai) / (1.0f + 2.276f * ai + 2.577f * ai * ai) : 1.0f;
    return G1o * G1i;
}
// StochasticFlakesBsdfLobe_computeBrdf: the discrete D averaged both ways (reciprocity), Cook-Torrance's G and the
// flakes' weighted colour as a conductor's Fresnel.
X2_HD inline Color brdf(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, const Sums& c, float& pdf) {
    pdf = 0.0f;
    V3 m;
    if (!computeNormalizedHalfVector(s.wo, wi, m)) return rgb(0);
    const float count = float(l.flakes.count);
    Color wc1 = c.cO, wc2 = c.cI;
    if (!isZero(c.kO)) wc1 = wc1 * (1.0f / c.kO);
    if (!isZero(c.kI)) wc2 = wc2 * (1.0f / c.kI);
    const float discreteD = 0.5f * (c.kO / count + c.kI / count);
    const V3 N = l.frame.z;
    const float cosNI = fminf(dot(N, wi), OneMinusEpsilon);
    if (cosNI <= Epsilon) return rgb(0);
    const float cosNO = fminf(dot(N, s.wo), OneMinusEpsilon);
    if (cosNO <= Epsilon) return rgb(0);
    const float cosMI = dot(m, wi);
    if (cosMI <= Epsilon) return rgb(0);
    const float solidAngleArea = TwoPi * (1.0f - l.flakes.cosGamma);
    const float D = discreteD / solidAngleArea;
    const Color F = scaleAndFresnel(b, l, cosMI);
    const float G = geometryTerm(cosNO, cosNI, l.flakes.randomness);
    const float invBrdfDenom = 1.0f / (cosNO * (s.includeCosine ? 1.0f : cosNI));
    const Color flakesBrdf = F * D * G * invBrdfDenom;
    pdf = c.kO / (solidAngleArea * c.totalO);
    const Color avg = cmin(rgb(0.999f), 0.5f * (wc1 + wc2));
    const Color eta = complexIorEta(avg, avg), k = complexIorK(avg, eta);
    return flakesBrdf * conductorEval(eta, k, 1.0f, cosMI);
}
X2_HD inline Color eval(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    Sums c;
    sums(b, l, s.wo, wi, c);
    if (!(c.totalO > 0.0f) || !(c.totalI > 0.0f)) {
        pdf = 0.0f;
        return rgb(0);
    }
    return brdf(b, l, s, wi, c, pdf);
}
// StochasticFlakesBsdfLobe_sample: a flake chosen by its wo weight (the CDF's upper bound), then a direction in the
// cone about its reflection.
X2_HD inline Color sample(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const GlitterFlakeSet& f = b.flakeSet;
    const U32 n = l.flakes.count;
    float total = 0.0f;
    for (U32 i = 0; i < n; ++i) {
        V3 r;
        total += fmaxf(0.0f, computeReflectionDirection(flakeSetNormal(f, i), s.wo, r));
    }
    if (!(total > 0.0f) || n == 0) {
        pdf = 0.0f;
        return rgb(0);
    }
    const float inv = 1.0f / total;
    float cdf = 0.0f, previous = 0.0f;
    U32 index = n;
    V3 reflection{0, 0, 1};
    for (U32 i = 0; i < n; ++i) {
        V3 r;
        const float w = fmaxf(0.0f, computeReflectionDirection(flakeSetNormal(f, i), s.wo, r));
        previous = cdf;
        cdf += w * inv;
        reflection = r;
        if (r1 < cdf) {
            index = i;
            break;
        }
    }
    if (index == n) index = n - 1;  // past the last bound: the last flake (previous and cdf are its bounds)
    const float remapped = index >= 1 ? (r1 - previous) / (cdf - previous) : r1 / cdf;
    const V3 wiLocal = sampleLocalSphericalCapUniform(remapped, r2, l.flakes.cosGamma);
    wi = localToGlobal(frame(reflection), wiLocal);
    Sums c;
    sums(b, l, s.wo, wi, c);
    if (!(c.totalI > 0.0f)) {
        pdf = 0.0f;
        return rgb(0);
    }
    return brdf(b, l, s, wi, c, pdf);
}
X2_HD inline void differentials(const Lobe& l, V3 wo, V3 wi, V3 dNdx, V3 dNdy, V3& dDdx, V3& dDdy) {
    V3 H;
    if (!computeNormalizedHalfVector(wo, wi, H)) H = l.frame.z;
    reflectionDifferential(wo, wi, H, dNdx, dNdy, dDdx, dDdy);
}
}  // namespace flakes
}}}
