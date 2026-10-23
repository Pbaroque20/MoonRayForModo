// Private XPU2 shading library, shared CPU/CUDA: the DwaBase combinators
// (DwaLayer, DwaMix, DwaTwoSided, DwaSwitch, DwaColorCorrect, DwaAdjust) as a
// tree of nodes the devices walk without recursion (OptiX has none), and
// DWABASE_blendParameters (moonshine lib/material/dwabase Blending.ispc and the
// combinator DSOs). Derived from MoonRay Apache-2.0, Copyright 2023-2024
// DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "shade_dwabase.h"
#include "shade_maps.h"
namespace xpu2 { namespace interactive { namespace shade {

enum BlendColorSpace : U32 { BlendRgb = 0, BlendHsv, BlendHsl };
X2_HD inline Color colorSpaceLerp(Color c0, Color c1, float mask, U32 space) {
    switch (space) {
    case BlendHsv: return hsvToRgb(lerp(rgbToHsv(c0), rgbToHsv(c1), mask));
    case BlendHsl: return hslToRgb(lerp(rgbToHsl(c0), rgbToHsl(c1), mask));
    default: return lerp(c0, c1, mask);
    }
}
X2_HD inline V3 lerpV(V3 a, V3 b, float t) { return a * (1.0f - t) + b * t; }

//----------------------------------------------------------------------------
// Blending.ispc: each function sets the fields of one feature; where only one
// material uses a feature, its settings are taken as they are.
X2_HD inline void blendFuzz(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    p.fuzz = lerpf(p0.fuzz, p1.fuzz, mask);
    if (isZero(p.fuzz)) return;
    if (!isZero(p0.fuzz) && !isZero(p1.fuzz)) {
        p.fuzzRoughness = lerpf(p0.fuzzRoughness, p1.fuzzRoughness, mask);
        p.fuzzAlbedo = colorSpaceLerp(p0.fuzzAlbedo, p1.fuzzAlbedo, mask, cs);
        p.fuzzUseAbsorbingFibers = p0.fuzzUseAbsorbingFibers || p1.fuzzUseAbsorbingFibers;
        p.fuzzNormal = normalize(lerpV(p0.fuzzNormal, p1.fuzzNormal, mask));
    } else {
        const DwaParams& s = !isZero(p1.fuzz) ? p1 : p0;
        p.fuzzRoughness = s.fuzzRoughness;
        p.fuzzUseAbsorbingFibers = s.fuzzUseAbsorbingFibers;
        p.fuzzAlbedo = s.fuzzAlbedo;
        p.fuzzNormal = s.fuzzNormal;
    }
}
X2_HD inline void copyOuterSpecular(const DwaParams& s, DwaParams& d) {
    d.outerSpecularRefractiveIndex = s.outerSpecularRefractiveIndex;
    d.outerSpecularRoughness = s.outerSpecularRoughness;
    d.outerSpecularThickness = s.outerSpecularThickness;
    d.outerSpecularAttenuationColor = s.outerSpecularAttenuationColor;
    d.outerSpecularNormal = s.outerSpecularNormal;
    d.outerSpecularNormalLength = s.outerSpecularNormalLength;
}
X2_HD inline void blendOuterSpecular(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    p.outerSpecular = lerpf(p0.outerSpecular, p1.outerSpecular, mask);
    if (isZero(p.outerSpecular)) return;
    if (!isZero(p0.outerSpecular) && !isZero(p1.outerSpecular)) {
        p.outerSpecularRefractiveIndex = lerpf(p0.outerSpecularRefractiveIndex, p1.outerSpecularRefractiveIndex, mask);
        p.outerSpecularRoughness = lerpf(p0.outerSpecularRoughness, p1.outerSpecularRoughness, mask);
        p.outerSpecularThickness = lerpf(p0.outerSpecularThickness, p1.outerSpecularThickness, mask);
        p.outerSpecularAttenuationColor = colorSpaceLerp(p0.outerSpecularAttenuationColor, p1.outerSpecularAttenuationColor, mask, cs);
        p.outerSpecularNormal = normalize(lerpV(p0.outerSpecularNormal, p1.outerSpecularNormal, mask));
        p.outerSpecularNormalLength = lerpf(p0.outerSpecularNormalLength, p1.outerSpecularNormalLength, mask);
    } else if (!isZero(p1.outerSpecular)) {
        copyOuterSpecular(p1, p);
    } else {
        copyOuterSpecular(p0, p);
    }
}
X2_HD inline void blendCommonSpecular(float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    p.specular = lerpf(p0.specular, p1.specular, mask);
    if (isZero(p.specular)) return;
    if (!isZero(p0.specular) && !isZero(p1.specular)) {
        p.roughness = lerpf(p0.roughness, p1.roughness, mask);
        if (!isZero(p0.anisotropy) && !isZero(p1.anisotropy)) {
            p.anisotropy = lerpf(p0.anisotropy, p1.anisotropy, mask);
            const float x = lerpf(p0.shadingTangent[0], p1.shadingTangent[0], mask),
                        y = lerpf(p0.shadingTangent[1], p1.shadingTangent[1], mask);
            const float l = sqrtf(x * x + y * y);
            p.shadingTangent[0] = x / l;
            p.shadingTangent[1] = y / l;
        } else if (!isZero(p1.anisotropy)) {
            p.anisotropy = p1.anisotropy * mask;
            p.shadingTangent[0] = p1.shadingTangent[0];
            p.shadingTangent[1] = p1.shadingTangent[1];
        } else {
            p.anisotropy = p0.anisotropy * (1.0f - mask);
            p.shadingTangent[0] = p0.shadingTangent[0];
            p.shadingTangent[1] = p0.shadingTangent[1];
        }
    } else {
        const DwaParams& s = !isZero(p1.specular) ? p1 : p0;
        p.roughness = s.roughness;
        p.anisotropy = s.anisotropy;
        p.shadingTangent[0] = s.shadingTangent[0];
        p.shadingTangent[1] = s.shadingTangent[1];
    }
}
X2_HD inline void copyIridescence(const IridescenceParameters& s, IridescenceParameters& d) {
    d.applyTo = s.applyTo;
    d.colorControl = s.colorControl;
    d.primaryColor = s.primaryColor;
    d.secondaryColor = s.secondaryColor;
    d.flipHueDirection = s.flipHueDirection;
    d.thickness = s.thickness;
    d.exponent = s.exponent;
    d.at0 = s.at0;
    d.at90 = s.at90;
    d.rampInterpolationMode = s.rampInterpolationMode;
    d.rampNumPoints = s.rampNumPoints;
    for (U32 i = 0; i < s.rampNumPoints; ++i) {
        d.rampPositions[i] = s.rampPositions[i];
        d.rampColors[i] = s.rampColors[i];
        d.rampInterpolators[i] = s.rampInterpolators[i];
    }
}
X2_CALL void blendIridescence(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    if (isZero(p.specular)) return;
    IridescenceParameters& i = p.iridescence;
    const IridescenceParameters &i0 = p0.iridescence, &i1 = p1.iridescence;
    i.iridescence = lerpf(i0.iridescence, i1.iridescence, mask);
    if (isZero(i.iridescence)) return;
    if (!isZero(i0.iridescence) && !isZero(i1.iridescence)) {
        i.applyTo = i0.applyTo != i1.applyTo ? U32(IridescenceOuterSpecular) : i1.applyTo;   // outer specular wins
        i.colorControl = i0.colorControl != i1.colorControl ? 1u : i1.colorControl;           // the ramp wins
        i.primaryColor = colorSpaceLerp(i0.primaryColor, i1.primaryColor, mask, cs);
        i.secondaryColor = colorSpaceLerp(i0.secondaryColor, i1.secondaryColor, mask, cs);
        i.flipHueDirection = mask >= 0.5f ? i1.flipHueDirection : i0.flipHueDirection;
        i.thickness = lerpf(i0.thickness, i1.thickness, mask);
        i.exponent = lerpf(i0.exponent, i1.exponent, mask);
        i.at0 = lerpf(i0.at0, i1.at0, mask);
        i.at90 = lerpf(i0.at90, i1.at90, mask);
        i.rampInterpolationMode = i0.rampInterpolationMode != i1.rampInterpolationMode ? U32(RampHsv) : i1.rampInterpolationMode;
        i.rampNumPoints = i0.rampNumPoints > i1.rampNumPoints ? i0.rampNumPoints : i1.rampNumPoints;
        const U32 n = i0.rampNumPoints < i1.rampNumPoints ? i0.rampNumPoints : i1.rampNumPoints;
        for (U32 k = 0; k < n; ++k) {
            i.rampPositions[k] = lerpf(i0.rampPositions[k], i1.rampPositions[k], mask);
            i.rampColors[k] = lerp(i0.rampColors[k], i1.rampColors[k], mask);
            i.rampInterpolators[k] = i1.rampInterpolators[k];
        }
        const IridescenceParameters& rest = i0.rampNumPoints > i1.rampNumPoints ? i0 : i1;
        for (U32 k = n; k < i.rampNumPoints; ++k) {
            i.rampPositions[k] = rest.rampPositions[k];
            i.rampColors[k] = rest.rampColors[k];
            i.rampInterpolators[k] = rest.rampInterpolators[k];
        }
    } else if (!isZero(i0.iridescence)) {
        copyIridescence(i0, i);
    } else {
        copyIridescence(i1, i);
    }
}
X2_HD inline void blendMetallic(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    if (isZero(p.specular)) return;
    p.metallic = lerpf(p0.metallic, p1.metallic, mask);
    if (isZero(p.metallic)) return;
    if (!isZero(p0.metallic) && !isZero(p1.metallic)) {
        p.metallicColor = colorSpaceLerp(p0.metallicColor, p1.metallicColor, mask, cs);
        p.metallicEdgeColor = colorSpaceLerp(p0.metallicEdgeColor, p1.metallicEdgeColor, mask, cs);
    } else {
        const DwaParams& s = !isZero(p0.metallic) ? p0 : p1;
        p.metallicColor = s.metallicColor;
        p.metallicEdgeColor = s.metallicEdgeColor;
    }
}
X2_HD inline void copyFabric(const DwaParams& s, DwaParams& d) {
    d.warpColor = s.warpColor;
    d.warpRoughness = s.warpRoughness;
    d.fabricTangent = s.fabricTangent;
    d.weftColor = s.weftColor;
    d.weftRoughness = s.weftRoughness;
    d.warpThreadDirection = s.warpThreadDirection;
    d.warpThreadElevation = s.warpThreadElevation;
    d.warpThreadCoverage = s.warpThreadCoverage;
}
X2_HD inline void blendFabric(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    if (isOne(p.metallic)) return;
    p.fabricSpecular = lerpf(p0.fabricSpecular, p1.fabricSpecular, mask);
    if (isZero(p.fabricSpecular)) return;
    if (!isZero(p0.fabricSpecular) && !isZero(p1.fabricSpecular)) {
        p.warpColor = colorSpaceLerp(p0.warpColor, p1.warpColor, mask, cs);
        p.warpRoughness = lerpf(p0.warpRoughness, p1.warpRoughness, mask);
        p.fabricTangent = lerpV(p0.fabricTangent, p1.fabricTangent, mask);
        p.weftColor = colorSpaceLerp(p0.weftColor, p1.weftColor, mask, cs);
        p.weftRoughness = lerpf(p0.weftRoughness, p1.weftRoughness, mask);
        p.warpThreadDirection = normalize(lerpV(p0.warpThreadDirection, p1.warpThreadDirection, mask));
        p.warpThreadElevation = lerpf(p0.warpThreadElevation, p1.warpThreadElevation, mask);
        p.warpThreadCoverage = lerpf(p0.warpThreadCoverage, p1.warpThreadCoverage, mask);
    } else if (!isZero(p0.fabricSpecular)) {
        copyFabric(p0, p);
    } else {
        copyFabric(p1, p);
    }
}
X2_CALL void blendTransmission(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    if (isOne(p.metallic) || isZero(p.fabricAttenuation)) return;
    p.transmission = lerpf(p0.transmission, p1.transmission, mask);
    if (isZero(p.transmission)) return;
    if (!isZero(p0.transmission) && !isZero(p1.transmission))
        p.transmissionColor = colorSpaceLerp(p0.transmissionColor, p1.transmissionColor, mask, cs);
    else
        p.transmissionColor = !isZero(p0.transmission) ? p0.transmissionColor : p1.transmissionColor;

    if (p0.useIndependentTransmissionRefractiveIndex && p1.useIndependentTransmissionRefractiveIndex) {
        p.useIndependentTransmissionRefractiveIndex = true;
        p.independentTransmissionRefractiveIndex =
            lerpf(p0.independentTransmissionRefractiveIndex, p1.independentTransmissionRefractiveIndex, mask);
    } else if (p0.useIndependentTransmissionRefractiveIndex) {
        p.useIndependentTransmissionRefractiveIndex = true;
        p.independentTransmissionRefractiveIndex = isZero(p1.transmission)
                                                       ? p0.independentTransmissionRefractiveIndex
                                                       : lerpf(p0.independentTransmissionRefractiveIndex, p1.refractiveIndex, mask);
    } else if (p1.useIndependentTransmissionRefractiveIndex) {
        p.useIndependentTransmissionRefractiveIndex = true;
        p.independentTransmissionRefractiveIndex = isZero(p0.transmission)
                                                       ? p1.independentTransmissionRefractiveIndex
                                                       : lerpf(p0.refractiveIndex, p1.independentTransmissionRefractiveIndex, mask);
    } else {
        p.useIndependentTransmissionRefractiveIndex = false;
    }

    if (p0.useIndependentTransmissionRoughness && p1.useIndependentTransmissionRoughness) {
        p.useIndependentTransmissionRoughness = true;
        p.independentTransmissionRoughness = lerpf(p0.independentTransmissionRoughness, p1.independentTransmissionRoughness, mask);
    } else if (p0.useIndependentTransmissionRoughness) {
        p.useIndependentTransmissionRoughness = true;
        p.independentTransmissionRoughness =
            isZero(p1.transmission) ? p0.independentTransmissionRoughness : lerpf(p0.independentTransmissionRoughness, p1.roughness, mask);
    } else if (p1.useIndependentTransmissionRoughness) {
        p.useIndependentTransmissionRoughness = true;
        p.independentTransmissionRoughness =
            isZero(p0.transmission) ? p1.independentTransmissionRoughness : lerpf(p0.roughness, p1.independentTransmissionRoughness, mask);
    } else {
        p.useIndependentTransmissionRoughness = false;
    }

    if (!isZero(p0.dispersionAbbeNumber) && !isZero(p1.dispersionAbbeNumber))
        p.dispersionAbbeNumber = lerpf(p0.dispersionAbbeNumber, p1.dispersionAbbeNumber, mask);
    else if (!isZero(p0.dispersionAbbeNumber))
        p.dispersionAbbeNumber = p0.dispersionAbbeNumber;
    else if (!isZero(p1.dispersionAbbeNumber))
        p.dispersionAbbeNumber = p1.dispersionAbbeNumber;
}
X2_HD inline void copyToonRamp(const ToonDiffuseParameters& s, ToonDiffuseParameters& d) {
    d.rampNumPoints = s.rampNumPoints;
    for (U32 i = 0; i < s.rampNumPoints; ++i) {
        d.rampPositions[i] = s.rampPositions[i];
        d.rampColors[i] = s.rampColors[i];
        d.rampInterpolators[i] = s.rampInterpolators[i];
    }
    d.extendRamp = s.extendRamp;
}
X2_HD inline void copyToonOrenNayar(const ToonDiffuseParameters& s, ToonDiffuseParameters& d) {
    d.terminatorShift = s.terminatorShift;
    d.flatness = s.flatness;
    d.flatnessFalloff = s.flatnessFalloff;
}
X2_CALL void blendToonDiffuse(float mask, const ToonDiffuseParameters& t0, const ToonDiffuseParameters& t1, ToonDiffuseParameters& t) {
    t.toonDiffuse = lerpf(t0.toonDiffuse, t1.toonDiffuse, mask);
    if (isZero(t.toonDiffuse)) return;
    if (!isZero(t0.toonDiffuse) && !isZero(t1.toonDiffuse)) {
        t.model = t0.model != t1.model ? U32(ToonDiffuseRamp) : t1.model;
        t.normal = normalize(lerpV(t0.normal, t1.normal, mask));
        if (t0.model == ToonDiffuseOrenNayar && t1.model == ToonDiffuseRamp) {
            copyToonOrenNayar(t0, t);
        } else if (t0.model == ToonDiffuseRamp && t1.model == ToonDiffuseOrenNayar) {
            copyToonOrenNayar(t1, t);
        } else {
            t.terminatorShift = lerpf(t0.terminatorShift, t1.terminatorShift, mask);
            t.flatness = lerpf(t0.flatness, t1.flatness, mask);
            t.flatnessFalloff = lerpf(t0.flatnessFalloff, t1.flatnessFalloff, mask);
        }
        t.rampWeight = lerpf(t0.rampWeight, t1.rampWeight, mask);
        if (t0.model == ToonDiffuseOrenNayar && t1.model == ToonDiffuseRamp) {
            copyToonRamp(t1, t);
        } else if (t0.model == ToonDiffuseRamp && t1.model == ToonDiffuseOrenNayar) {
            copyToonRamp(t0, t);
        } else {
            t.rampNumPoints = t0.rampNumPoints > t1.rampNumPoints ? t0.rampNumPoints : t1.rampNumPoints;
            const U32 n = t0.rampNumPoints < t1.rampNumPoints ? t0.rampNumPoints : t1.rampNumPoints;
            for (U32 i = 0; i < n; ++i) {
                t.rampPositions[i] = lerpf(t0.rampPositions[i], t1.rampPositions[i], mask);
                t.rampColors[i] = lerp(t0.rampColors[i], t1.rampColors[i], mask);
                t.rampInterpolators[i] = t1.rampInterpolators[i];
            }
            const ToonDiffuseParameters& rest = t0.rampNumPoints > t1.rampNumPoints ? t0 : t1;
            for (U32 i = n; i < t.rampNumPoints; ++i) {
                t.rampPositions[i] = rest.rampPositions[i];
                t.rampColors[i] = rest.rampColors[i];
                t.rampInterpolators[i] = rest.rampInterpolators[i];
            }
            t.extendRamp = t0.extendRamp != t1.extendRamp ? true : t1.extendRamp;
        }
    } else {
        const ToonDiffuseParameters& s = !isZero(t1.toonDiffuse) ? t1 : t0;
        t.model = s.model;
        t.normal = s.normal;
        copyToonRamp(s, t);
        copyToonOrenNayar(s, t);
    }
}
X2_HD inline void blendDiffuse(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    const bool has0 = !isBlack(p0.albedo), has1 = !isBlack(p1.albedo);
    const bool blocked = isOne(p.metallic) || isZero(p.fabricAttenuation) || isOne(p.transmission);
    if (blocked || !(has0 || has1)) return;
    p.albedo = colorSpaceLerp(p0.albedo, p1.albedo, mask, cs);
    p.diffuseTransmission = lerp(p0.diffuseTransmission, p1.diffuseTransmission, mask);
    if (has0 && has1) {
        p.scatteringRadius = colorSpaceLerp(p0.scatteringRadius, p1.scatteringRadius, mask, cs);
        p.creaseAttenuation = lerpf(p0.creaseAttenuation, p1.creaseAttenuation, mask);
        p.diffuseTransmissionBlendingBehavior = p1.diffuseTransmissionBlendingBehavior;
        p.diffuseRoughness = lerpf(p0.diffuseRoughness, p1.diffuseRoughness, mask);
    } else {
        const DwaParams& s = has1 ? p1 : p0;
        p.scatteringRadius = s.scatteringRadius;
        p.creaseAttenuation = s.creaseAttenuation;
        p.diffuseTransmissionBlendingBehavior = s.diffuseTransmissionBlendingBehavior;
        p.diffuseRoughness = s.diffuseRoughness;
    }
}
X2_HD inline void blendRefractiveIndex(float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    if (isZero(p0.fabricAttenuation) && isZero(p1.fabricAttenuation)) return;
    const bool uses0 = !isOne(p0.metallic) && (!isZero(p0.specular) || !isZero(p0.transmission)) && !isOne(p0.fabricSpecular);
    const bool uses1 = !isOne(p1.metallic) && (!isZero(p1.specular) || !isZero(p1.transmission)) && !isOne(p1.fabricSpecular);
    if (uses0 && uses1) p.refractiveIndex = lerpf(p0.refractiveIndex, p1.refractiveIndex, mask);
    else if (uses1) p.refractiveIndex = p1.refractiveIndex;
    else if (uses0) p.refractiveIndex = p0.refractiveIndex;
}
X2_HD inline void blendCommon(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    p.diffuseNormal = normalize(lerpV(p0.diffuseNormal, p1.diffuseNormal, mask));
    p.normal = normalize(lerpV(p0.normal, p1.normal, mask));
    p.normalLength = lerpf(p0.normalLength, p1.normalLength, mask);
    p.normalAAStrategy = p0.normalAAStrategy != p1.normalAAStrategy ? U32(NormalAAToksvig) : p1.normalAAStrategy;
    if (p.normalAAStrategy != NormalAANone) p.normalAADial = lerpf(p0.normalAADial, p1.normalAADial, mask);
    p.emission = colorSpaceLerp(p0.emission, p1.emission, mask, cs);
}
X2_HD inline void blendAccent(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    p.accentSubsurface = lerpf(p0.accentSubsurface, p1.accentSubsurface, mask);
    p.accentSubsurfaceNormal = normalize(lerpV(p0.accentSubsurfaceNormal, p1.accentSubsurfaceNormal, mask));
    p.accentSubsurfaceNormalDial = lerpf(p0.accentSubsurfaceNormalDial, p1.accentSubsurfaceNormalDial, mask);
    p.accentSubsurfaceColor = colorSpaceLerp(p0.accentSubsurfaceColor, p1.accentSubsurfaceColor, mask, cs);
}
// copyToonSpecularParams (enableIndirectReflections is neither copied nor blended: it stays off).
X2_HD inline void copyToonSpecular(const ToonSpecularParameters& s, ToonSpecularParameters& d) {
    d.intensity = s.intensity;
    d.fresnelBlend = s.fresnelBlend;
    d.roughness = s.roughness;
    d.tint = s.tint;
    d.rampInputScale = s.rampInputScale;
    d.rampNumPoints = s.rampNumPoints;
    for (U32 i = 0; i < s.rampNumPoints && i < DwaMaxToonRampPoints; ++i) {
        d.rampPositions[i] = s.rampPositions[i];
        d.rampValues[i] = s.rampValues[i];
        d.rampInterpolators[i] = s.rampInterpolators[i];
    }
    d.normal = s.normal;
    d.stretchU = s.stretchU;
    d.stretchV = s.stretchV;
    d.dPds = s.dPds;
    d.dPdt = s.dPdt;
    d.indirectReflectionsIntensity = s.indirectReflectionsIntensity;
    d.indirectReflectionsRoughness = s.indirectReflectionsRoughness;
}
X2_CALL void blendToonSpecular(U32 cs, float mask, const ToonSpecularParameters& t0, const ToonSpecularParameters& t1,
                               ToonSpecularParameters& t) {
    t.toonSpecular = lerpf(t0.toonSpecular, t1.toonSpecular, mask);
    if (isZero(t.toonSpecular)) return;
    if (!isZero(t0.toonSpecular) && !isZero(t1.toonSpecular)) {
        t.normal = normalize(lerpV(t0.normal, t1.normal, mask));
        t.intensity = lerpf(t0.intensity, t1.intensity, mask);
        t.fresnelBlend = lerpf(t0.fresnelBlend, t1.fresnelBlend, mask);
        t.roughness = lerpf(t0.roughness, t1.roughness, mask);
        t.tint = colorSpaceLerp(t0.tint, t1.tint, mask, cs);
        t.rampInputScale = lerpf(t0.rampInputScale, t1.rampInputScale, mask);
        t.rampNumPoints = t0.rampNumPoints > t1.rampNumPoints ? t0.rampNumPoints : t1.rampNumPoints;
        const U32 both = t0.rampNumPoints < t1.rampNumPoints ? t0.rampNumPoints : t1.rampNumPoints;
        for (U32 i = 0; i < both && i < DwaMaxToonRampPoints; ++i) {
            t.rampPositions[i] = lerpf(t0.rampPositions[i], t1.rampPositions[i], mask);
            t.rampValues[i] = lerpf(t0.rampValues[i], t1.rampValues[i], mask);
            t.rampInterpolators[i] = t1.rampInterpolators[i];
        }
        const ToonSpecularParameters& rest = t0.rampNumPoints > t1.rampNumPoints ? t0 : t1;
        for (U32 i = both; i < t.rampNumPoints && i < DwaMaxToonRampPoints; ++i) {
            t.rampPositions[i] = rest.rampPositions[i];
            t.rampValues[i] = rest.rampValues[i];
            t.rampInterpolators[i] = rest.rampInterpolators[i];
        }
        t.stretchU = lerpf(t0.stretchU, t1.stretchU, mask);
        t.stretchV = lerpf(t0.stretchV, t1.stretchV, mask);
        t.dPds = lerpV(t0.dPds, t1.dPds, mask);
        t.dPdt = lerpV(t0.dPdt, t1.dPdt, mask);
        t.indirectReflectionsIntensity = lerpf(t0.indirectReflectionsIntensity, t1.indirectReflectionsIntensity, mask);
        t.indirectReflectionsRoughness = lerpf(t0.indirectReflectionsRoughness, t1.indirectReflectionsRoughness, mask);
    } else {
        copyToonSpecular(!isZero(t1.toonSpecular) ? t1 : t0, t);
    }
}
// DWABASE_blendParameters past its early exits: p0 the background (B), p1 the foreground (A).
// The colour corrections were applied by each material; the hair parameters are not blended
// (MoonRay's DwaLayer drops them).
X2_CALL void blendParameters(U32 cs, float mask, const DwaParams& p0, const DwaParams& p1, DwaParams& p) {
    initParameters(p);
    // blendGlitterParams: the mask lerped, then the glitter of the input that has it (a layer both of whose inputs
    // have glitter shades its own Glitter object: refused at admission).
    p.glitterMask = lerpf(p0.glitterMask, p1.glitterMask, mask);
    if (!isZero(p.glitterMask)) {
        if (!isZero(p0.glitterMask) && !isZero(p1.glitterMask)) p.glitter.tables = GlitterNone;
        else p.glitter = !isZero(p0.glitterMask) ? p0.glitter : p1.glitter;
    }
    blendCommon(cs, mask, p0, p1, p);
    blendFuzz(cs, mask, p0, p1, p);
    blendOuterSpecular(cs, mask, p0, p1, p);
    blendCommonSpecular(mask, p0, p1, p);
    blendIridescence(cs, mask, p0, p1, p);
    blendMetallic(cs, mask, p0, p1, p);
    blendAccent(cs, mask, p0, p1, p);
    p.fabricAttenuation = lerpf(p0.fabricAttenuation, p1.fabricAttenuation, mask);
    blendFabric(cs, mask, p0, p1, p);
    blendRefractiveIndex(mask, p0, p1, p);
    blendTransmission(cs, mask, p0, p1, p);
    blendToonDiffuse(mask, p0.toonDiffuse, p1.toonDiffuse, p.toonDiffuse);
    blendToonSpecular(cs, mask, p0.toonSpec, p1.toonSpec, p.toonSpec);
    blendDiffuse(cs, mask, p0, p1, p);
}

//----------------------------------------------------------------------------
// The material tree. Every node is 32 words in the material pool.
enum DwaNodeKind : U32 { NodeLeaf = 0, NodeLayer, NodeMix, NodeTwoSided, NodeSwitch, NodeColorCorrect, NodeAdjust };
constexpr U32 DwaNoNode = 0xffffffffu, DwaMaxSlots = 6, DwaMaxDepth = 24, DwaMaxMixInputs = 64;
enum AdjustEmissionMode : U32 { EmissionOff = 0, EmissionMasked = 1, EmissionUnmasked = 2 };
struct DwaNode {
    U32 kind;
    // Leaf: the DwaRecord's pool offset. Layer: B (background), A (foreground). TwoSided: front, back.
    // Switch, ColorCorrect, Adjust: the input. Mix: the pool offset of its list of inputs, and its count.
    U32 child[2];
    // The castsCaustics each child is resolved with when it is its own (TwoSided, Switch, ColorCorrect,
    // Adjust pass their input its own; Layer and Mix pass on what they were given).
    U32 childCaustics[2];
    U32 colorSpace;
    // The node's bound attributes: a leaf's onto its DwaInputs, a combinator's onto value[].
    U32 bindings, bindingCount;
    // Layer: mask. Mix: mix, maxMixValue, inputMultiplier, interpolation. ColorCorrect: on, mix, hueShift,
    // saturation, gain, tmiEnabled, tmi (3). Adjust: on, mix, emissionMode, emission (3), disableClearcoat,
    // disableSpecular, disableDiffuse.
    float value[24];
};
static_assert(sizeof(DwaNode) == 32 * 4, "DwaNode is 32 words");
// A DwaBase-family material in the material pool: its uniform parameters, its own castsCaustics
// (what shade() passes the root), its root node and the parameter slots its tree needs.
struct DwaTree {
    DwaUniformParams up;
    U32 castsCaustics, root, slots;
    U32 requiresRefP;  // a leaf's glitter is in reference space: ref_P is a required attribute
};
constexpr U32 DwaTreeFloats = sizeof(DwaTree) / sizeof(float);

X2_HD inline const DwaNode& dwaNode(const float* pool, U32 offset) { return *reinterpret_cast<const DwaNode*>(pool + offset); }
X2_HD inline const DwaRecord& dwaRecord(const float* pool, U32 offset) { return *reinterpret_cast<const DwaRecord*>(pool + offset); }
X2_HD inline U32 poolU32(const float* pool, U32 offset) { return *reinterpret_cast<const U32*>(pool + offset); }
// A combinator's values at this hit: its own, under its bindings.
struct NodeValues {
    float v[12];
    X2_HD NodeValues(const float* pool, const DwaNode& n, const Color* regs) {
        for (U32 i = 0; i < 12; ++i) v[i] = n.value[i];
        if (n.bindingCount) applyBindings(v, reinterpret_cast<const MapBinding*>(pool + n.bindings), n.bindingCount, regs);
    }
};

// DwaMix's interpolateMix.
X2_HD inline float interpolateMix(float mix, U32 mode, float inputMultiplier) {
    mix = mix * inputMultiplier;
    const float twoPi = 6.283185307179586f, oneOverTwoPi = 0.159154943091895f;
    switch (mode) {
    case 1: mix = floorf(mix); break;
    case 2: mix = floorf(mix + 0.5f); break;
    case 3: mix = (sinf((mix + 0.5f) * twoPi) + (mix + 0.5f) * twoPi) * oneOverTwoPi - 0.5f; break;
    default: break;
    }
    if (fabsf(float(int(mix + 0.5f)) - mix) < 0.001f) mix = float(int(mix + 0.5f));
    return mix;
}
// The two inputs a Mix blends at this hit and the weight of the second; false without a first.
X2_HD inline bool mixInputs(const float* pool, const DwaNode& n, const float* value, U32& in0, U32& in1, float& t) {
    float mix = clampf(value[0], 0.0f, n.value[1]);
    mix = interpolateMix(mix, U32(n.value[3]), n.value[2]);
    const U32 t0 = U32(int(mix));
    in0 = t0 < n.child[1] ? poolU32(pool, n.child[0] + t0) : DwaNoNode;
    in1 = t0 + 1 < n.child[1] ? poolU32(pool, n.child[0] + t0 + 1) : DwaNoNode;
    t = mix - float(t0);
    return in0 != DwaNoNode;
}

// DwaAdjust's modifyParameters, without the primitive attributes (XPU2 meshes carry none yet).
X2_HD inline void adjustParameters(const DwaNode& n, const float* value, DwaParams& p) {
    if (n.value[0] == 0.0f) return;
    const float mix = saturate(value[1]);
    const U32 mode = U32(n.value[2]);
    const float eMix = mode == EmissionUnmasked ? 1.f : mode == EmissionMasked ? mix : 0.f;
    const Color e = p.emission + eMix * Color{value[3], value[4], value[5]};
    p.emission = Color{fmaxf(0.f, e.x), fmaxf(0.f, e.y), fmaxf(0.f, e.z)};
    if (n.value[6] != 0.0f) p.outerSpecular = 0.f;
    if (n.value[7] != 0.0f) {
        p.specular = 0.f;
        p.outerSpecular = 0.f;
        p.fabricSpecular = 0.f;
    }
    if (n.value[8] != 0.0f) {
        p.albedo = rgb(0);
        p.warpColor = rgb(0);
        p.weftColor = rgb(0);
    }
}

struct DwaFrame {
    U32 node, slot, phase, caustics, ccCount;
    U32 in0, in1;
    float t;
};
// Resolves the tree into slots[0]: DWABASELAYERABLE resolveParameters of the root. False when
// MoonRay's would be (a missing input): the material then gives no lobes.
X2_CALL bool resolveDwaTree(const float* pool, const DwaTree& tree, const State& st, DwaParams* slots, const Color* regs) {
    DwaFrame stack[DwaMaxDepth];
    ColorCorrectParameters cc[DwaMaxColorCorrections];
    U32 depth = 0, ccCount = 0;
    stack[depth++] = DwaFrame{tree.root, 0, 0, tree.castsCaustics, 0, DwaNoNode, DwaNoNode, 0.0f};
    while (depth) {
        DwaFrame& f = stack[depth - 1];
        const DwaNode& n = dwaNode(pool, f.node);
        // Tail calls replace the frame; pushes add one.
        auto replace = [&](U32 node, U32 caustics) {
            f.node = node;
            f.phase = 0;
            f.caustics = caustics;
        };
        auto push = [&](U32 node, U32 slot, U32 caustics) -> bool {
            if (depth >= DwaMaxDepth) return false;
            stack[depth++] = DwaFrame{node, slot, 0, caustics, 0, DwaNoNode, DwaNoNode, 0.0f};
            return true;
        };
        switch (n.kind) {
        case NodeLeaf: {
            DwaParams& p = slots[f.slot];
            p.numColorCorrections = ccCount;
            for (U32 i = 0; i < ccCount; ++i) p.colorCorrect[i] = cc[i];
            const DwaRecord& r = dwaRecord(pool, n.child[0]);
            if (n.bindingCount) {
                DwaInputs in = r.in;
                applyBindings(reinterpret_cast<float*>(&in), reinterpret_cast<const MapBinding*>(pool + n.bindings), n.bindingCount,
                              regs);
                resolveDwaBase(r.u, in, st, f.caustics != 0, p, regs);
            } else {
                resolveDwaBase(r.u, r.in, st, f.caustics != 0, p, regs);
            }
            --depth;
            break;
        }
        case NodeLayer:
        case NodeMix: {
            if (f.phase == 0) {
                const NodeValues values(pool, n, regs);
                if (n.kind == NodeLayer) {
                    f.in0 = n.child[0];
                    f.in1 = n.child[1];
                    f.t = saturate(values.v[0]);
                    if (f.in0 == DwaNoNode) return false;
                } else if (!mixInputs(pool, n, values.v, f.in0, f.in1, f.t)) {
                    return false;
                }
                if (f.in1 == DwaNoNode || isZero(f.t)) {
                    replace(f.in0, f.caustics);
                } else if (isOne(f.t)) {
                    replace(f.in1, f.caustics);
                } else {
                    if (f.slot + 3 > tree.slots) return false;
                    f.phase = 1;
                    if (!push(f.in0, f.slot + 1, f.caustics)) return false;
                }
            } else if (f.phase == 1) {
                f.phase = 2;
                if (!push(f.in1, f.slot + 2, f.caustics)) return false;
            } else {
                blendParameters(n.colorSpace, f.t, slots[f.slot + 1], slots[f.slot + 2], slots[f.slot]);
                --depth;
            }
            break;
        }
        case NodeTwoSided: {
            const U32 side = st.entering ? 0 : 1;
            if (n.child[side] == DwaNoNode) return false;
            replace(n.child[side], n.childCaustics[side]);
            break;
        }
        case NodeSwitch:
            if (n.child[0] == DwaNoNode) return false;
            replace(n.child[0], n.childCaustics[0]);
            break;
        case NodeColorCorrect:
            if (n.child[0] == DwaNoNode) return false;
            if (f.phase == 0) {
                f.ccCount = ccCount;
                if (ccCount < DwaMaxColorCorrections) {
                    const NodeValues values(pool, n, regs);
                    ColorCorrectParameters& c = cc[ccCount];
                    c.on = n.value[0] != 0.0f;
                    c.mix = saturate(values.v[1]);
                    c.hueShift = values.v[2];
                    c.saturation = fmaxf(0.f, values.v[3]);
                    c.gain = values.v[4];
                    c.tmiEnabled = n.value[5] != 0.0f;
                    c.tmi = Color{values.v[6], values.v[7], values.v[8]};
                    ++ccCount;
                }
                f.phase = 1;
                if (!push(n.child[0], f.slot, n.childCaustics[0])) return false;
            } else {
                ccCount = f.ccCount;
                --depth;
            }
            break;
        case NodeAdjust:
            if (n.child[0] == DwaNoNode) return false;
            if (f.phase == 0) {
                f.phase = 1;
                if (!push(n.child[0], f.slot, n.childCaustics[0])) return false;
            } else {
                const NodeValues values(pool, n, regs);
                adjustParameters(n, values.v, slots[f.slot]);
                --depth;
            }
            break;
        default: return false;
        }
    }
    return true;
}

// The tree's presence (each combinator's resolvePresence; TwoSided, Switch and ColorCorrect keep
// theirs in a bool, as MoonRay's do).
struct PresenceFrame {
    U32 node, phase;
    float t, p0, cast;  // cast: 1 when the result is to be kept as a bool
};
X2_CALL float dwaTreePresence(const float* pool, const DwaTree& tree, const State& st, const Color* regs) {
    PresenceFrame stack[DwaMaxDepth];
    U32 depth = 0;
    float result = 1.0f;
    stack[depth++] = PresenceFrame{tree.root, 0, 0.0f, 0.0f, 0.0f};
    // Each frame leaves its result in 'result' when it pops.
    while (depth) {
        PresenceFrame& f = stack[depth - 1];
        const DwaNode& n = dwaNode(pool, f.node);
        auto finish = [&](float v) {
            result = f.cast != 0.0f ? (v != 0.0f ? 1.0f : 0.0f) : v;
            --depth;
        };
        auto push = [&](U32 node, float cast) {
            if (depth < DwaMaxDepth) stack[depth++] = PresenceFrame{node, 0, 0.0f, 0.0f, cast};
        };
        switch (n.kind) {
        case NodeLeaf: {
            const DwaRecord& r = dwaRecord(pool, n.child[0]);
            float p = r.in.presence;
            if (n.bindingCount) {
                const MapBinding* b = reinterpret_cast<const MapBinding*>(pool + n.bindings);
                for (U32 i = 0; i < n.bindingCount; ++i)
                    if (b[i].offset == U32(X2_OFFSETOF(DwaInputs, presence) / sizeof(float))) applyRule(&p, b[i].rule, regs[b[i].reg]);
            }
            finish(saturate(p));
            break;
        }
        case NodeLayer:
        case NodeMix: {
            U32 in0 = DwaNoNode, in1 = DwaNoNode;
            float t = 0.0f;
            const NodeValues values(pool, n, regs);
            if (n.kind == NodeLayer) {
                in0 = n.child[0];
                in1 = n.child[1];
                t = saturate(values.v[0]);
            } else if (!mixInputs(pool, n, values.v, in0, in1, t)) {
                in0 = DwaNoNode;
            }
            if (f.phase == 0) {
                if (in0 == DwaNoNode) {
                    finish(1.0f);
                } else if (in1 == DwaNoNode || isZero(t)) {
                    f.phase = 3;
                    push(in0, 0.0f);
                } else if (isOne(t)) {
                    f.phase = 3;
                    push(in1, 0.0f);
                } else {
                    f.phase = 1;
                    f.t = t;
                    push(in0, 0.0f);
                }
            } else if (f.phase == 1) {
                f.p0 = result;
                f.phase = 2;
                push(in1, 0.0f);
            } else if (f.phase == 2) {
                finish(lerpf(f.p0, result, f.t));
            } else {
                finish(result);
            }
            break;
        }
        case NodeTwoSided: {
            const U32 side = st.entering ? 0 : 1;
            if (f.phase == 0) {
                if (n.child[side] == DwaNoNode) {
                    finish(0.0f);
                } else {
                    f.cast = 1.0f;
                    f.phase = 1;
                    push(n.child[side], 0.0f);
                }
            } else {
                finish(result);
            }
            break;
        }
        case NodeSwitch:
        case NodeColorCorrect:
        case NodeAdjust:
            if (f.phase == 0) {
                if (n.child[0] == DwaNoNode) {
                    finish(n.kind == NodeSwitch ? 0.0f : 1.0f);
                } else {
                    if (n.kind != NodeAdjust) f.cast = 1.0f;
                    f.phase = 1;
                    push(n.child[0], 0.0f);
                }
            } else {
                finish(result);
            }
            break;
        default: finish(1.0f); break;
        }
    }
    return result;
}
}}}
