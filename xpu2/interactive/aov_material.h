// Material AOVs (pbr/core/Aov.ispc, as MoonRay's vector mode computes them): each property from the Bsdf's lobes,
// their Fresnels and its subsurface, through the properties MoonRay's lobes report (BsdfLobe_getProperty and each
// lobe's getProperty, Fresnel_getProperty, Bssrdf_getProperty, VolumeSubsurface_getProperty), with their PBR
// validity (PbrValidity.ispc). Normals are reported in MoonRay's render space.
#pragma once
#include "aov_core.h"
#include "shade_lobes.h"
#include "shade_bssrdf.h"
#include "shade_state.h"

namespace xpu2::interactive::aov {
using shade::Bsdf;
using shade::Color;
using shade::Lobe;

// BsdfLobeProperty and FresnelProperty.
enum LobeProperty : U32 { PropNormal = 1, PropRoughness = 2, PropColor = 4, PropPbrValidity = 8, PropEyeMask = 16 };
enum FresnelProperty : U32 { FresnelColor = 1, FresnelFactor = 2, FresnelRoughness = 4 };

// PbrValidity.isph.
X2_HD inline Color pbrLerp(Color a, Color b, float t) { return a + (b - a) * t; }
X2_HD inline Color pbrValid() { return Color{0.0f, 1.0f, 0.0f}; }
X2_HD inline Color pbrInvalid() { return Color{1.0f, 0.0f, 0.0f}; }
X2_HD inline Color albedoPbrValidity(Color albedo) {
    const float value = fmaxf(fmaxf(albedo.x, albedo.y), albedo.z);
    const float lo = 0.031896f, hi = 0.871367f;
    if (value > lo && value < hi) return pbrValid();
    if (value < lo) return pbrLerp(pbrInvalid(), pbrValid(), value / lo);
    return pbrLerp(pbrValid(), pbrInvalid(), shade::saturate((value - hi) / (1.0f - hi)));
}
X2_HD inline Color dielectricPbrValidity(float etaT) {
    const float lowBegin = 1.3f, lowEnd = 1.33f, highBegin = 1.576f, highEnd = 1.788f;
    if (etaT < lowBegin || etaT > highEnd) return pbrInvalid();
    if (etaT > lowEnd && etaT < highBegin) return pbrValid();
    if (etaT > highBegin) return pbrLerp(pbrValid(), pbrInvalid(), (etaT - highBegin) / (highEnd - highBegin));
    return pbrLerp(pbrInvalid(), pbrValid(), (etaT - lowBegin) / (lowEnd - lowBegin));
}
X2_HD inline Color conductorPbrValidity(Color reflectivity) {
    const float value = fmaxf(fmaxf(reflectivity.x, reflectivity.y), reflectivity.z), invalid = 0.456411f, valid = 0.533276f;
    if (value < invalid || value > 1.0f) return pbrInvalid();
    if (value > valid) return pbrValid();
    return pbrLerp(pbrInvalid(), pbrValid(), (value - invalid) / (valid - invalid));
}

// A Fresnel's property flags (Fresnel_init's) and Fresnel_getProperty, walked without recursion (OptiX rejects a
// recursive call graph) as shade::fresnelChain: the one-minus wrappers down to their base, and a multiple
// transmission's members each such a chain.
X2_HD inline U32 fresnelBaseFlags(U32 kind) {
    switch (kind) {
    case shade::FresnelSchlick:
    case shade::FresnelDielectric:
    case shade::FresnelLayeredDielectric: return FresnelColor | FresnelFactor;
    case shade::FresnelConductor: return FresnelColor;
    case shade::FresnelOneMinusVelvet: return FresnelRoughness;
    default: return 0;
    }
}
X2_HD inline U32 fresnelChainFlags(const shade::FresnelPool& pool, U32 index, U32& base) {
    U32 flags = 0;
    for (int n = 0; index < pool.count && shade::fresnelWraps(pool.items[index].kind) && n < 9; ++n) {
        if (pool.items[index].kind != shade::FresnelOneMinus) flags |= FresnelRoughness;
        index = pool.items[index].top;
    }
    base = index;
    return index < pool.count ? flags | fresnelBaseFlags(pool.items[index].kind) : flags;
}
X2_HD inline U32 fresnelFlags(const shade::FresnelPool& pool, U32 index) {
    U32 base = ~0u, member = ~0u;
    U32 flags = fresnelChainFlags(pool, index, base);
    if (base < pool.count && pool.items[base].kind == shade::FresnelMultipleTransmission) {
        const shade::Fresnel& f = pool.items[base];
        for (U32 i = 0; i < f.count && i < shade::MaxMultipleFresnels; ++i) flags |= fresnelChainFlags(pool, f.list[i], member);
    }
    return flags;
}
// A base Fresnel's property (an unhandled property writes nothing, as MoonRay's).
X2_HD inline void fresnelBaseProperty(const shade::Fresnel& f, U32 property, float* dest) {
    switch (f.kind) {
    case shade::FresnelSchlick:
        if (property == FresnelColor) {
            dest[0] = f.a.x * f.weight;
            dest[1] = f.a.y * f.weight;
            dest[2] = f.a.z * f.weight;
        } else if (property == FresnelFactor) {
            dest[0] = f.f0;
        }
        break;
    case shade::FresnelDielectric:
    case shade::FresnelLayeredDielectric:
        if (property == FresnelColor) dest[0] = dest[1] = dest[2] = f.weight;
        break;
    case shade::FresnelConductor:
        if (property == FresnelColor) {
            dest[0] = (1.0f - f.b.x) * f.weight;
            dest[1] = (1.0f - f.b.y) * f.weight;
            dest[2] = (1.0f - f.b.z) * f.weight;
        }
        break;
    case shade::FresnelOneMinusVelvet:
        if (property == FresnelRoughness) dest[0] = dest[1] = f.f0;
        break;
    default: break;
    }
}
// The wrappers: a one-minus inverts its top's colour; a rough one-minus answers roughness itself (sqrt of its
// roughness), else as the plain one-minus. The base's property comes from `base`.
template <class Base>
X2_HD inline void fresnelChainProperty(const shade::FresnelPool& pool, U32 index, U32 property, float* dest, const Base& base) {
    U32 n = 0;
    while (index < pool.count && shade::fresnelWraps(pool.items[index].kind) && n < 9) {
        const shade::Fresnel& w = pool.items[index];
        if (w.kind != shade::FresnelOneMinus && property == FresnelRoughness) {
            dest[0] = dest[1] = sqrtf(w.f0);
            return;
        }
        ++n;
        index = w.top;
    }
    if (index < pool.count) base(pool.items[index], index);
    if (property == FresnelColor)
        for (; n; --n)
            for (int c = 0; c < 3; ++c) dest[c] = 1.0f - dest[c];
}
X2_HD inline void fresnelProperty(const shade::FresnelPool& pool, U32 index, U32 property, float* dest) {
    fresnelChainProperty(pool, index, property, dest, [&](const shade::Fresnel& f, U32 at) {
        if (f.kind != shade::FresnelMultipleTransmission) {
            fresnelBaseProperty(f, property, dest);
            return;
        }
        // MultipleTransmissionFresnel_compute*Property, its average taken (and written) inside its loop as MoonRay's is.
        const U32 n = f.count < shade::MaxMultipleFresnels ? f.count : shade::MaxMultipleFresnels;
        const U32 flags = fresnelFlags(pool, at);
        const float inv = n ? 1.0f / float(n) : 0.0f;
        float avg[3] = {0, 0, 0};
        for (U32 i = 0; i < n; ++i) {
            if (flags & property) {
                float tmp[3] = {0, 0, 0};
                fresnelChainProperty(pool, f.list[i], property, tmp,
                                     [&](const shade::Fresnel& g, U32) { fresnelBaseProperty(g, property, tmp); });
                for (int c = 0; c < 3; ++c) avg[c] += tmp[c];
            }
            if (property == FresnelFactor) {
                avg[0] /= float(n);
                dest[0] = avg[0];
            } else {
                for (int c = 0; c < 3; ++c) avg[c] *= inv;
                dest[0] = avg[0];
                dest[1] = avg[1];
                if (property == FresnelColor) dest[2] = avg[2];
            }
        }
    });
}
// Fresnel_computePbrValidity.
X2_HD inline Color fresnelPbrValidity(const shade::FresnelPool& pool, U32 index) {
    if (index >= pool.count) return Color{0, 0, 0};
    const shade::Fresnel& f = pool.items[index];
    switch (f.kind) {
    case shade::FresnelDielectric:
    case shade::FresnelLayeredDielectric: return dielectricPbrValidity(f.etaT);
    case shade::FresnelConductor: return conductorPbrValidity(shade::fresnelEval(pool, index, 1.0f));
    default: return Color{0, 0, 0};
    }
}

// The lobe a wrapper's properties come from (UnderBsdfLobe_getProperty, IridescenceBsdfLobe_getProperty).
X2_HD inline const Lobe& propertyLobe(const Bsdf& b, const Lobe& l) {
    const Lobe* p = &l;
    for (int i = 0; i < 4 && p->child != shade::NoIndex &&
                    (p->kind == shade::KindUnder || p->kind == shade::KindUnderClearcoat || p->kind == shade::KindUnderClearcoatTransmission ||
                     p->kind == shade::KindIridescence);
         ++i)
        p = &b.records[p->child];
    return *p;
}
// A lobe's property flags (each lobe's BsdfLobe_init; COLOR always, BsdfLobe_init adds it).
X2_HD inline U32 lobePropertyFlags(const Bsdf& b, const Lobe& l0) {
    // Under lobes take their child's flags; iridescence keeps its own.
    const Lobe& l = (l0.kind == shade::KindIridescence) ? l0 : propertyLobe(b, l0);
    U32 f = 0;
    switch (l.kind) {
    case shade::KindLambert:
    case shade::KindOrenNayar:
    case shade::KindFlatDiffuse:
    case shade::KindCookTorrance:
    case shade::KindGGX:
    case shade::KindStochasticFlakes: f = PropNormal | PropRoughness | PropPbrValidity; break;
    case shade::KindAnisoCookTorrance:
    case shade::KindBerryCookTorrance:
    case shade::KindGlitterGGX:
    case shade::KindTransmissionCookTorrance:
    case shade::KindMirrorReflection:
    case shade::KindMirrorTransmission:
    case shade::KindMirrorRetroreflection:
    case shade::KindRetroreflection:
    case shade::KindFabric:
    case shade::KindIridescence:
    case shade::KindToonSpecular:
    case shade::KindHairToonSpecular: f = PropNormal | PropRoughness; break;
    case shade::KindVelvet: f = PropNormal | PropRoughness; break;
    case shade::KindEyeCaustic: f = PropNormal | PropEyeMask; break;
    case shade::KindToon: f = PropNormal | PropPbrValidity; break;
    case shade::KindHairOneSampler: f = PropNormal | PropRoughness; break;
    case shade::KindHairR:
    case shade::KindHairTRT:
    case shade::KindHairTT:
    case shade::KindHairTRRT:
    case shade::KindHairDiffuse: f = PropNormal | PropRoughness | PropPbrValidity; break;
    default: break;
    }
    return f | PropColor;
}
X2_HD inline V3 renderVector(const float* worldToRender, V3 v) { return worldToRender ? shade::xformVector(worldToRender, v) : v; }
X2_HD inline Color scaleAndFresnel1(const Bsdf& b, const Lobe& l) { return shade::scaleAndFresnel(b, l, 1.0f); }
// BsdfLobe_getProperty: the lobe's own property, else (colour) its scale and Fresnel at normal incidence. False when
// neither handles it (MoonRay then writes nothing).
X2_HD inline bool lobeProperty(const Bsdf& b, const Lobe& l0, U32 property, float* d, const float* worldToRender) {
    const Lobe& l = propertyLobe(b, l0);
    auto put3 = [&](V3 v) {
        d[0] = v.x;
        d[1] = v.y;
        d[2] = v.z;
    };
    auto putN = [&](V3 n) { put3(renderVector(worldToRender, n)); };
    auto put2 = [&](float u, float v) {
        d[0] = u;
        d[1] = v;
    };
    const shade::HairRecord* hair = l.hair.record < b.hairCount ? &b.hairs[l.hair.record] : nullptr;
    switch (l.kind) {
    case shade::KindLambert:
    case shade::KindOrenNayar:
    case shade::KindFlatDiffuse:
    case shade::KindToon: {
        const Color albedo = l.kind == shade::KindToon ? l.toon.albedo : l.diffuse.albedo;
        switch (property) {
        case PropRoughness: put2(1.0f, 1.0f); return true;
        case PropNormal: putN(l.frame.z); return true;
        case PropPbrValidity: put3(albedoPbrValidity(albedo)); return true;
        case PropColor: put3(albedo * scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    }
    case shade::KindCookTorrance:
    case shade::KindGGX:
    case shade::KindBerryCookTorrance:
    case shade::KindGlitterGGX:
        switch (property) {
        case PropRoughness: put2(l.ct.inputRoughness, l.ct.inputRoughness); return true;
        case PropPbrValidity: put3(fresnelPbrValidity(b.fresnels, l.fresnel)); return true;
        case PropNormal: putN(l.kind == shade::KindGlitterGGX ? l.ct.flakeNormal : l.frame.z); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindAnisoCookTorrance:
        switch (property) {
        case PropRoughness: put2(l.ct.inputRoughness, l.ct.inputRoughnessV); return true;
        case PropNormal: putN(l.frame.z); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindTransmissionCookTorrance:
        switch (property) {
        case PropRoughness: put2(l.ct.inputRoughness, l.ct.inputRoughness); return true;
        case PropNormal: putN(l.frame.z); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindMirrorReflection:
    case shade::KindMirrorTransmission:
    case shade::KindMirrorRetroreflection:
        switch (property) {
        case PropRoughness: put2(0.0f, 0.0f); return true;
        case PropNormal: putN(l.frame.z); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindRetroreflection:
        switch (property) {
        case PropRoughness: put2(l.retro.inputRoughness, l.retro.inputRoughness); return true;
        case PropNormal: putN(l.frame.z); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindStochasticFlakes:
        switch (property) {
        case PropRoughness: put2(l.flakes.randomness, l.flakes.randomness); return true;
        case PropNormal: putN(l.frame.z); return true;
        case PropPbrValidity: put3(fresnelPbrValidity(b.fresnels, l.fresnel)); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindEyeCaustic:
        switch (property) {
        case PropNormal: putN(l.frame.z); return true;
        case PropEyeMask: put3(l.eye.eyeMask); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindFabric:
    case shade::KindVelvet:
        switch (property) {
        case PropColor: put3(l.fabric.color); return true;
        case PropRoughness: put2(l.fabric.roughness, l.fabric.roughness); return true;
        case PropNormal: putN(l.frame.z); return true;
        default: return false;
        }
    case shade::KindToonSpecular:
        switch (property) {
        case PropNormal: putN(l.frame.z); return true;
        case PropColor: put3(scaleAndFresnel1(b, l)); return true;
        default: return false;
        }
    case shade::KindHairToonSpecular:
        if (property == PropColor) {
            put3(scaleAndFresnel1(b, l));
            return true;
        }
        return false;
    case shade::KindHairOneSampler:
    case shade::KindHairR:
    case shade::KindHairTRT:
    case shade::KindHairTT:
    case shade::KindHairTRRT:
        switch (property) {
        case PropColor:
            if (hair) put3(hair->hairColor);
            return true;
        case PropRoughness: put2(l.hair.roughU, l.hair.roughV); return true;
        case PropNormal:
            if (hair) putN(hair->hairDir);
            return true;
        case PropPbrValidity: put3(fresnelPbrValidity(b.fresnels, l.fresnel)); return true;
        default: return false;
        }
    case shade::KindHairDiffuse:
        switch (property) {
        case PropColor: put3(l.hair.refl); return true;
        case PropRoughness: put2(1.0f, 1.0f); return true;
        case PropNormal: putN(l.hair.dir); return true;
        case PropPbrValidity: put3(Color{0.0f, 1.0f, 0.0f}); return true;
        default: return false;
        }
    default:
        if (property == PropColor) {
            put3(scaleAndFresnel1(b, l));
            return true;
        }
        return false;
    }
}

// The subsurface's properties (Dipole, NormalizedDiffusion, VolumeSubsurface getProperty): colour, radius, validity.
enum SubsurfaceProperty : U32 { SubColor = 1, SubRadius = 2, SubPbrValidity = 4 };
X2_HD inline U32 subsurfaceFlags(const shade::BssrdfRecord& s) {
    if (s.type == shade::BssrdfNone) return 0;
    return SubColor | SubRadius | SubPbrValidity;
}
X2_HD inline void subsurfaceProperty(const shade::BssrdfRecord& s, U32 property, float* d) {
    Color c{0, 0, 0};
    if (s.type == shade::BssrdfDipole) {
        if (property == SubColor) c = s.diffuseReflectance;
        else if (property == SubRadius) c = Color{1.0f / s.sigmaTr.x, 1.0f / s.sigmaTr.y, 1.0f / s.sigmaTr.z};
        else c = albedoPbrValidity(s.albedo);
    } else if (s.type == shade::BssrdfNormalizedDiffusion) {
        if (property == SubColor) c = s.albedo;
        else if (property == SubRadius) c = s.dmfp;
        else c = albedoPbrValidity(s.albedo);
    } else if (s.type == shade::BssrdfRandomWalk) {
        if (property == SubColor) c = s.rwColor;
        else if (property == SubRadius) c = s.rwRadius;
        else c = albedoPbrValidity(s.rwColor);
    }
    d[0] = c.x;
    d[1] = c.y;
    d[2] = c.z;
}

// labelMatch: an entry's list of label indices (empty: any) holds this label.
X2_HD inline bool labelMatch(const Tables& t, int label, U32 first, U32 count) {
    if (!count) return true;
    for (U32 i = 0; i < count; ++i)
        if (t.labelLists[first + i] == label) return true;
    return false;
}

// What a material AOV is computed from at a hit.
struct MaterialHit {
    const Bsdf* bsdf;
    const shade::State* st;
    int geomLabel;             // the geometry's material AOV label (-1: none)
    const float* albedo;       // the BSDF samples' albedo of each top lobe (3 floats a lobe), null without samples
    const unsigned char* albedoLobes;  // each top lobe's validity for the albedo (it had samples drawn)
    Color ssAov;               // the subsurface's material AOV albedo
    const float* worldToRender;
    float pixelWeight;         // the path's AOV pixel weight
    bool primary;              // a camera ray's hit (ray depth 0)
    int lpe;                   // the path's state
    // State and primitive attribute values for material AOVs of them (aov_state.h fills them).
    const float* stateValues;  // indexed by Schema - StateP, 3 floats each
    const float* primValues;   // indexed by Tables::prims, 3 floats each, NaN: not provided
};

// The material AOVs at a hit, into the sample's array (aovSetMaterialAovs through MaterialAovs::computeVector).
X2_HD inline void materialAovs(const Tables& t, float* aovs, float* depths, const MaterialHit& h, float depth) {
    const Bsdf& b = *h.bsdf;
    const int geomLabel = h.geomLabel;
    const int materialLabel = shade::labelMaterialAovId(b.materialLabels);
    for (U32 ei = 0; ei < t.count; ++ei) {
        const Entry& e = t.entries[ei];
        if (e.type != TypeMaterial) continue;
        const MaterialAov& m = t.materials[e.material];
        // An LPE: only where the 'M:' event leads somewhere; otherwise secondary rays only when asked.
        if (m.lpe != None) {
            if (lpeNext(t, h.lpe, LpeMaterial, m.lpeLabel) < 0) continue;
        } else if (!m.secondary && !h.primary) {
            continue;
        }
        const float w = e.filter == FilterAvg ? h.pixelWeight : 1.0f;
        float v[3] = {0, 0, 0};
        const bool labels = labelMatch(t, geomLabel, m.geomLabels, m.geomLabelCount) && labelMatch(t, materialLabel, m.materialLabels, m.materialLabelCount);
        auto lobeMatches = [&](const Lobe& l) {
            return shade::matchesFlags(l.type, m.lobeFlags) && labelMatch(t, shade::labelMaterialAovId(l.label), m.labels, m.labelCount);
        };
        const bool subsurface = b.bssrdf.type != shade::BssrdfNone;
        const bool subLabel = subsurface && labelMatch(t, shade::labelMaterialAovId(b.bssrdf.label), m.labels, m.labelCount);
        switch (m.property) {
        case PropertyAlbedo: {
            Color r{0, 0, 0};
            U32 n = 0;
            if (labels) {
                if (m.lobeFlags && h.albedo) {
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!h.albedoLobes[k] || !lobeMatches(l)) continue;
                        ++n;
                        r = r + Color{h.albedo[3 * k], h.albedo[3 * k + 1], h.albedo[3 * k + 2]};
                    }
                    r = r * w;
                }
                if (m.subsurface && subLabel) {
                    ++n;
                    r = r + h.ssAov;
                }
            }
            if (n > 1) r = r * (1.0f / float(n));
            v[0] = r.x;
            v[1] = r.y;
            v[2] = r.z;
            break;
        }
        case PropertyColor: {
            Color r{0, 0, 0};
            bool lobeContributed = false, subContributed = false;
            if (labels) {
                if (m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!lobeMatches(l)) continue;
                        lobeContributed = true;
                        float c[3] = {0, 0, 0};
                        if (lobeProperty(b, l, PropColor, c, h.worldToRender)) r = r + Color{c[0], c[1], c[2]};
                    }
                if (m.fresnel) {
                    // computeFresnelColor: each matching lobe's Fresnel colour, and the subsurface's transmission Fresnel's.
                    r = Color{0, 0, 0};
                    if (m.lobeFlags)
                        for (U32 k = 0; k < b.topCount; ++k) {
                            const Lobe& l = shade::topLobe(b, k);
                            if (!lobeMatches(l) || l.fresnel == shade::NoIndex) continue;
                            if (fresnelFlags(b.fresnels, l.fresnel) & FresnelColor) {
                                float c[3] = {0, 0, 0};
                                fresnelProperty(b.fresnels, l.fresnel, FresnelColor, c);
                                r = r + Color{c[0], c[1], c[2]};
                            }
                        }
                    if (m.subsurface && subLabel && b.bssrdf.fresnel != shade::NoIndex &&
                        (fresnelFlags(b.fresnels, b.bssrdf.fresnel) & FresnelColor)) {
                        float c[3] = {0, 0, 0};
                        fresnelProperty(b.fresnels, b.bssrdf.fresnel, FresnelColor, c);
                        r = r + Color{c[0], c[1], c[2]};
                    }
                    r = r * w;
                    v[0] = r.x;
                    v[1] = r.y;
                    v[2] = r.z;
                    break;
                }
                if (m.subsurface && subLabel) {
                    subContributed = true;
                    float c[3];
                    subsurfaceProperty(b.bssrdf, SubColor, c);
                    r = r + Color{c[0], c[1], c[2]};
                }
                r = r * w;
            }
            if (lobeContributed && subContributed) r = r * 0.5f;
            v[0] = r.x;
            v[1] = r.y;
            v[2] = r.z;
            break;
        }
        case PropertyEmission:
            if (labels && !b.earlyTermination) {
                v[0] = b.selfEmission.x * w;
                v[1] = b.selfEmission.y * w;
                v[2] = b.selfEmission.z * w;
            }
            break;
        case PropertyMatte: {
            float r = 0.0f;
            if (labels) {
                if (m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k)
                        if (lobeMatches(shade::topLobe(b, k))) {
                            r = w;
                            break;
                        }
                if (r == 0.0f && m.subsurface && subLabel) r = w;
                if (!b.topCount && !subsurface && m.lobeFlags == U32(shade::AllLobeTypes)) r = w;
            }
            v[0] = r;
            break;
        }
        case PropertyRoughness: {
            float r[2] = {0, 0};
            int matching = 0;
            if (labels) {
                if (m.fresnel) {
                    if (m.lobeFlags)
                        for (U32 k = 0; k < b.topCount; ++k) {
                            const Lobe& l = shade::topLobe(b, k);
                            if (!lobeMatches(l) || l.fresnel == shade::NoIndex) continue;
                            if (fresnelFlags(b.fresnels, l.fresnel) & FresnelRoughness) {
                                float c[3] = {0, 0, 0};
                                fresnelProperty(b.fresnels, l.fresnel, FresnelRoughness, c);
                                r[0] += c[0];
                                r[1] += c[1];
                                ++matching;
                            }
                        }
                    if (m.subsurface && subLabel && b.bssrdf.fresnel != shade::NoIndex &&
                        (fresnelFlags(b.fresnels, b.bssrdf.fresnel) & FresnelRoughness)) {
                        float c[3] = {0, 0, 0};
                        fresnelProperty(b.fresnels, b.bssrdf.fresnel, FresnelRoughness, c);
                        r[0] += c[0];
                        r[1] += c[1];
                        ++matching;
                    }
                } else if (m.lobeFlags) {
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!lobeMatches(l) || !(lobePropertyFlags(b, l) & PropRoughness)) continue;
                        float c[3] = {0, 0, 0};
                        lobeProperty(b, l, PropRoughness, c, h.worldToRender);
                        r[0] += c[0];
                        r[1] += c[1];
                        ++matching;
                    }
                }
                if (matching) {
                    r[0] *= 1.0f / float(matching);
                    r[1] *= 1.0f / float(matching);
                }
                r[0] *= w;
                r[1] *= w;
            }
            v[0] = r[0];
            v[1] = r[1];
            break;
        }
        case PropertyNormal: {
            V3 r{0, 0, 0};
            int matching = 0;
            if (labels) {
                if (m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!lobeMatches(l) || !(lobePropertyFlags(b, l) & PropNormal)) continue;
                        float c[3] = {0, 0, 0};
                        lobeProperty(b, l, PropNormal, c, h.worldToRender);
                        r = surface::add(r, V3{c[0], c[1], c[2]});
                        ++matching;
                    }
                if (m.subsurface && subLabel) {
                    r = surface::add(r, renderVector(h.worldToRender, b.bssrdf.N));
                    ++matching;
                }
                if (matching) r = surface::mul(r, 1.0f / float(matching));
                r = surface::mul(r, w);
            }
            v[0] = r.x;
            v[1] = r.y;
            v[2] = r.z;
            break;
        }
        case PropertyRadius: {
            Color r{0, 0, 0};
            if (labels) {
                if (subLabel) subsurfaceProperty(b.bssrdf, SubRadius, &r.x);
                r = r * w;
            }
            v[0] = r.x;
            v[1] = r.y;
            v[2] = r.z;
            break;
        }
        case PropertyFactor: {
            float r = 0.0f;
            int s = 0;
            if (labels) {
                if (m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!lobeMatches(l) || l.fresnel == shade::NoIndex) continue;
                        if (fresnelFlags(b.fresnels, l.fresnel) & FresnelFactor) {
                            float f = 0.0f;
                            fresnelProperty(b.fresnels, l.fresnel, FresnelFactor, &f);
                            r += f;
                            ++s;
                        }
                    }
                if (m.subsurface && subLabel && b.bssrdf.fresnel != shade::NoIndex &&
                    (fresnelFlags(b.fresnels, b.bssrdf.fresnel) & FresnelFactor)) {
                    float f = 0.0f;
                    fresnelProperty(b.fresnels, b.bssrdf.fresnel, FresnelFactor, &f);
                    r += f;
                    ++s;
                }
                if (s > 0) r = r / float(s);
                r *= w;
            }
            v[0] = r;
            break;
        }
        case PropertyPbrValidity: {
            Color r{0, 0, 0};
            if (labels) {
                if (m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!lobeMatches(l) || !(lobePropertyFlags(b, l) & PropPbrValidity)) continue;
                        float c[3] = {0, 0, 0};
                        lobeProperty(b, l, PropPbrValidity, c, h.worldToRender);
                        r = r + Color{c[0], c[1], c[2]};
                    }
                if (m.subsurface && subLabel) {
                    float c[3];
                    subsurfaceProperty(b.bssrdf, SubPbrValidity, c);
                    r = r + Color{c[0], c[1], c[2]};
                }
                r = r * w;
            }
            v[0] = r.x;
            v[1] = r.y;
            v[2] = r.z;
            break;
        }
        case PropertyEyeMask: {
            Color r{0, 0, 0};
            if (labels) {
                if (m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k) {
                        const Lobe& l = shade::topLobe(b, k);
                        if (!lobeMatches(l) || !(lobePropertyFlags(b, l) & PropEyeMask)) continue;
                        float c[3] = {0, 0, 0};
                        lobeProperty(b, l, PropEyeMask, c, h.worldToRender);
                        r = r + Color{c[0], c[1], c[2]};
                    }
                r = r * w;
            }
            v[0] = r.x;
            v[1] = r.y;
            v[2] = r.z;
            break;
        }
        case PropertyState:
        case PropertyPrim: {
            // computeStateAov, computePrimitiveAttribute: the value where the selector matches, else the miss value.
            bool matched = false;
            if (labels) {
                const bool selectorIsDefault = m.lobeFlags == U32(shade::AllLobeTypes) && m.subsurface;
                if (selectorIsDefault && !b.topCount && !subsurface) matched = !b.earlyTermination;
                if (!matched && m.lobeFlags)
                    for (U32 k = 0; k < b.topCount; ++k)
                        if (lobeMatches(shade::topLobe(b, k))) {
                            matched = true;
                            break;
                        }
                if (!matched && m.subsurface && subLabel) matched = true;
            }
            const float miss = e.filter == FilterMin ? infinity() : e.filter == FilterMax ? -infinity() : 0.0f;
            if (matched) {
                const float* src = m.property == PropertyState ? h.stateValues + 3 * (e.state - StateP) : h.primValues + 3 * e.prim;
                if (m.property == PropertyPrim && !(src[0] == src[0])) {
                    v[0] = v[1] = v[2] = miss;
                } else {
                    for (U32 c = 0; c < e.channels; ++c) v[c] = src[c] * w;
                }
            } else {
                v[0] = v[1] = v[2] = miss;
            }
            break;
        }
        default: break;
        }
        // The value as MoonRay queues it (only non-zero for the averages and sums, only finite for the rest).
        put(e, aovs, depths, v, depth);
    }
}

}  // namespace xpu2::interactive::aov
