// Private XPU2 shading library, shared CPU/CUDA: MoonRay's Fresnel closures
// (shading/ispc/bsdf/Fresnel.isph, Fresnel.ispc) and the complex IOR helpers
// (Ior.isph). Derived from MoonRay Apache-2.0, Copyright 2023-2024 DreamWorks
// Animation LLC. See MOONRAY_LICENSE.txt.
//
// A Fresnel lives in its Bsdf's pool and refers to the Fresnel it wraps (the
// one-minus kinds) by pool index, not pointer, so a Bsdf can be copied between
// a GPU thread's registers and memory as plain data.
#pragma once
#include "shade_math.h"
#include "shade_tables.h"
namespace xpu2 { namespace interactive { namespace shade {

enum FresnelKind : U32 {
    FresnelNone = 0,
    FresnelSchlick,
    FresnelOneMinusRoughSchlick,
    FresnelOneMinus,
    FresnelOneMinusRough,
    FresnelOneMinusVelvet,
    FresnelConductor,
    FresnelDielectric,
    FresnelLayeredDielectric,
    FresnelMultipleTransmission
};
constexpr U32 NoIndex = 0xffu, MaxMultipleFresnels = 8;
struct Fresnel {
    U32 kind = FresnelNone, top = NoIndex, count = 0, pad = 0;
    float weight = 1, etaI = 1, etaT = 1.5f;
    // Schlick: a spec, f0 factor, f1 neta. Conductor: a eta, b absorption.
    // One-minus-rough: a one minus Fresnel at 0, f0 roughness squared, f1 interpolator.
    // One-minus-velvet: f0 roughness. Layered dielectric: f0 layers.
    Color a{0, 0, 0}, b{0, 0, 0};
    float f0 = 0, f1 = 0;
    unsigned char list[MaxMultipleFresnels] = {};  // multiple transmission: the Fresnels it multiplies
};

// Ior.isph: complex IOR from an artist's reflectivity and edge colours.
X2_HD inline Color complexIorNMin(Color r) { return (rgb(1) - r) / (rgb(1) + r); }
X2_HD inline Color complexIorNMax(Color r) {
    const Color s = sqrt3(r);
    return (rgb(1) + s) / (rgb(1) - s);
}
X2_HD inline Color complexIorEta(Color r, Color g) { return g * complexIorNMin(r) + (rgb(1) - g) * complexIorNMax(r); }
X2_HD inline Color complexIorK(Color r, Color n) {
    const Color a = n + rgb(1), b = n - rgb(1);
    const Color nr = cmax(rgb(0), r * a * a - b * b);
    return sqrt3(nr / (rgb(1) - r));
}
X2_HD inline void complexIorFromColor(Color color, Color edge, Color& eta, Color& k) {
    const Color maxRefl = rgb(0.999f);
    const Color c = cmin(cmax(color, rgb(0)), maxRefl), e = cmin(cmax(edge, rgb(0)), maxRefl);
    eta = cmax(rgb(0), complexIorEta(c, e));
    k = complexIorK(c, eta);
}
// Fresnel.isph: average Fresnel reflectances (Kulla'17 fits).
X2_HD inline float averageFresnelReflectance(float neta) { return (neta - 1.0f) / (4.08567f + 1.00071f * neta); }
X2_HD inline float averageInvFresnelReflectance(float neta) {
    return 0.997118f + 0.1014f * neta - 0.965241f * neta * neta - 0.130607f * neta * neta * neta;
}
X2_HD inline Color averageFresnelReflectance(Color r, Color e) {
    const Color r2 = r * r, e2 = e * e;
    return rgb(0.087237f) + 0.0230685f * e - 0.0864902f * e2 + 0.0774594f * e2 * e + 0.782654f * r - 0.136432f * r2 +
           0.278708f * r2 * r + 0.19744f * e * r + 0.0360605f * e2 * r - 0.2586f * e * r2;
}
X2_HD inline void averageFresnelReflectance(float neta, float& favg, float& favgInv) {
    if (neta > 1.0f) {
        favg = averageFresnelReflectance(neta);
        favgInv = averageInvFresnelReflectance(1.0f / neta);
    } else if (neta < 1.0f) {
        favg = averageFresnelReflectance(1.0f / neta);
        favgInv = averageInvFresnelReflectance(neta);
    } else {
        favg = favgInv = 0.0f;
    }
}
X2_HD inline float diffuseFresnelReflectance(float eta) {
    if (eta >= 1.0f) return -1.4399f / (eta * eta) + 0.7099f / eta + 0.6681f + 0.0636f * eta;
    const float e2 = eta * eta;
    return -0.4399f + 0.7099f / eta - 0.3319f / e2 + 0.0636f / (e2 * eta);
}

// VelvetAlbedo.ispc
X2_HD inline float velvetAlbedoAt(float cosTheta, float roughness) {
    roughness = clampf(roughness, 0.0f, 1.0f);
    const int r1 = int(floorf(roughness * 20.0f - 1.0f)), r2 = int(ceilf(roughness * 20.0f - 1.0f));
    cosTheta = clampf(cosTheta, 0.0f, 1.0f);
    const int cosIndex = int(cosTheta * 100.0f - 1.0f);  // truncation, as ISPC's int conversion
    const int lo = r1 * 100 + cosIndex < 0 ? 0 : (r1 * 100 + cosIndex > 1999 ? 1999 : r1 * 100 + cosIndex);
    const int hi = r2 * 100 + cosIndex < 0 ? 0 : (r2 * 100 + cosIndex > 1999 ? 1999 : r2 * 100 + cosIndex);
    const float frac = roughness - float(int(roughness));
    return (1.0f - frac) * tables::VelvetAlbedo_albedoTable[lo] + frac * tables::VelvetAlbedo_albedoTable[hi];
}

struct FresnelPool {
    Fresnel items[24];
    U32 count = 0;
};
X2_HD inline U32 addFresnel(FresnelPool& p, const Fresnel& f) {
    if (p.count >= 24) return NoIndex;
    p.items[p.count] = f;
    return p.count++;
}

X2_HD inline Color schlickEval(const Fresnel& f, float hDotWi) {
    if (f.f0 == 0.f) return f.a;
    float tmp;
    if (f.f1 > 1.0f) {
        const float rcpNeta = 1.0f / f.f1, cosSqrCritical = 1.0f - rcpNeta * rcpNeta;
        if (hDotWi * hDotWi < cosSqrCritical) return rgb(1);
        tmp = (1.0f - hDotWi) / (1.0f - sqrtf(cosSqrCritical));
    } else {
        tmp = 1.0f - hDotWi;
    }
    float power = tmp * tmp;
    power = tmp * power * power;
    return f.a + f.f0 * (rgb(1) - f.a) * power;
}
X2_HD inline Color dielectricEval(float etaI, float etaT, float weight, float hDotWi) {
    hDotWi = fminf(fmaxf(hDotWi, -1.0f), 1.0f);
    const float eta = etaI / etaT, sinThetaSqr = eta * eta * (1.0f - hDotWi * hDotWi);
    if (sinThetaSqr >= 1.0f) return rgb(weight);
    const float cosTheta = sqrtf(1.0f - sinThetaSqr);
    hDotWi = fabsf(hDotWi);
    const float etaTH = etaT * hDotWi, etaIC = etaI * cosTheta;
    const float parallel = (etaTH - etaIC) / (etaTH + etaIC);
    const float etaIH = etaI * hDotWi, etaTC = etaT * cosTheta;
    const float perp = (etaIH - etaTC) / (etaIH + etaTC);
    return rgb(0.5f * (parallel * parallel + perp * perp) * weight);
}
X2_HD inline Color conductorEval(Color eta, Color k, float weight, float hDotWi) {
    const float h2 = hDotWi * hDotWi;
    const Color factor = eta * eta + k * k, tmp = factor * h2, etaH = eta * hDotWi;
    const Color parallel = (tmp - 2.0f * etaH + rgb(1)) / (tmp + 2.0f * etaH + rgb(1));
    const Color perp = (factor - 2.0f * etaH + rgb(h2)) / (factor + 2.0f * etaH + rgb(h2));
    return 0.5f * (parallel + perp) * weight;
}
// Fresnel.ispc LayeredDielectricFresnel
X2_HD inline Color layeredDielectricEval(const Fresnel& f, float hDotI) {
    float cosThetaI = fminf(fmaxf(hDotI, -1.0f), 1.0f);
    const float eta = 1.0f / f.etaT, sinThetaTSqr = eta * eta * (1.0f - cosThetaI * cosThetaI);
    if (sinThetaTSqr >= 1.0f) return rgb(f.weight);
    const float cosThetaT = sqrtf(1.0f - sinThetaTSqr);
    cosThetaI = fabsf(cosThetaI);
    const float eI = f.etaI, eP = f.etaT;
    const float sA = eI * cosThetaI, sB = eP * cosThetaT, perp = (sA - sB) / (sA + sB), Fs = perp * perp;
    const float pA = eP * cosThetaI, pB = eI * cosThetaT, par = (pA - pB) / (pA + pB), Fp = par * par;
    const float t1 = Fs + (1.0f - Fs) * (1.0f - Fs) * Fs / (1.0f - Fs * Fs);
    const float t2 = Fp + (1.0f - Fp) * (1.0f - Fp) * Fp / (1.0f - Fp * Fp);
    const float F = 0.5f * t1 + 0.5f * t2, n = f.f0 * F, d = 1.0f + (f.f0 - 1.0f) * F;
    return f.weight * rgb(clampf(n / d, 0.0f, 1.0f));
}
// A Fresnel and the one-minus Fresnels that wrap it, evaluated without
// recursion (OptiX rejects a recursive call graph): the wrappers are walked down
// to the base, which is evaluated, and their operations applied on the way out.
X2_HD inline Color fresnelBase(const Fresnel& f, float c) {
    switch (f.kind) {
    case FresnelSchlick: return schlickEval(f, c);
    case FresnelOneMinusVelvet: return rgb(1.0f - velvetAlbedoAt(c, f.f0) * f.weight);
    case FresnelConductor: return conductorEval(f.a, f.b, f.weight, c);
    case FresnelDielectric: return dielectricEval(f.etaI, f.etaT, f.weight, c);
    case FresnelLayeredDielectric: return layeredDielectricEval(f, c);
    default: return rgb(1);
    }
}
X2_HD inline bool fresnelWraps(U32 kind) {
    return kind == FresnelOneMinus || kind == FresnelOneMinusRough || kind == FresnelOneMinusRoughSchlick;
}
X2_CALL Color fresnelChain(const FresnelPool& pool, U32 index, float c) {
    U32 ops[8];
    U32 n = 0;
    while (index < pool.count && fresnelWraps(pool.items[index].kind) && n < 8) {
        ops[n++] = index;
        index = pool.items[index].top;
    }
    if (index >= pool.count) return rgb(0);
    Color r = fresnelBase(pool.items[index], c);
    while (n) {
        const Fresnel& w = pool.items[ops[--n]];
        if (w.kind == FresnelOneMinus) {
            r = rgb(1) - r;
        } else if (w.kind == FresnelOneMinusRough) {
            r = lerp(rgb(1) - r, w.a, w.f1);
        } else {  // one minus rough Schlick: a holds the top Schlick's spec
            const float tmp = 1.0f - w.f0, t = 1.0f - tmp * tmp * tmp;
            r = lerp(rgb(1) - r, rgb(1) - w.a, clampf(t, 0.f, 1.f));
        }
    }
    return r;
}
X2_CALL Color fresnelEval(const FresnelPool& pool, U32 index, float hDotWi) {
    if (index >= pool.count) return rgb(1);
    const Fresnel& f = pool.items[index];
    if (f.kind != FresnelMultipleTransmission) return fresnelChain(pool, index, hDotWi);
    Color r = rgb(1);
    for (U32 i = 0; i < f.count && i < MaxMultipleFresnels; ++i) r = r * fresnelChain(pool, f.list[i], hDotWi);
    return r;
}

// Constructors (the _init functions), returning the pool index.
X2_HD inline U32 schlickFresnel(FresnelPool& p, Color spec, float factor, float neta = 1.0f, float weight = 1.0f) {
    Fresnel f;
    f.kind = FresnelSchlick;
    f.a = spec;
    f.f0 = factor;
    f.f1 = neta;
    f.weight = weight;
    return addFresnel(p, f);
}
X2_HD inline U32 dielectricFresnel(FresnelPool& p, float etaI, float etaT, float weight = 1.0f) {
    Fresnel f;
    f.kind = FresnelDielectric;
    f.etaI = etaI;
    f.etaT = etaT;
    f.weight = weight;
    return addFresnel(p, f);
}
X2_HD inline U32 layeredDielectricFresnel(FresnelPool& p, float etaI, float etaT, float thickness, float weight = 1.0f) {
    Fresnel f;
    f.kind = FresnelLayeredDielectric;
    f.etaI = etaI;
    f.etaT = etaT;
    f.weight = weight;
    f.f0 = lerpf(0.5f, 1.5f, thickness);
    return addFresnel(p, f);
}
X2_HD inline U32 conductorFresnel(FresnelPool& p, Color eta, Color k, float weight = 1.0f) {
    Fresnel f;
    f.kind = FresnelConductor;
    f.a = eta;
    f.b = k;
    f.weight = weight;
    return addFresnel(p, f);
}
X2_HD inline U32 oneMinusFresnel(FresnelPool& p, U32 top) {
    if (top == NoIndex) return NoIndex;
    Fresnel f;
    f.kind = FresnelOneMinus;
    f.top = top;
    return addFresnel(p, f);
}
X2_HD inline U32 oneMinusRoughFresnel(FresnelPool& p, U32 top, float specRoughness) {
    if (top == NoIndex) return NoIndex;
    Fresnel f;
    f.kind = FresnelOneMinusRough;
    f.top = top;
    const float r = specRoughness * specRoughness, tmp = 1.0f - r;
    f.f0 = r;
    f.f1 = clampf(1.0f - tmp * tmp * tmp, 0.0f, 1.0f);
    f.a = rgb(1) - fresnelEval(p, top, 1.0f);
    return addFresnel(p, f);
}
X2_HD inline U32 oneMinusRoughSchlickFresnel(FresnelPool& p, U32 schlick, float specRoughness) {
    if (schlick == NoIndex) return NoIndex;
    Fresnel f;
    f.kind = FresnelOneMinusRoughSchlick;
    f.top = schlick;
    f.f0 = specRoughness * specRoughness;
    f.a = p.items[schlick].a;
    return addFresnel(p, f);
}
X2_HD inline U32 oneMinusVelvetFresnel(FresnelPool& p, float roughness, float weight) {
    Fresnel f;
    f.kind = FresnelOneMinusVelvet;
    f.f0 = roughness;
    f.weight = weight;
    return addFresnel(p, f);
}
X2_HD inline U32 multipleTransmissionFresnel(FresnelPool& p) {
    Fresnel f;
    f.kind = FresnelMultipleTransmission;
    return addFresnel(p, f);
}
X2_HD inline void multipleTransmissionAdd(FresnelPool& p, U32 multiple, U32 fresnel) {
    if (multiple == NoIndex || fresnel == NoIndex) return;
    Fresnel& f = p.items[multiple];
    if (f.count < MaxMultipleFresnels) f.list[f.count++] = (unsigned char)fresnel;
}
// The roughness property a one-minus-rough Fresnel reports (its input roughness).
X2_HD inline bool fresnelRoughness(const FresnelPool& p, U32 index, float& r) {
    if (index >= p.count) return false;
    const Fresnel& f = p.items[index];
    if (f.kind == FresnelOneMinusRough || f.kind == FresnelOneMinusRoughSchlick) {
        r = sqrtf(f.f0);
        return true;
    }
    if (f.kind == FresnelOneMinusVelvet) {
        r = f.f0;
        return true;
    }
    return false;
}
}}}
