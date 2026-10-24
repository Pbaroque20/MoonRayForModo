// Private XPU2 shading library, shared CPU/CUDA: MoonRay's BSDF lobes and the
// Bsdf that holds them (shading/ispc/bsdf: Bsdf, BsdfSlice, BsdfLambert,
// BsdfOrenNayar, cook_torrance (Beckmann, GGX, anisotropic, Berry, glitter,
// transmission, energy compensation), BsdfMirror, BsdfRetroreflection,
// BsdfEyeCaustic, fabric (DwaFabric, Kajiya-Kay, velvet), under (Under,
// UnderClearcoat, UnderClearcoatTransmission), BsdfIridescence). Derived from
// MoonRay Apache-2.0, Copyright 2023-2024 DreamWorks Animation LLC. See
// MOONRAY_LICENSE.txt.
//
// The vector (ISPC) lobes are what MoonRay XPU shades with; these follow them.
// MoonRay's lobes are objects with function pointers that wrap one another
// (under-layer attenuation, iridescence); here a lobe is a record in its Bsdf
// with a kind, and a wrapper names the record it wraps by index. Evaluation
// walks a chain of wrappers iteratively (no recursion on the GPU).
#pragma once
#include "shade_bssrdf.h"
#include "shade_fresnel.h"
#include "shade_color.h"
namespace xpu2 { namespace interactive { namespace shade {

// BsdfLobe::Type
enum LobeType : U32 {
    LobeNone = 0,
    Reflection = 1u << 0,
    Transmission = 1u << 1,
    Diffuse = 1u << 2,
    Glossy = 1u << 4,
    Mirror = 1u << 6,
    AllSurfaceSides = Reflection | Transmission,
    AllLobes = Diffuse | Glossy | Mirror,
    AllReflection = AllLobes | Reflection,
    AllTransmission = AllLobes | Transmission,
    AllDiffuse = AllSurfaceSides | Diffuse,
    AllGlossy = AllSurfaceSides | Glossy,
    AllMirror = AllSurfaceSides | Mirror,
    AllLobeTypes = AllReflection | AllTransmission
};
X2_HD inline bool matchesFlags(U32 type, U32 flags) { return (type & AllSurfaceSides & flags) && (type & AllLobes & flags); }

enum LobeKind : U32 {
    KindLambert,
    KindOrenNayar,
    KindCookTorrance,     // Beckmann
    KindGGX,
    KindAnisoCookTorrance,
    KindBerryCookTorrance,
    KindGlitterGGX,
    KindTransmissionCookTorrance,
    KindMirrorReflection,
    KindMirrorTransmission,
    KindMirrorRetroreflection,
    KindRetroreflection,
    KindEyeCaustic,
    KindFabric,
    KindVelvet,
    KindUnder,
    KindUnderClearcoat,
    KindUnderClearcoatTransmission,
    KindIridescence,
    KindFlatDiffuse,
    KindToon,          // ToonBsdfLobe: a ramp over the cosine
    KindToonSpecular,  // ToonSpecularBsdfLobe
    KindHairOneSampler,  // HairOneSamplerBsdfLobe (shade_hair.h)
    KindHairR,           // the separate hair lobes
    KindHairTRT,
    KindHairTT,
    KindHairTRRT,
    KindHairDiffuse,     // HairDiffuseBsdfLobe
    KindStochasticFlakes,  // StochasticFlakesBsdfLobe: glitter's micro flakes (shade_flakes.h)
    KindHairToonSpecular,  // HairToonSpecularBsdfLobe: a hair R lobe through a ramp
    KindCount
};
enum ShadowTerminatorFix : U32 { StfOff = 0, StfCustom, StfSineCompensation, StfGGX, StfCosineCompensation };
enum MicrofacetDistribution : U32 { Beckmann = 0, GGXDistribution = 1 };
enum LobeFlags : U32 { FlagSpherical = 1, FlagHair = 2, FlagIgnoresIncomingDifferentials = 4 };

struct Slice {
    V3 Ng, wo;
    U32 flags;
    U32 stf;
    bool includeCosine, entering;
};

struct CookTorranceParams {
    float inputRoughness, roughness, invRoughness, dDFactor;
    Color favg, favgInv;
    float etaI, etaT;
    U32 coupled;
    float inputRoughnessV, roughnessV;  // anisotropic
    V3 flakeNormal;                     // glitter
    // transmission
    float neta, etaR, etaG, etaB;
    Color tint;
    U32 allowDispersion;
};
struct DiffuseParams {
    Color albedo;
    float roughness, A, B;
    float terminatorShift, flatness, flatnessFalloff;  // FlatDiffuse
};
struct MirrorParams {
    float etaI, etaT, etaR, etaG, etaB;
    Color tint;
    U32 allowDispersion;
};
struct RetroParams {
    float inputRoughness, roughness, dDFactor;
};
struct EyeCausticParams {
    V3 Ng;
    Color causticColor, eyeMask;
    float exponent, normalization, dDFactor;
};
struct FabricParams {
    float roughness, specularExponent, normalization, dDFactor;
    V3 threadDirection;
    Color color;
    U32 useDwaFabric;
};
struct UnderParams {
    V3 N;
    float thickness;
    Color attenuationColor;
    float attenuationWeight;
    U32 exitingFresnel;
    float neta;
    U32 passThroughTIR;
};
// ToonBsdfLobe and ToonSpecularBsdfLobe; their ramps are in the Bsdf's ramp pool (a float ramp in x).
struct ToonParams {
    Color albedo, tint;
    float rampInputScale;
    U32 ramp, extendRamp;
    float intensity, fresnelBlend, stretchU, stretchV, normalization, indirectIntensity;
    V3 dPds, dPdt;
    U32 enableIndirect, indirect;  // the indirect reflections' GGX lobe record
};
// Hair: a lobe's parameters in its Bsdf's hair pool (HairRecord), and what the lobe keeps itself: its ray
// differential factor and roughness property, and a hair diffuse lobe's direction and colours.
struct HairParams {
    U32 record;
    float dDFactor, roughU, roughV;
    V3 dir;
    Color refl, trans;
};
enum HairFresnelType : U32 { HairFresnelSimpleLongitudinal = 0, HairFresnelDielectricCylinder, HairFresnelLayeredCuticles };
enum HairComponentIndex : U32 { HairR = 0, HairTRT, HairTT, HairTRRT };
// One scattering component (R, TRT, TT, TRRT): whether shown, its longitudinal shift, roughness and variance, its
// azimuthal roughness and variance, tint and saturation.
struct HairComponent {
    U32 show;
    float sinAlpha, cosAlpha, longRoughness, longVariance, azimRoughness, azimVariance;
    Color tint;
    float saturation;
};
// A hair lobe's record (BSDF_HAIR_LOBE_BASE and the one-sampler's members): the one-sampler's four components, or
// a separate lobe's own as c[0].
struct HairRecord {
    V3 hairDir;
    float uv[2], h, mediumIor, ior;
    U32 fresnelType;
    float cuticle;  // the layered cuticles' layer count, lerp(0.5, 1.5, thickness)
    Color hairColor, sigmaA;
    float hairRotation;
    V3 hairNormal;
    U32 showGlint;
    float glintRoughness, glintEccentricity, glintSaturation;
    HairComponent c[4];
};
// HairToonSpecularBsdfLobe: its hair record's c[0] the direct R lobe, c[1] the indirect one; its ramp in the Bsdf's ramp
// pool (a float ramp in x); dDFactor the indirect lobe's.
struct HairToonParams {
    U32 record, ramp, enableIndirect;
    float intensity, indirectIntensity, dDFactor;
    Color tint;
};
// StochasticFlakesBsdfLobe: its flakes are its Bsdf's flake set (GlitterFlakeSet).
struct FlakesParams {
    float randomness, cosGamma;
    U32 count;
};
// Glitter's micro flakes as a stochastic flakes lobe reads them (Glitter.ispc createMicroFlake): flake i's id is ids[i];
// its normal the flake table's normal at that id in the reference frame, its colour computeFlakeColor's of the id and
// of base colour (i + offset) mod macroCount. The ids live in the shading thread's glitter scratch, the tables in the
// material pool.
struct GlitterFlakeSet {
    const unsigned short* ids = nullptr;
    const float* tables = nullptr;
    Frame refFrame{};
    Color baseColors[4];
    V3 hsvVariation{0, 0, 0};
    U32 offset = 0, macroCount = 1;
};
struct IridescenceParams {
    V3 N;
    float iridescence;
    U32 colorControl;  // 0 hue interpolation, 1 ramp
    Color primary, secondary;
    U32 flipHue;
    float thickness, exponent, at0, at90;
    U32 ramp;          // index of the ramp in the Bsdf's ramp pool
};

struct Lobe {
    U32 kind = KindLambert, type = 0, flags = 0;
    // label: its AOV label ids as aovEncodeLabels makes them (encodedLabel), 0 for none.
    U32 fresnel = NoIndex, child = NoIndex, label = 0;
    Color scale{1, 1, 1};
    Frame frame{};  // z is the lobe normal N
    union {
        CookTorranceParams ct;
        DiffuseParams diffuse;
        MirrorParams mirror;
        RetroParams retro;
        EyeCausticParams eye;
        FabricParams fabric;
        UnderParams under;
        IridescenceParams iri;
        ToonParams toon;
        HairParams hair;
        FlakesParams flakes;
        HairToonParams hairToon;
    };
    X2_HD Lobe() : ct() {}
};


constexpr U32 MaxLobes = 16, MaxLobeRecords = 32, MaxRamps = 4;  // ramps: iridescence colours, toon ramps
constexpr U32 MaxHairRecords = 4;  // a hair material's separate lobes
struct Bsdf {
    Lobe records[MaxLobeRecords];
    unsigned char top[MaxLobes];
    U32 topCount = 0, recordCount = 0, type = 0;
    bool spherical = false, earlyTermination = false;
    bool fatal = false;  // a hit without an attribute its shading requires: the fatal colour alone
    // The material's own label ids (encodedLabel of label 0: Bsdf::getMaterialLabelId, getLpeMaterialLabelId).
    U32 materialLabels = 0;
    Color selfEmission{0, 0, 0};
    FresnelPool fresnels;
    ColorRamp ramps[MaxRamps];
    U32 rampCount = 0;
    BssrdfRecord bssrdf;  // its diffusion subsurface profile (type BssrdfNone: none)
    HairRecord hairs[MaxHairRecords];  // its hair lobes' parameters
    U32 hairCount = 0;
    GlitterFlakeSet flakeSet;  // its stochastic flakes lobe's flakes (one glitter a material)
    // The material's extra AOVs at this hit (shading::Material's extra AOVs, ListMap of ExtraAovMaps): each one's
    // light path expression label ('U:' and its label), its value, and (extraPost, a bit each) whether it is
    // accumulated after the scattering (Bsdf::setPostScatterExtraAovs) rather than at the hit.
    static constexpr U32 MaxExtraAovs = 20;
    U32 extraCount = 0, extraPost = 0;
    int extraLabel[MaxExtraAovs];
    Color extraValue[MaxExtraAovs];
};
// Empties a Bsdf for reuse without touching its records' storage.
X2_HD inline void reset(Bsdf& b) {
    b.topCount = b.recordCount = b.type = 0;
    b.spherical = b.earlyTermination = b.fatal = false;
    b.materialLabels = 0;
    b.selfEmission = Color{0, 0, 0};
    b.fresnels.count = 0;
    b.rampCount = 0;
    b.bssrdf.type = BssrdfNone;
    b.hairCount = 0;
    b.extraCount = b.extraPost = 0;
}
X2_HD inline U32 newRecord(Bsdf& b) {
    if (b.recordCount >= MaxLobeRecords) return NoIndex;
    b.records[b.recordCount] = Lobe();
    return b.recordCount++;
}
X2_HD inline bool addLobe(Bsdf& b, U32 record) {
    if (record == NoIndex || b.topCount >= MaxLobes) return false;
    b.top[b.topCount++] = (unsigned char)record;
    b.type |= b.records[record].type;
    if (b.records[record].flags & FlagSpherical) b.spherical = true;
    return true;
}
X2_HD inline const Lobe& topLobe(const Bsdf& b, U32 i) { return b.records[b.top[i]]; }
// AovLabels.hh: a label's material AOV id (bits 0 to 15 less one) and its light path expression id (bits 16 to 31 less
// one), -1 for none.
X2_HD inline U32 encodedLabel(int materialAovId, int lpeId) {
    return U32(materialAovId + 1) & 0xffffu | (U32(lpeId + 1) & 0xffffu) << 16;
}
X2_HD inline int labelMaterialAovId(U32 encoded) { return int(encoded & 0xffffu) - 1; }
X2_HD inline int labelLpeId(U32 encoded) { return int(encoded >> 16) - 1; }

X2_HD inline Color scaleAndFresnel(const Bsdf& b, const Lobe& l, float cosWi) {
    return l.fresnel == NoIndex ? l.scale : l.scale * fresnelEval(b.fresnels, l.fresnel, cosWi);
}

// BsdfSlice.ispc
X2_HD inline float shadowTerminatorFix(const Slice& s, V3 N, V3 wi) {
    switch (s.stf) {
    case StfOff: return 1.0f;
    case StfCustom: {
        const float cosX = clampf(dot(N, s.Ng), 0.0f, 1.0f), d = 0.14944f * (1.0f - cosX) + 0.01999f * cosX;
        const float t = clampf(dot(s.Ng, wi) / d, 0.0f, 1.0f);
        return t * t * (3.0f - 2.0f * t);
    }
    case StfSineCompensation: {
        float G = clampf(fminf(1.0f, dot(s.Ng, wi) / (fmaxf(Epsilon, dot(N, wi)) * fmaxf(Epsilon, length(cross(s.Ng, N))))),
                         0.0f, 1.0f);
        return -(G * G * G) + G * G + G;
    }
    case StfGGX: {
        const float cosD = fminf(fabsf(dot(s.Ng, N)), 1.0f), tan2D = (1.0f - cosD * cosD) / (cosD * cosD);
        const float alpha2 = clampf(0.125f * tan2D, 0.0f, 1.0f);
        const float cosI = fmaxf(fabsf(dot(s.Ng, wi)), Epsilon), tan2I = (1.0f - cosI * cosI) / (cosI * cosI);
        return 2.0f / (1.0f + sqrtf(1.0f + alpha2 * tan2I));
    }
    case StfCosineCompensation: {
        float G = clampf(fminf(1.0f, dot(s.Ng, wi) / (fmaxf(Epsilon, dot(N, wi)) * fmaxf(Epsilon, dot(s.Ng, N)))), 0.0f, 1.0f);
        return -(G * G * G) + G * G + G;
    }
    default: return 1.0f;
    }
}
// Bsdf-level surface flags for a direction (BsdfSlice_getSurfaceFlags).
X2_HD inline U32 surfaceFlags(const Slice& s, bool spherical, V3 wi) {
    if (spherical) return s.flags;
    return dot(s.Ng, s.wo) * dot(s.Ng, wi) > 0.0f ? (s.flags & ~U32(Transmission)) : (s.flags & ~U32(Reflection));
}

//----------------------------------------------------------------------------
// Energy compensation (cook_torrance/energy_conservation)
namespace energy {
constexpr U32 Comp = 33;
X2_HD inline U32 rIndex(float roughness, float& weight) {
    const float i = roughness * float(Comp - 1), indexI = floorf(i);
    weight = i - indexI;
    return U32(indexI);
}
X2_HD inline void index(float cosTheta, float roughness, float& w, U32& lo, U32& hi) {
    const U32 l = rIndex(roughness, w), h = l + 1 < Comp * Comp - 1 ? l + 1 : Comp * Comp - 1;
    lo = U32(ceilf(float(l * Comp) + cosTheta * float(Comp - 1)));
    hi = U32(ceilf(float(h * Comp) + cosTheta * float(Comp - 1)));
}
X2_HD inline float reflectionE(U32 type, float cosTheta, float roughness) {
    float w;
    U32 lo, hi;
    index(cosTheta, roughness, w, lo, hi);
    const float* t = type == Beckmann ? tables::ReflectionAlbedo_BeckmannE : tables::ReflectionAlbedo_GGXE;
    lo = lo < Comp * Comp ? lo : Comp * Comp - 1;
    hi = hi < Comp * Comp ? hi : Comp * Comp - 1;
    return lerpf(t[lo], t[hi], w);
}
X2_HD inline float reflectionOneMinusAvg(U32 type, float roughness) {
    float w;
    const U32 lo = rIndex(roughness, w), hi = lo + 1 < Comp - 1 ? lo + 1 : Comp - 1;
    const float* t = type == Beckmann ? tables::ReflectionAlbedo_BeckmannOneMinusEavg : tables::ReflectionAlbedo_GGXOneMinusEavg;
    return lerpf(t[lo < Comp ? lo : Comp - 1], t[hi], w);
}
X2_HD inline Color reflectionEval(U32 type, float cosNO, float cosNI, float roughness, Color favg, bool includeCosine) {
    float compensation = (1.0f - reflectionE(type, cosNO, roughness)) * (1.0f - reflectionE(type, cosNI, roughness));
    const float divisor = reflectionOneMinusAvg(type, roughness);
    compensation = !isZero(divisor) ? compensation / divisor : 0.0f;
    const float eavg = 1.0f - reflectionOneMinusAvg(type, roughness);
    const Color multiplier = (favg * favg * eavg) / (rgb(1) - favg * (1.0f - eavg));
    return compensation * multiplier * OneOverPi * (includeCosine ? cosNI : 1.0f);
}
X2_HD inline void reflectionSample(U32 type, const Frame& f, float r1, float r2, float r, V3& wi) {
    const float power = type == Beckmann ? 2.767f * r * r - 5.4f * r + 2.99412f : 1.1933f * r * r - 2.0969f * r + 1.3698f;
    const float cosThetaI = powf(r1, power), sinThetaI = sqrtf(1.0f - cosThetaI * cosThetaI);
    wi = localToGlobal(f, localSpherical(cosThetaI, sinThetaI, TwoPi * r2));
}
X2_HD inline float reflectionPdf(U32 type, float cosNI, float roughness) {
    const float norm = Pi * reflectionOneMinusAvg(type, roughness);
    if (isZero(norm)) return 0.0f;
    return fmaxf(0.0f, cosNI * (1.0f - reflectionE(type, cosNI, roughness)) / norm);
}
X2_HD inline float reflectionWeight(float roughness) { return fmaxf(0.0f, roughness - 0.5f); }
// TransmissionAlbedo.isph
X2_HD inline float netaRange(float eta) { return (eta - 1.05f) / (3.05f - 1.05f); }
X2_HD inline U32 nIndex(float eta) { return U32(clampf(netaRange(eta), 0.0f, 1.0f) * float(Comp - 1)); }
X2_HD inline U32 trIndex(float eta, float roughness, float& weight) {
    const float i = float(nIndex(eta) * Comp) + roughness * float(Comp - 1), indexI = floorf(i);
    weight = i - indexI;
    return U32(indexI);
}
X2_HD inline void trIndices(float eta, float cosTheta, float roughness, float& w, U32& lo, U32& hi) {
    const U32 l = trIndex(eta, roughness, w), h = l + 1 < Comp * Comp - 1 ? l + 1 : Comp * Comp - 1;
    lo = U32(ceilf(float(l * Comp) + cosTheta * float(Comp - 1)));
    hi = U32(ceilf(float(h * Comp) + cosTheta * float(Comp - 1)));
}
X2_HD inline float transmissionE(float eta, float cosTheta, float roughness) {
    float w;
    U32 lo, hi;
    const float* t = tables::TransmissionAlbedo_E;
    if (eta < 1.0f) {
        trIndices(1.0f / eta, cosTheta, roughness, w, lo, hi);
        t = tables::TransmissionAlbedo_EExit;
    } else {
        trIndices(eta, cosTheta, roughness, w, lo, hi);
    }
    const U32 n = Comp * Comp * Comp;
    return lerpf(t[lo < n ? lo : n - 1], t[hi < n ? hi : n - 1], w);
}
X2_HD inline float transmissionOneMinusAvg(float eta, float roughness) {
    float w;
    U32 lo;
    const float* t = tables::TransmissionAlbedo_OneMinusEavg;
    if (eta < 1.0f) {
        lo = trIndex(1.0f / eta, roughness, w);
        t = tables::TransmissionAlbedo_OneMinusEavgExit;
    } else {
        lo = trIndex(eta, roughness, w);
    }
    const U32 hi = lo + 1 < Comp * Comp - 1 ? lo + 1 : Comp * Comp - 1;
    return lerpf(t[lo < Comp * Comp ? lo : Comp * Comp - 1], t[hi], w);
}
X2_HD inline float computeFactor(float favg, float favgInv, float etaI, float etaT, float roughness) {
    const float neta = etaI < etaT ? etaT / etaI : etaI / etaT;
    const float divisor = transmissionOneMinusAvg(neta, roughness);
    if (isZero(divisor)) return 1.0f;
    float y = transmissionOneMinusAvg(1.0f / neta, roughness) / divisor;
    y *= neta * neta;
    const float t = y * (1.0f - favgInv) / (1.0f - favg);
    return fmaxf(0.0f, t / (1.0f + t));
}
X2_HD inline Color transmissionEvalR(float cosNO, float cosNI, float roughness, float etaI, float etaT, float favg,
                                     float favgInv, bool includeCosine) {
    const float neta = etaT / etaI;
    float compensation = (1.0f - transmissionE(neta, cosNO, roughness)) * (1.0f - transmissionE(neta, cosNI, roughness));
    const float divisor = transmissionOneMinusAvg(neta, roughness);
    const float factor = computeFactor(favg, favgInv, etaI, etaT, roughness);
    const float ratio = neta > 1.0f ? 1.0f - (1.0f - favg) * factor : 1.0f - (1.0f - favgInv) * (1.0f - factor);
    compensation = !isZero(divisor) ? compensation / divisor : 0.0f;
    compensation *= OneOverPi;
    return rgb(fmaxf(0.0f, ratio * compensation * (includeCosine ? cosNI : 1.0f)));
}
X2_HD inline Color transmissionEvalT(float cosNO, float cosNI, float roughness, float etaI, float etaT, float favg,
                                     float favgInv, bool includeCosine) {
    const float neta = etaT / etaI;
    const float divisor = transmissionOneMinusAvg(1.0f / neta, roughness);
    const float factor = computeFactor(favg, favgInv, etaI, etaT, roughness);
    float n, ratio;
    if (etaI < etaT) {
        n = 1.0f;
        ratio = (1.0f - favg) * factor;
    } else {
        n = etaT / etaI;
        ratio = (1.0f - favgInv) * (1.0f - factor);
    }
    float compensation = (1.0f - transmissionE(neta, cosNO, roughness)) * (1.0f - transmissionE(1.0f / neta, cosNI, roughness));
    compensation = !isZero(divisor) ? compensation / divisor : 0.0f;
    compensation *= OneOverPi;
    return rgb(fmaxf(0.0f, ratio * compensation * n * n * (includeCosine ? cosNI : 1.0f)));
}
X2_HD inline void transmissionSampleR(const Frame& f, float r1, float r2, V3& wi, float r, float etaI, float etaT) {
    float cosThetaI;
    if (etaI < etaT) {
        const float n = netaRange(etaT / etaI), power = (0.133f * n + 3.02f) * r * r + (-0.66f * n - 5.12f) * r + 3.009f;
        cosThetaI = powf(r1, power);
    } else {
        const float n = netaRange(etaI / etaT), power = (0.38f * n + 2.4f) * r * r + (-0.68f * n - 4.34f) * r + 2.57f;
        cosThetaI = powf(r1, power);
    }
    cosThetaI = clampf(cosThetaI, 0.0f, 0.99f);
    float sinThetaI = clampf(1.0f - cosThetaI * cosThetaI, 0.0f, 1.0f);
    sinThetaI = sinThetaI > 0.0f ? sqrtf(sinThetaI) : 0.0f;
    wi = localToGlobal(f, localSpherical(cosThetaI, sinThetaI, TwoPi * r2));
}
X2_HD inline float transmissionPdfR(float cosNI, float etaI, float etaT, float roughness) {
    const float neta = etaT / etaI, norm = Pi * transmissionOneMinusAvg(neta, roughness);
    return fmaxf(0.0f, cosNI * (1.0f - transmissionE(neta, cosNI, roughness)) / norm);
}
X2_HD inline float transmissionWeightR(float etaI, float etaT, float roughness) {
    return fmaxf(0.0f, etaI < etaT ? roughness - 0.5f : roughness - 0.3f);
}
}  // namespace energy

//----------------------------------------------------------------------------
// Constructors (the lobes' _init functions). Each returns the new record's
// index, or NoIndex when the Bsdf is full.
constexpr float CtDFactorMin = 1.0f, CtDFactorSlope = 7.0f;

X2_HD inline U32 lambertLobe(Bsdf& b, V3 N, Color albedo, bool reflection) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindLambert;
    l.type = (reflection ? Reflection : Transmission) | Diffuse;
    l.flags = FlagIgnoresIncomingDifferentials;
    l.frame = frame(N);
    l.diffuse.albedo = albedo;
    l.diffuse.roughness = 1.0f;
    return i;
}
X2_HD inline U32 orenNayarLobe(Bsdf& b, V3 N, Color albedo, float roughness, bool reflection) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindOrenNayar;
    l.type = (reflection ? Reflection : Transmission) | Diffuse;
    l.flags = FlagIgnoresIncomingDifferentials;
    l.frame = frame(N);
    l.diffuse.albedo = albedo;
    l.diffuse.roughness = roughness;
    float s = deg2rad(roughness * 90.0f);
    s = s * s;
    l.diffuse.A = 1.0f - 0.5f * (s / (s + 0.33f));
    l.diffuse.B = 0.45f * (s / (s + 0.09f));
    return i;
}
// BsdfFlatDiffuse: Oren-Nayar with the NPR controls flatness and terminator shift.
X2_HD inline U32 flatDiffuseLobe(Bsdf& b, V3 N, Color albedo, float roughness, float terminatorShift, float flatness,
                                 float flatnessFalloff, bool reflection) {
    const U32 i = orenNayarLobe(b, N, albedo, roughness, reflection);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindFlatDiffuse;
    l.diffuse.terminatorShift = terminatorShift;
    l.diffuse.flatness = flatness;
    l.diffuse.flatnessFalloff = flatnessFalloff;
    return i;
}
X2_HD inline U32 toonLobe(Bsdf& b, V3 N, Color albedo, float rampInputScale, U32 ramp, bool extendRamp) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindToon;
    l.type = Reflection | Diffuse;
    l.flags = FlagIgnoresIncomingDifferentials;
    l.frame = frame(N);
    l.toon = ToonParams{};
    l.toon.albedo = albedo;
    l.toon.rampInputScale = rampInputScale;
    l.toon.ramp = ramp;
    l.toon.extendRamp = extendRamp ? 1 : 0;
    return i;
}
X2_HD inline U32 cookTorranceLobe(Bsdf& b, U32 kind, V3 N, float roughness, Color favg, Color favgInv, float etaI = 1.0f,
                                  float etaT = 1.5f, bool coupled = false) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = kind;  // KindCookTorrance, KindGGX or KindBerryCookTorrance
    l.type = Reflection | Glossy;
    l.frame = frame(N);
    CookTorranceParams& c = l.ct;
    c.inputRoughness = roughness;
    c.roughness = fmaxf(0.001f, roughness * roughness);
    c.invRoughness = 1.0f / c.roughness;
    c.dDFactor = CtDFactorMin + c.roughness * CtDFactorSlope;
    c.favg = favg;
    c.favgInv = favgInv;
    c.etaI = etaI;
    c.etaT = etaT;
    c.coupled = coupled ? 1 : 0;
    return i;
}
// ToonSpecularBsdfLobe_init: its indirect reflections a GGX lobe record of their own (the Fresnel shared).
X2_HD inline U32 toonSpecularLobe(Bsdf& b, V3 N, float intensity, float fresnelBlend, Color tint, float rampInputScale, U32 ramp,
                                  float stretchU, float stretchV, V3 dPds, V3 dPdt, bool enableIndirect, float indirectRoughness,
                                  float indirectIntensity, U32 fresnel, float normalization) {
    const U32 g = cookTorranceLobe(b, KindGGX, N, indirectRoughness, rgb(0), rgb(0));
    if (g == NoIndex) return g;
    b.records[g].fresnel = fresnel;
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindToonSpecular;
    l.type = Reflection | Glossy;
    l.frame = frame(N);
    l.toon = ToonParams{};
    l.toon.intensity = intensity;
    l.toon.fresnelBlend = fresnelBlend;
    l.toon.tint = tint;
    l.toon.rampInputScale = rampInputScale;
    l.toon.ramp = ramp;
    l.toon.stretchU = stretchU;
    l.toon.stretchV = stretchV;
    l.toon.dPds = dPds;
    l.toon.dPdt = dPdt;
    l.toon.normalization = normalization;
    l.toon.enableIndirect = enableIndirect ? 1 : 0;
    l.toon.indirectIntensity = indirectIntensity;
    l.toon.indirect = g;
    return i;
}
X2_HD inline U32 anisoCookTorranceLobe(Bsdf& b, V3 N, V3 anisoDirection, float roughnessU, float roughnessV) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindAnisoCookTorrance;
    l.type = Reflection | Glossy;
    l.frame = frame(N, anisoDirection);
    CookTorranceParams& c = l.ct;
    c.inputRoughness = roughnessU;
    c.inputRoughnessV = roughnessV;
    c.roughness = fmaxf(0.001f, roughnessU * roughnessU);
    c.roughnessV = fmaxf(0.001f, roughnessV * roughnessV);
    c.dDFactor = CtDFactorMin + fminf(c.roughness, c.roughnessV) * CtDFactorSlope;
    c.favg = c.favgInv = rgb(0);
    return i;
}
X2_HD inline U32 glitterGGXLobe(Bsdf& b, V3 N, V3 flakeNormal, float roughness, Color favg) {
    const U32 i = cookTorranceLobe(b, KindGlitterGGX, N, roughness, favg, rgb(0));
    if (i != NoIndex) b.records[i].ct.flakeNormal = flakeNormal;
    return i;
}
// StochasticFlakesBsdfLobe_init: the flakes are b.flakeSet's.
X2_HD inline U32 stochasticFlakesLobe(Bsdf& b, V3 N, U32 flakeCount, float roughness, float inputFlakeRandomness) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindStochasticFlakes;
    l.type = Reflection | Glossy;
    l.frame = frame(N);
    l.flakes.randomness = fmaxf(0.001f, inputFlakeRandomness * inputFlakeRandomness);
    l.flakes.cosGamma = fminf(0.999f, 1.0f - roughness * roughness);
    l.flakes.count = flakeCount < 2000u ? flakeCount : 2000u;  // StochasticFlakes_sMaxFlakes
    return i;
}
X2_HD inline U32 transmissionCookTorranceLobe(Bsdf& b, V3 N, float roughness, float etaI, float etaT, Color tint, float favg,
                                              float favgInv, float abbeNumber = 0.0f) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindTransmissionCookTorrance;
    l.type = Transmission | Glossy;
    l.frame = frame(N);
    CookTorranceParams& c = l.ct;
    c.tint = tint;
    c.inputRoughness = roughness;
    c.roughness = fmaxf(0.001f, roughness * roughness);
    c.invRoughness = 1.0f / c.roughness;
    c.etaI = etaI;
    c.etaT = etaT;
    c.neta = etaI / etaT;
    c.allowDispersion = isZero(abbeNumber) ? 0 : 1;
    if (c.allowDispersion) computeSpectralIOR(etaT, abbeNumber, c.etaR, c.etaG, c.etaB);
    c.dDFactor = CtDFactorMin + c.roughness * CtDFactorSlope;
    c.favg = rgb(favg);
    c.favgInv = rgb(favgInv);
    return i;
}
X2_HD inline U32 mirrorReflectionLobe(Bsdf& b, V3 N, U32 kind = KindMirrorReflection) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = kind;
    l.type = Reflection | Mirror;
    l.frame.z = N;
    return i;
}
X2_HD inline U32 mirrorTransmissionLobe(Bsdf& b, V3 N, float etaI, float etaT, Color tint, float abbeNumber = 0.0f) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindMirrorTransmission;
    l.type = Transmission | Mirror;
    l.frame.z = N;
    l.mirror.etaI = etaI;
    l.mirror.etaT = etaT;
    l.mirror.tint = tint;
    l.mirror.allowDispersion = isZero(abbeNumber) ? 0 : 1;
    if (l.mirror.allowDispersion) computeSpectralIOR(etaT, abbeNumber, l.mirror.etaR, l.mirror.etaG, l.mirror.etaB);
    return i;
}
X2_HD inline U32 retroreflectionLobe(Bsdf& b, V3 N, float roughness) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindRetroreflection;
    l.type = Reflection | Glossy;
    l.frame.z = N;
    l.retro.inputRoughness = roughness;
    l.retro.roughness = clampf(roughness * roughness, 0.001f, 0.99f);
    l.retro.dDFactor = 1.0f + l.retro.roughness * 7.0f;
    return i;
}
X2_HD inline U32 eyeCausticLobe(Bsdf& b, V3 N, V3 irisN, Color causticColor, float exponent, Color eyeMask) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindEyeCaustic;
    l.type = Reflection | Glossy;
    l.frame = frame(irisN);
    l.eye.Ng = N;
    l.eye.causticColor = causticColor;
    l.eye.eyeMask = eyeMask;
    l.eye.exponent = clampf(exponent, 0.1f, 20000.0f);
    l.eye.normalization = (l.eye.exponent + 2) * OneOverTwoPi;
    l.eye.dDFactor = 1.0f + (l.eye.exponent / 20000.0f) * 7.0f;
    return i;
}
X2_HD inline U32 fabricLobe(Bsdf& b, V3 N, V3 tangent, V3 threadDirection, float threadElevation, float roughness,
                            Color threadColor, bool useDwaFabric) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindFabric;
    l.type = Reflection | Glossy;
    l.flags = FlagIgnoresIncomingDifferentials;
    l.frame = frame(N, tangent);
    FabricParams& f = l.fabric;
    f.useDwaFabric = useDwaFabric ? 1 : 0;
    f.roughness = clampf(roughness, 0.05f, 1.0f);
    f.color = threadColor;
    float s, c;
    sincosf2(deg2rad(threadElevation), &s, &c);
    const V3 d{threadDirection.x * c - threadDirection.z * s, threadDirection.y, threadDirection.x * s + threadDirection.z * c};
    f.threadDirection = normalize(localToGlobal(l.frame, d));
    l.frame = isOne(dot(N, f.threadDirection)) ? frame(N) : frame(N, f.threadDirection);
    f.dDFactor = 1.0f + f.roughness * 7.0f;
    if (f.useDwaFabric) {
        const float rgh = 1.0f - f.roughness;
        f.specularExponent = ceilf(1.0f + 29.0f * rgh * rgh);
        const int index = int(clampf(f.specularExponent - 1, 0.0f, 30.0f));
        f.normalization = tables::precomputedDwaFabricNormalizationFactor[index];
    } else {
        const float oneOverR = 1.0f / f.roughness;
        f.specularExponent = 2.0f * oneOverR * oneOverR * oneOverR * oneOverR;
        f.normalization = sqrtf(f.specularExponent / 2.0f) * (1 + 3 / (4 * f.specularExponent)) * 0.1795871f;
    }
    return i;
}
X2_HD inline U32 velvetLobe(Bsdf& b, V3 N, float roughness, Color color) {
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.kind = KindVelvet;
    l.type = Reflection | Glossy;
    l.flags = FlagIgnoresIncomingDifferentials;
    l.frame = frame(N);
    FabricParams& f = l.fabric;
    f.roughness = clampf(roughness, 0.05f, 1.0f);
    f.color = color;
    f.specularExponent = 1.0f / f.roughness;
    const int tableIndex = int(floorf(f.roughness * 20.0f - 1.0f));
    f.normalization = 1.0f / tables::BsdfFabricVelvet_precomputedNormalizationTable[tableIndex < 0 ? 0 : tableIndex];
    f.dDFactor = 1.0f + f.roughness * 7.0f;
    return i;
}
// A wrapper takes its child's type, flags and properties (UnderBsdfLobe_init).
X2_HD inline U32 wrapperLobe(Bsdf& b, U32 kind, U32 child) {
    if (child == NoIndex) return NoIndex;
    const U32 i = newRecord(b);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    const Lobe& c = b.records[child];
    l.kind = kind;
    l.type = c.type;
    l.flags = c.flags;
    l.child = child;
    l.frame = c.frame;
    return i;
}
X2_HD inline U32 underLobe(Bsdf& b, U32 child, V3 N, float thickness, Color attenuationColor, float attenuationWeight) {
    const U32 i = wrapperLobe(b, KindUnder, child);
    if (i == NoIndex) return i;
    UnderParams& u = b.records[i].under;
    u.N = N;
    u.thickness = thickness;
    u.attenuationColor = attenuationColor;
    u.attenuationWeight = attenuationWeight;
    u.exitingFresnel = NoIndex;
    u.neta = 1.0f;
    u.passThroughTIR = 1;
    return i;
}
X2_HD inline U32 underClearcoatLobe(Bsdf& b, U32 kind, U32 child, V3 N, U32 exitingFresnel, float etaI, float etaT,
                                    float thickness, Color attenuationColor, float attenuationWeight) {
    const U32 i = underLobe(b, child, N, thickness, attenuationColor, attenuationWeight);
    if (i == NoIndex) return i;
    b.records[i].kind = kind;  // KindUnderClearcoat or KindUnderClearcoatTransmission
    b.records[i].under.exitingFresnel = exitingFresnel;
    b.records[i].under.neta = etaI / etaT;
    return i;
}
X2_HD inline U32 iridescenceLobe(Bsdf& b, U32 child, V3 N, float iridescence, U32 colorControl, Color primary, Color secondary,
                                 bool flipHue, U32 ramp, float thickness, float exponent, float at0, float at90) {
    const U32 i = wrapperLobe(b, KindIridescence, child);
    if (i == NoIndex) return i;
    Lobe& l = b.records[i];
    l.flags = 0;  // BsdfLobe_init(..., isSpherical false, ...)
    IridescenceParams& p = l.iri;
    p.N = N;
    p.iridescence = iridescence;
    p.colorControl = colorControl;
    p.primary = primary;
    p.secondary = secondary;
    p.flipHue = flipHue ? 1 : 0;
    p.ramp = ramp;
    p.thickness = thickness;
    p.exponent = exponent;
    p.at0 = at0;
    p.at90 = at90;
    return i;
}
}}}
#include "shade_lobes_eval.h"
