// Private XPU2 shading library, shared CPU/CUDA: DwaBase's glitter as MoonRay XPU's vector path shades it
// (moonshine lib/material/glitter Glitter.ispc), the Worley flake search it uses (lib/common/noise Worley.ispc
// NOISE_worleySearchPoints over glitter's static tables) and its reads of ref_P and ref_N (lib/map/primvar
// Primvar.ispc, shading/ispc/ShaderDataAux.ispc). Derived from MoonRay Apache-2.0, Copyright 2023-2024 DreamWorks
// Animation LLC. See MOONRAY_LICENSE.txt.
//
// The flakes found in a footprint are kept as their ids only, in the shading thread's glitter scratch: the first
// four by id are the macro flakes (their coverage kept aside as they are found), the rest the micro flakes a
// stochastic flakes lobe reads back through its Bsdf's flake set (shade_flakes.h). Flake textures are refused at
// admission.
#pragma once
#include "shade_builder.h"
#include "shade_flakes.h"
#include "shade_glitter_tables.h"
namespace xpu2 { namespace interactive { namespace shade {

constexpr U32 GlitterNone = 0xffffffffu;  // no glitter tables (mGlitterPointerVector null)
constexpr U32 GlitterMaxPoints = 1500;    // NOISE_WORLEY_MAX_SEARCH_POINTS
enum GlitterSpace : U32 { GlitterObjectSpace = 4, GlitterReferenceSpace = 5 };
enum GlitterDebugMode : U32 {
    GlitterDebugOff = 0,
    GlitterDebugBlend,
    GlitterDebugColor,
    GlitterDebugAverageColor,
    GlitterDebugFootprintArea,
    GlitterDebugRadius
};
enum GlitterLayeringMode : U32 { GlitterLayeringPhysical = 0, GlitterLayeringAdditive = 1 };

// The shading thread's glitter scratch: the found flakes' ids, sorted once found.
struct GlitterScratch {
    unsigned short ids[GlitterMaxPoints];
};

// What DwaBaseParameters carries of glitter: the Glitter object's uniform parameters (its tables in the pool) and
// GLITTER_VaryingParameters (the mask is DwaParams::glitterMask).
struct GlitterParameters {
    U32 tables = GlitterNone;
    int noiseSeed = 0;  // Noise::mSeed: the seed modulo the table size
    U32 space = GlitterReferenceSpace, layeringMode = GlitterLayeringPhysical, debugMode = GlitterDebugOff;
    float flakeRandomness = 0.0f;  // 0.6 * saturate(glitter_randomness)
    int blendStart = 100, blendEnd = 400;
    Color flakeColor[2];
    float flakeRoughness[2], styleFrequency[2], flakeSize[2];
    V3 hsvVariation;
    float density, jitter, orientationRandomness;
    U32 compensateDeformation, approximateForSecRays;
};
// DWABASELAYERABLE_initGlitterVaryingParameters
X2_HD inline void initGlitterParameters(GlitterParameters& g) {
    g = GlitterParameters{};
    g.styleFrequency[0] = 1.0f;
    g.flakeColor[0] = rgb(1);
    g.flakeSize[0] = 1.0f;
    g.flakeRoughness[0] = 0.14f;
    g.styleFrequency[1] = 0.0f;
    g.flakeColor[1] = rgb(1);
    g.flakeSize[1] = 1.0f;
    g.flakeRoughness[1] = 0.14f;
    g.hsvVariation = V3{0, 0, 0};
    g.density = 1.0f;
    g.jitter = 1.0f;
    g.orientationRandomness = 0.15f;
    g.compensateDeformation = 1;
    g.approximateForSecRays = 1;
}

// NOISE_WorleySample
struct GlitterSample {
    V3 position, normal;
    bool compensate = false;
    float compensationS = 1, compensationT = 1, shear = 0;
    V3 refX{0, 0, 0}, refY{0, 0, 0}, refZ{0, 0, 0};
    float footprintLength = 0, footprintArea = 0, radius = 0, searchRadius = 0, microfacetBlend = 0;
    U32 estimatedFeatures = 0;
};

// transformNormal from render to object space: through the inverse transpose of world to object (the cofactors
// over the determinant).
X2_HD inline V3 glitterObjectNormal(const float* m, V3 n) {
    if (!m) return n;
    const float a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], i = m[10];
    const float c00 = e * i - f * h, c01 = f * g - d * i, c02 = d * h - e * g;
    const float c10 = c * h - b * i, c11 = a * i - c * g, c12 = b * g - a * h;
    const float c20 = b * f - c * e, c21 = c * d - a * f, c22 = a * e - b * d;
    const float inv = 1.0f / (a * c00 + b * c01 + c * c02);
    return V3{(c00 * n.x + c01 * n.y + c02 * n.z) * inv, (c10 * n.x + c11 * n.y + c12 * n.z) * inv,
              (c20 * n.x + c21 * n.y + c22 * n.z) * inv};
}
X2_HD inline V3 v3(const float v[3]) { return V3{v[0], v[1], v[2]}; }

// calculateDeformationFactors: in reference space, how the surface is stretched and sheared from its reference.
X2_HD inline bool glitterDeformation(const State& st, const GlitterParameters& g, U32 refPKey, GlitterSample& s) {
    if (!g.compensateDeformation || g.space != GlitterReferenceSpace) return false;
    const V3 curdPds = st.dPds, curdPdt = st.dPdt;
    V3 curZ = cross(curdPds, curdPdt);
    const float lengthCurZ = length(curZ);
    if (isZero(lengthCurZ)) return false;
    curZ = curZ / lengthCurZ;
    const V3 curX = normalize(curdPds), curY = normalize(cross(curZ, curX));
    float ds[3] = {0, 0, 0}, dt[3] = {0, 0, 0};
    primPartials(st, refPKey, ds, dt);
    const V3 refdPds = v3(ds), refdPdt = v3(dt);
    V3 refZ = cross(refdPds, refdPdt);
    const float lengthRefZ = length(refZ);
    if (isZero(lengthRefZ)) return false;  // GLITTER_RESULTCODE_NO_REFP_PARTIALS (a warning)
    refZ = refZ / lengthRefZ;
    const V3 refX = normalize(refdPds), refY = normalize(cross(refZ, refX));
    s.compensationS = fabsf(dot(curdPds, curX) / dot(refdPds, refX));
    s.compensationT = fabsf(dot(curdPdt, curY) / dot(refdPdt, refY));
    s.shear = dot(normalize(refdPdt), refX) - dot(normalize(curdPdt), curX);
    s.refX = refX;
    s.refY = refY;
    s.refZ = refZ;
    return true;
}
// initializeNoiseSample: the shading point in the glitter's space (object space, or ref_P and its normal), scaled by
// the flake density, and the texture footprint's area there.
X2_HD inline bool glitterNoiseSample(const State& st, const GlitterParameters& g, GlitterSample& s) {
    const U32 refPKey = primKey("ref_P", PrimVec3f), refNKey = primKey("ref_N", PrimVec3f);
    V3 pos, normal, dPds{0, 0, 0}, dPdt{0, 0, 0};
    if (g.space == GlitterReferenceSpace) {
        float v[3];
        if (!primValue(st, refPKey, v)) return false;  // GLITTER_RESULTCODE_NO_REFP
        pos = v3(v);
        float ds[3] = {0, 0, 0}, dt[3] = {0, 0, 0};
        const bool partials = primPartials(st, refPKey, ds, dt);
        // SHADER_DATA_getRefN: ref_N, else the normal of ref_P's partials (Wo across a curve).
        V3 n;
        if (primValue(st, refNKey, v)) {
            n = v3(v);
        } else {
            V3 a = v3(ds), b = v3(dt);
            if (isZero(lengthSqr(a))) return false;  // GLITTER_RESULTCODE_NO_REFN
            a = normalize(a);
            if (isZero(lengthSqr(b))) {
                b = st.wo;
                b = cross(a, cross(a, normalize(b)));
            }
            n = cross(a, normalize(b));
            if (isZero(lengthSqr(n))) return false;
        }
        if (!st.entering) n = -n;  // SHADER_DATA_getRefN flips an exiting surface's reference normal...
        if (!st.entering) n = -n;  // ...and PRIMVAR_getNormal flips it back
        normal = normalize(n);
        if (partials) {
            dPds = v3(ds);
            dPdt = v3(dt);
        }
    } else {
        pos = st.worldToObject ? xformPoint(st.worldToObject, st.P) : st.P;
        normal = normalize(glitterObjectNormal(st.worldToObject, st.N));
        dPds = st.worldToObject ? xformVector(st.worldToObject, st.dPds) : st.dPds;
        dPdt = st.worldToObject ? xformVector(st.worldToObject, st.dPdt) : st.dPdt;
    }
    s.normal = normalize(normal);
    dPds = dPds * g.density;
    dPdt = dPdt * g.density;
    const V3 dPdxScaled = dPds * st.dsdx + dPdt * st.dtdx, dPdyScaled = dPds * st.dsdy + dPdt * st.dtdy;
    s.position = pos * g.density;
    s.footprintArea = length(cross(dPdxScaled, dPdyScaled));
    s.radius = sqrtf(s.footprintArea * OneOverPi);
    s.footprintLength = 2.0f * s.radius;
    s.estimatedFeatures = U32(int(3.0f * s.footprintArea + 1));  // NOISE_WORLEY_LAMBDA
    s.searchRadius = s.radius * 0.25f;                          // mSearchRadiusFactor
    s.microfacetBlend = saturate(float(int(s.estimatedFeatures) - g.blendStart) / float(g.blendEnd - g.blendStart));
    s.compensate = glitterDeformation(st, g, refPKey, s);
    return true;
}

// Worley's point count of a cell (getPointCount): its Poisson count from a feature point's coordinate.
X2_HD inline int glitterPointCount(const float* t, int hash) {
    int low = 1, high = 9, m = 1;
    const float prob = t[GlitterPointsX + glitterPerm(t, hash + 5)];
    while (low <= high) {
        m = (low + high) / 2;
        if (prob < t[GlitterProbLow + m]) high = m - 1;
        else if (prob >= t[GlitterProbHigh + m]) low = m + 1;
        else break;
    }
    return m;
}
// NOISE_Worley_computeSphereDiskOverlap (NOISE_WORLEY_V2): the share of the footprint's disk the flake's sphere
// covers where it cuts the surface's plane.
X2_HD inline float glitterOverlap(V3 featurePt, float radius, const GlitterSample& s) {
    const V3 diff = s.position - featurePt;
    const float deltaToPlane = dot(diff, s.normal);
    const float radiusP2 = radius * radius - deltaToPlane * deltaToPlane;
    if (radiusP2 < Epsilon) return 0.0f;
    float radiusProjection = sqrtf(radiusP2);
    const V3 centerProjection = featurePt + deltaToPlane * s.normal;
    V3 diskDiff = s.position - centerProjection;
    if (s.compensate) {
        radiusProjection *= fminf(1.0f, fminf(s.compensationS, s.compensationT));
        diskDiff.x = diskDiff.x - s.shear * diskDiff.y;
        diskDiff = dot(diskDiff, s.refX) * s.compensationS * s.refX + dot(diskDiff, s.refY) * s.compensationT * s.refY +
                   dot(diskDiff, s.refZ) * s.refZ;
    }
    const float distToPlane = length(diskDiff);
    float overlapRadius = radiusProjection + s.radius - distToPlane;
    overlapRadius = fminf(fmaxf(overlapRadius, 0.0f), 2.0f * fminf(radiusProjection, s.radius));
    if (!isNormalized(s.normal)) return 0.0f;
    const float overlapArea = overlapRadius * overlapRadius * Pi;
    return overlapArea > s.footprintArea ? 1.0f : overlapArea / s.footprintArea;
}

// A macro flake: its id, coverage and style.
struct GlitterMacro {
    int id;
    float weight;
    U32 style;
};
struct GlitterFound {
    U32 count = 0;
    GlitterMacro macro[4];
    U32 macroCount = 0;
};
// NOISE_worleySearchPoints and finalizeFlakes: the flakes whose spheres overlap the footprint, cell by cell outward
// (a level's points at most 1,500, all of them at most 1,500), their ids sorted. The four least ids (the earliest
// found first among equal ids) are kept aside with their coverage and style.
X2_CALL void glitterSearch(const float* t, int seed, const float radii[2], const float cdf[2], const GlitterSample& s, float jitter,
                           unsigned short* ids, GlitterFound& found) {
    const V3 pos = s.position;
    const float radius = fmaxf(radii[0], radii[1]) + s.searchRadius;
    U32 level = 0;
    auto cell = [&](int ix, int iy, int iz) {
        if (found.count == GlitterMaxPoints) return;
        int hash = glitterPerm(t, ix + glitterPerm(t, iy + glitterPerm(t, iz)));
        hash = (hash + seed) % int(GlitterTableSize);  // static tables: the seed offsets the hash
        const int count = glitterPointCount(t, hash);
        for (int i = 0; i < count; i++) {
            const V3 position{float(ix) + 0.5f + (t[GlitterPointsX + hash] - 0.5f) * jitter,
                              float(iy) + 0.5f + (t[GlitterPointsY + hash] - 0.5f) * jitter,
                              float(iz) + 0.5f + (t[GlitterPointsZ + hash] - 0.5f) * jitter};
            // NOISE_Worley_setFlakeStyleAndSize
            const float r1 = t[GlitterRandom + ((7 * hash) & (int(GlitterRandomSize) - 1))];
            U32 style = 0;
            float size = 0.0f;
            if (r1 <= cdf[0]) {
                style = 0;
                size = radii[0];
            } else if (r1 <= cdf[1]) {
                style = 1;
                size = radii[1];
            }
            const float overlap = glitterOverlap(position, size, s);
            if (overlap > Epsilon) {
                if (level == GlitterMaxPoints) break;  // the level's array is full: the cell's other points are lost
                ++level;
                if (overlap > 0.00001f && found.count < GlitterMaxPoints) {  // collectPoints
                    ids[found.count++] = (unsigned short)hash;
                    if (found.macroCount < 4 || hash < found.macro[3].id) {
                        U32 k = found.macroCount < 4 ? found.macroCount++ : 3u;
                        while (k > 0 && found.macro[k - 1].id > hash) {
                            found.macro[k] = found.macro[k - 1];
                            --k;
                        }
                        found.macro[k] = GlitterMacro{hash, overlap, style};
                    }
                }
            }
            hash = (hash + 1) & int(GlitterTableSize - 1);
        }
    };
    const int ixMin = int(floorf(pos.x - radius)), iyMin = int(floorf(pos.y - radius)), izMin = int(floorf(pos.z - radius));
    const int ixMax = int(floorf(pos.x + radius)), iyMax = int(floorf(pos.y + radius)), izMax = int(floorf(pos.z + radius));
    if (ixMin == ixMax && iyMin == iyMax && izMin == izMax) {
        cell(ixMin, iyMin, izMin);
    } else {
        const int cx = int(floorf(pos.x)), cy = int(floorf(pos.y)), cz = int(floorf(pos.z));
        const int maxRadius = int(floorf(radius)) + 1;
        const float reach = 0.86603f + radius;
        cell(cx, cy, cz);
        for (int k = 1; k <= maxRadius; k++) {
            const int kp = k - 1;
            for (int ix = cx - k; ix <= cx + k; ++ix)
                for (int iy = cy - k; iy <= cy + k; ++iy)
                    for (int iz = cz - k; iz <= cz + k; ++iz) {
                        if (ix >= cx - kp && ix <= cx + kp && iy >= cy - kp && iy <= cy + kp && iz >= cz - kp && iz <= cz + kp)
                            continue;  // alreadyVisited
                        const V3 cornerCenter = pos - V3{float(ix) + 0.5f, float(iy) + 0.5f, float(iz) + 0.5f};
                        if (dot(cornerCenter, cornerCenter) < reach * reach) cell(ix, iy, iz);
                    }
            level = 0;
            if (found.count == GlitterMaxPoints) break;
        }
    }
    // finalizeFlakes: by id (a heap sort)
    const int n = int(found.count);
    auto sift = [&](int root, int end) {
        while (2 * root + 1 < end) {
            int child = 2 * root + 1;
            if (child + 1 < end && ids[child] < ids[child + 1]) ++child;
            if (!(ids[root] < ids[child])) return;
            const unsigned short x = ids[root];
            ids[root] = ids[child];
            ids[child] = x;
            root = child;
        }
    };
    for (int i = n / 2 - 1; i >= 0; --i) sift(i, n);
    for (int end = n - 1; end > 0; --end) {
        const unsigned short x = ids[0];
        ids[0] = ids[end];
        ids[end] = x;
        sift(0, end);
    }
}

// computeCoverageFactor: the average share of a footprint the flakes cover, fitted over the flake size.
X2_HD inline float glitterCoverageFactor(float flakeSize) {
    flakeSize = fminf(flakeSize, 1.1277f);
    float res = 0.0f;
    const float flakeSizeSq = flakeSize * flakeSize;
    if (flakeSize < 0.4f) res = (-0.0382308f * flakeSize) + (1.230008f * flakeSizeSq);
    else res = 0.030076f - (0.6612578f * flakeSize) + (3.313868f * flakeSizeSq) - (1.7856762f * flakeSize * flakeSizeSq);
    return saturate(res);
}
X2_HD inline float glitterHueTable(const float (&table)[16][100], int hue, int var) {
    hue = hue < 0 ? 0 : (hue > 15 ? 15 : hue);
    var = var < 0 ? 0 : (var > 99 ? 99 : var);
    return table[hue][var];
}
// computeAverageFlakeColor: with a hue variation, the average flake colour from the tables (coverage included).
X2_HD inline Color glitterAverageFlakeColor(Color baseColor, V3 hsvVariation, float coverageFactor) {
    if (isZero3(hsvVariation)) return baseColor;
    const Color hsv = rgbToHsv(baseColor);
    const float hueVar = hsvVariation.x, origHue = hsv.x, origSat = hsv.y, origVal = hsv.z;
    float origHueT = fmodf(origHue, 0.3333f) / 0.3333f;
    origHueT = 2.0f * ((origHueT > 0.5f) ? 1.0f - origHueT : origHueT);
    const float hueIndexFloat = origHueT * 15.0f;
    const int hueIndexLo = int(hueIndexFloat), hueIndexHi = int(fminf(15.0f, floorf(hueIndexFloat) + 1.0f));
    const float hueVarIndexFloat = hueVar * 99.0f;
    const int hueVarIndexLo = int(hueVarIndexFloat), hueVarIndexHi = int(fminf(99.0f, floorf(hueVarIndexFloat) + 1.0f));
    const float hueT = hueIndexFloat - float(hueIndexLo), varT = hueVarIndexFloat - float(hueVarIndexLo);
    const auto& S = GlitterHueVariationSaturation;
    const auto& V = GlitterHueVariationValue;
    const float s0 = glitterHueTable(S, hueIndexLo, hueVarIndexLo), s1 = glitterHueTable(S, hueIndexLo, hueVarIndexHi);
    const float s2 = glitterHueTable(S, hueIndexHi, hueVarIndexLo), s3 = glitterHueTable(S, hueIndexHi, hueVarIndexHi);
    const float avgSat = origSat * lerpf(lerpf(s0, s1, varT), lerpf(s2, s3, varT), hueT);
    const float v0 = glitterHueTable(V, hueIndexLo, hueVarIndexLo), v1 = glitterHueTable(V, hueIndexLo, hueVarIndexHi);
    const float v2 = glitterHueTable(V, hueIndexHi, hueVarIndexLo), v3v = glitterHueTable(V, hueIndexHi, hueVarIndexHi);
    float avgVal = origVal * lerpf(lerpf(v0, v1, varT), lerpf(v2, v3v, varT), hueT);
    avgVal = lerpf(origVal * coverageFactor, avgVal, origSat);
    return hsvToRgb(Color{origHue, avgSat, avgVal});
}
// INTERPOLATION_lerpHSV (its value channel keeps A's, as MoonRay's does).
X2_HD inline Color glitterLerpHSV(float t, Color a, Color b) {
    if (t <= 0) return a;
    if (t >= 1) return b;
    float hue, aHue = a.x, bHue = b.x;
    float dist = bHue - aHue;
    if (aHue > bHue) {
        bHue = a.x;
        aHue = b.x;
        dist *= -1.f;
        t = 1.f - t;
    }
    if (dist > 0.5f) {
        aHue = aHue + 1.f;
        hue = fmodf(aHue + t * (bHue - aHue), 1.f);
    } else {
        hue = aHue + t * dist;
    }
    return Color{hue, a.y + t * (b.y - a.y), a.z + t * (b.z - b.z)};
}
// computeAverageBaseColor: two styles' colours lerped in HSV by their size-weighted frequencies.
X2_HD inline Color glitterAverageBaseColor(const GlitterParameters& g) {
    if (isZero(g.styleFrequency[0])) return g.flakeColor[1];
    if (isZero(g.styleFrequency[1])) return g.flakeColor[0];
    const float size1Sqr = g.flakeSize[0] * g.flakeSize[0], size2Sqr = g.flakeSize[1] * g.flakeSize[1];
    const float size1Ratio = size1Sqr / (size1Sqr + size2Sqr), size2Ratio = size2Sqr / (size1Sqr + size2Sqr);
    const float flake1Proportion = size1Ratio * g.styleFrequency[0], flake2Proportion = size2Ratio * g.styleFrequency[1];
    const float t = flake2Proportion / (flake1Proportion + flake2Proportion);
    return hsvToRgb(glitterLerpHSV(t, rgbToHsv(g.flakeColor[0]), rgbToHsv(g.flakeColor[1])));
}
// computeStyleCDF
X2_HD inline void glitterStyleCDF(const GlitterParameters& g, float cdf[2]) {
    float styleWeight = 0.0f;
    for (int i = 0; i < 2; i++) {
        cdf[i] = g.styleFrequency[i] + styleWeight;
        styleWeight += g.styleFrequency[i];
    }
    if (styleWeight > 1.0f)
        for (int i = 0; i < 2; i++) cdf[i] /= styleWeight;
}
X2_HD inline float glitterFlakeSize(const GlitterParameters& g) {
    return (g.flakeSize[0] * g.styleFrequency[0] + g.flakeSize[1] * g.styleFrequency[1]) * g.density;
}
X2_HD inline bool glitterHifi(const State& st) { return st.pathType == PathPrimary || st.pathType == PathIndirectMirror; }
// BsdfBuilder_addStochasticFlakesBRDF
X2_CALL void addStochasticFlakesBRDF(Builder& me, V3 N, U32 flakeCount, float roughness, float randomness, float weight, U32 behavior,
                                     U32 label) {
    if (!visible(me, weight, behavior) || lobeLimit(me)) return;
    U32 lobe = stochasticFlakesLobe(me.bsdf, N, flakeCount, roughness, randomness);
    lobe = scaleOrPlace(me, lobe, weight, behavior);
    if (isOverB(behavior)) me.weightAccum += weight;
    finishLobe(me, lobe, label);
    accumulateAttenuation(me);
}
X2_HD inline void addGlitterGGX(Builder& bb, V3 N, Color color, float randomness, float weight, U32 behavior, U32 label) {
    addMicrofacetIsotropicBRDF(bb, microfacetConductor(N, color, color, randomness, GGXDistribution), weight, behavior, label);
}

// The flakes about the shading point: none when the search finds none.
struct GlitterFlakes {
    GlitterFound found;
    Color baseColors[4];
    float roughness[4];
    float macroVis = 0.0f;
};
X2_HD inline bool glitterGather(const GlitterParameters& g, const float* t, const GlitterSample& s, unsigned short* ids, GlitterFlakes& f) {
    float cdf[2];
    glitterStyleCDF(g, cdf);
    const float radii[2] = {g.flakeSize[0] * 0.5f * g.density, g.flakeSize[1] * 0.5f * g.density};  // findNearestFlakes
    glitterSearch(t, g.noiseSeed, radii, cdf, s, g.jitter, ids, f.found);
    if (f.found.count == 0) return false;
    // setFlakeStyles
    for (U32 i = 0; i < f.found.macroCount; ++i) {
        f.baseColors[i] = g.flakeColor[f.found.macro[i].style];
        f.roughness[i] = g.flakeRoughness[f.found.macro[i].style];
        f.macroVis += f.found.macro[i].weight;
    }
    return true;
}

// GLITTER_createDebug*Lobes: emission showing the level-of-detail blend, the flake colours, the average colour or
// the footprint.
X2_CALL void glitterDebugLobes(Builder& bb, const State& st, const GlitterParameters& g, const float* t, GlitterScratch* scratch) {
    GlitterSample s;
    const float coverageFactor = glitterCoverageFactor(glitterFlakeSize(g));
    if (g.debugMode == GlitterDebugAverageColor) {
        addEmission(bb, glitterAverageFlakeColor(glitterAverageBaseColor(g), g.hsvVariation, coverageFactor));
        return;
    }
    if (g.debugMode == GlitterDebugBlend && !glitterHifi(st)) {
        addEmission(bb, Color{0, 0, 1});
        return;
    }
    if (!glitterNoiseSample(st, g, s)) return;
    if (g.debugMode == GlitterDebugFootprintArea || g.debugMode > GlitterDebugRadius) {
        if (g.debugMode == GlitterDebugFootprintArea) addEmission(bb, rgb(s.footprintArea));
        return;
    }
    if (g.debugMode == GlitterDebugRadius) {
        addEmission(bb, rgb(s.radius));
        return;
    }
    if (isOne(s.microfacetBlend)) {
        if (g.debugMode == GlitterDebugBlend) addEmission(bb, Color{0, 0, 1});
        else addEmission(bb, glitterAverageFlakeColor(glitterAverageBaseColor(g), g.hsvVariation, coverageFactor));
        return;
    }
    GlitterFlakes f;
    if (!glitterGather(g, t, s, scratch->ids, f)) return;
    const U32 flakeCount = f.found.count, macroCount = f.found.macroCount, microCount = flakeCount - macroCount;
    if (g.debugMode == GlitterDebugBlend) {
        float macroVis = f.macroVis;
        if (!(macroVis > 0.1f)) macroVis = 0.0f;
        const float microFlakeVis = microCount > 0 ? (1.0f - s.microfacetBlend) * (1.0f - macroVis) : 0.f;
        const float microFacetVis = microCount > 0 ? s.microfacetBlend * (1.0f - macroVis) : 0.f;
        addEmission(bb, Color{saturate(macroVis), saturate(microFlakeVis), saturate(microFacetVis)});
        return;
    }
    // GLITTER_DEBUG_MODE_COLOR
    const float macroVis = f.macroVis;
    U32 first = 0;
    while (first != macroCount && !(f.found.macro[first].weight >= OneMinusEpsilon)) ++first;
    Color current = rgb(0), emission = rgb(0), macroAvg = rgb(0);
    float flakeWeight = 1.0f;
    if (macroCount == 1) {
        current = glitterFlakeColor(t, f.found.macro[0].id, f.baseColors[0], g.hsvVariation);
        flakeWeight = f.found.macro[0].weight;
    } else if (first < macroCount) {
        current = glitterFlakeColor(t, f.found.macro[first].id, f.baseColors[first], g.hsvVariation);
        flakeWeight = f.found.macro[first].weight;
    }
    if (!isBlack(current)) {
        addEmission(bb, current * flakeWeight);
        return;
    }
    const float oneOverMacroVis = 1.0f / macroVis;
    for (U32 i = 0; i < macroCount; ++i) {
        current = glitterFlakeColor(t, f.found.macro[i].id, f.baseColors[i], g.hsvVariation);
        float scale = f.found.macro[i].weight;
        scale *= flakeCount > macroCount ? coverageFactor : 1.0f;
        if (macroVis >= OneMinusEpsilon) scale *= oneOverMacroVis;
        if (!isBlack(current)) {
            emission = emission + current * scale;
            macroAvg = macroAvg + current;
        }
    }
    auto clamp01 = [](Color c) { return Color{saturate(c.x), saturate(c.y), saturate(c.z)}; };
    if (macroVis < 1.0f && microCount == 0) {
        addEmission(bb, clamp01(emission));
        return;
    }
    const float microFlakeVis = saturate((1.0f - s.microfacetBlend) * (1.0f - macroVis));
    const float microFacetVis = saturate(s.microfacetBlend * (1.0f - macroVis));
    if (macroVis >= 0.9f && microCount > 0) {
        macroAvg = macroAvg * (1.0f / float(macroCount));
        if (macroVis < 0.99f && !isBlack(macroAvg)) emission = emission + macroAvg * (1.0f - macroVis) * coverageFactor;
    } else {
        Color microAvg = rgb(0);
        if (microFlakeVis > 0.0f) {
            for (U32 i = 0; i < microCount; ++i) {
                const U32 flakeIndex = i + macroCount;
                microAvg = microAvg + glitterFlakeColor(t, scratch->ids[flakeIndex], f.baseColors[flakeIndex % macroCount], g.hsvVariation);
            }
            microAvg = microAvg * (1.0f / float(microCount));
            emission = emission + microAvg * microFlakeVis * coverageFactor;
        }
        if (microFacetVis > 0.0f && !isBlack(microAvg)) emission = emission + microAvg * microFacetVis * coverageFactor;
    }
    addEmission(bb, clamp01(emission));
}

// createLobes: up to four macro flakes as glitter GGX lobes weighted by their coverage; the rest of the footprint's
// flakes as one stochastic flakes lobe blended toward a GGX lobe of their average colour as they grow dense; far
// away (or on secondary rays) that GGX lobe alone. All adjacent: glitter manages its own energy.
X2_CALL bool createGlitterLobes(Builder& bb, const State& st, const GlitterParameters& g, float glitterMask, const float* pool,
                                GlitterScratch* scratch, U32 label) {
    if (isZero(glitterMask)) return true;
    if (g.tables == GlitterNone) return true;  // no Glitter object: no glitter lobes
    if (!scratch) return false;
    const float* t = pool + g.tables;
    if (g.debugMode != GlitterDebugOff) {
        glitterDebugLobes(bb, st, g, t, scratch);
        return true;
    }
    startAdjacentComponents(bb);
    GlitterSample s;
    if (glitterNoiseSample(st, g, s)) {
        const Frame refFrame = frame(adaptNormal(st, st.N));
        const V3 N = refFrame.z;
        const float coverageFactor = glitterCoverageFactor(glitterFlakeSize(g));
        const bool hifi = glitterHifi(st);
        if ((!hifi && g.approximateForSecRays) || isOne(s.microfacetBlend)) {
            const Color avg = glitterAverageFlakeColor(glitterAverageBaseColor(g), g.hsvVariation, coverageFactor);
            addGlitterGGX(bb, N, avg, g.flakeRandomness, coverageFactor * glitterMask, Physical, label);
        } else {
            const U32 behavior = hifi && g.layeringMode == GlitterLayeringAdditive ? Additive : Physical;
            GlitterFlakes f;
            if (glitterGather(g, t, s, scratch->ids, f)) {
                const U32 flakeCount = f.found.count, macroCount = f.found.macroCount;
                const float macroVis = f.macroVis;
                Color macroAvg = rgb(0);
                bool single = false;
                // createMacroFlakes
                if (macroVis > 0.1f) {
                    U32 first = 0;
                    while (first != macroCount && !(f.found.macro[first].weight >= OneMinusEpsilon)) ++first;
                    single = true;
                    Color current = rgb(0);
                    V3 normal{0, 0, 1};
                    float roughness = 0.0f, flakeWeight = 1.0f;
                    const U32 pick = macroCount == 1 ? 0u : first;
                    if (pick < macroCount) {
                        const GlitterMacro& m = f.found.macro[pick];
                        current = glitterFlakeColor(t, m.id, f.baseColors[pick], g.hsvVariation);  // flake texture: white
                        normal = localToGlobal(refFrame, glitterFlakeNormal(t, m.id));
                        roughness = f.roughness[pick];
                        flakeWeight = m.weight;
                    }
                    if (!isBlack(current)) {
                        addGlitterFlakeBRDF(bb, glitterFlake(N, normal, current, current, roughness), glitterMask * flakeWeight, behavior, label);
                    } else {
                        single = false;
                        const float oneOverMacroVis = 1.0f / macroVis;
                        for (U32 i = 0; i < macroCount; ++i) {
                            const GlitterMacro& m = f.found.macro[i];
                            const V3 n = localToGlobal(refFrame, glitterFlakeNormal(t, m.id));
                            const Color color = glitterFlakeColor(t, m.id, f.baseColors[i], g.hsvVariation);
                            float scale = m.weight;
                            scale *= flakeCount > macroCount ? coverageFactor : 1.0f;
                            if (macroVis >= OneMinusEpsilon) scale *= oneOverMacroVis;
                            if (!isBlack(color)) {
                                addGlitterFlakeBRDF(bb, glitterFlake(N, n, color, color, f.roughness[i]), scale * glitterMask, behavior, label);
                                macroAvg = macroAvg + color;
                            }
                        }
                    }
                }
                const U32 microCount = flakeCount - macroCount;
                if (!single && !(macroVis >= OneMinusEpsilon) && !(macroVis < 1.0f && microCount == 0)) {
                    const float microFlakeVis = saturate((1.0f - s.microfacetBlend) * (1.0f - macroVis));
                    const float microFacetVis = saturate(s.microfacetBlend * (1.0f - macroVis));
                    if (macroVis >= 0.9f) {
                        if (microCount > 0) {
                            macroAvg = macroAvg * (1.0f / float(macroCount));
                            if (macroVis < 0.99f && !isBlack(macroAvg))
                                addGlitterGGX(bb, N, macroAvg, g.flakeRandomness, (1.0f - macroVis) * coverageFactor * glitterMask, behavior, label);
                        }
                    } else {
                        // createMicroFlake
                        Color avg = rgb(0);
                        if (microFlakeVis > 0.0f) {
                            GlitterFlakeSet& set = bb.bsdf.flakeSet;
                            set.ids = scratch->ids + macroCount;
                            set.tables = t;
                            set.refFrame = refFrame;
                            for (U32 i = 0; i < 4; ++i) set.baseColors[i] = i < macroCount ? f.baseColors[i] : rgb(0);
                            set.hsvVariation = g.hsvVariation;
                            set.offset = macroCount;
                            set.macroCount = macroCount;
                            for (U32 i = 0; i < microCount; ++i) avg = avg + flakeSetColor(set, i);
                            addStochasticFlakesBRDF(bb, N, microCount, g.flakeRoughness[0], g.flakeRandomness,
                                                    microFlakeVis * coverageFactor * glitterMask, behavior, label);
                        }
                        avg = avg * (1.0f / float(microCount));
                        if (microFacetVis > 0.0f && !isBlack(avg))
                            addGlitterGGX(bb, N, avg, g.flakeRandomness, microFacetVis * coverageFactor * glitterMask, behavior, label);
                    }
                }
            }
        }
    }
    endAdjacentComponents(bb);
    return true;
}
}}}
