// Private XPU2 shading library: evaluating, sampling and differentiating the
// lobes of shade_lobes.h. Derived from MoonRay Apache-2.0 (the ISPC lobes'
// eval, sample, albedo and differentials functions), Copyright 2023-2024
// DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "shade_lobes.h"
#include "shade_hair.h"
#include "shade_flakes.h"
namespace xpu2 { namespace interactive { namespace shade {

X2_HD inline float widenRoughness(float roughness, float cosNO) { return (1.2f - 0.2f * sqrtf(cosNO)) * roughness; }
X2_HD inline float beckmannG1(float a) {
    return a < 1.6f ? (3.535f * a + 2.181f * a * a) / (1.0f + 2.276f * a + 2.577f * a * a) : 1.0f;
}
X2_HD inline V3 beckmannMicrofacet(const Frame& f, float roughness, float r1, float r2, float cosNO) {
    const float alpha = widenRoughness(roughness, cosNO), alpha2 = alpha * alpha;
    const float tanThetaMSqr = -alpha2 * logf(1.0f - r1), tanThetaM = sqrtf(tanThetaMSqr);
    const float cosThetaM = rsqrt(1.0f + tanThetaMSqr), sinThetaM = cosThetaM * tanThetaM;
    return localToGlobal(f, localSpherical(cosThetaM, sinThetaM, 2.0f * Pi * r2));
}

// CookTorranceBsdfLobe_energyCompensation*
X2_HD inline float ctCompensationWeight(const CookTorranceParams& c) {
    if (isBlack(c.favg)) return 0.0f;
    return c.coupled ? energy::transmissionWeightR(c.etaI, c.etaT, c.inputRoughness) : energy::reflectionWeight(c.inputRoughness);
}
X2_HD inline float ctCompensationPdf(const CookTorranceParams& c, U32 type, float cosNI) {
    if (isBlack(c.favg)) return 0.0f;
    return c.coupled ? energy::transmissionPdfR(cosNI, c.etaI, c.etaT, c.inputRoughness)
                     : energy::reflectionPdf(type, cosNI, c.inputRoughness);
}
X2_CALL void ctCompensationSample(const CookTorranceParams& c, const Frame& f, U32 type, float r1, float r2, V3& wi) {
    if (isBlack(c.favg)) return;
    if (c.coupled) energy::transmissionSampleR(f, r1, r2, wi, c.inputRoughness, c.etaI, c.etaT);
    else energy::reflectionSample(type, f, r1, r2, c.inputRoughness, wi);
}
X2_HD inline Color ctCompensationEval(const CookTorranceParams& c, U32 type, float cosNO, float cosNI, bool includeCosine) {
    if (isBlack(c.favg)) return rgb(0);
    return c.coupled ? energy::transmissionEvalR(cosNO, cosNI, c.inputRoughness, c.etaI, c.etaT, c.favg.x, c.favgInv.x, includeCosine)
                     : energy::reflectionEval(type, cosNO, cosNI, c.inputRoughness, c.favg, includeCosine);
}

X2_CALL Color evalBeckmann(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const CookTorranceParams& c = l.ct;
    const V3 N = l.frame.z;
    pdf = 0.0f;
    float cosNO = dot(N, s.wo);
    if (cosNO <= Epsilon) return rgb(0);
    cosNO = fminf(cosNO, OneMinusEpsilon);
    float cosNI = dot(N, wi);
    if (cosNI <= Epsilon) return rgb(0);
    cosNI = fminf(cosNI, OneMinusEpsilon);
    V3 m;
    if (!computeNormalizedHalfVector(s.wo, wi, m)) return rgb(0);
    const float cosMI = dot(m, wi);
    if (cosMI <= Epsilon) return rgb(0);
    const float cosThetaM = dot(m, N);
    if (cosThetaM <= Epsilon) return rgb(0);
    float alpha2 = c.roughness * c.roughness;
    const float cosThetaM2 = cosThetaM * cosThetaM, cosThetaM4 = cosThetaM2 * cosThetaM2;
    const float minusTanThetaM2 = (cosThetaM2 - 1.0f) / cosThetaM2;
    float D4 = expf(minusTanThetaM2 / alpha2) / (FourPi * alpha2 * cosThetaM4);
    const float ao = cosNO * c.invRoughness * rsqrt(1.0f - cosNO * cosNO);
    const float ai = cosNI * c.invRoughness * rsqrt(1.0f - cosNI * cosNI);
    const float G = beckmannG1(ao) * beckmannG1(ai);
    Color f = G * D4 / cosNO * (s.includeCosine ? 1.0f : 1.0f / cosNI) * scaleAndFresnel(b, l, cosMI);
    const float w2 = ctCompensationWeight(c);
    if (w2 > 0.0f) f = f + ctCompensationEval(c, Beckmann, cosNO, cosNI, s.includeCosine);
    const float alpha = widenRoughness(c.roughness, cosNO);
    alpha2 = alpha * alpha;
    D4 = expf(minusTanThetaM2 / alpha2) / (FourPi * alpha2 * cosThetaM4);
    const float p2 = ctCompensationPdf(c, Beckmann, cosNI), p1 = D4 * cosThetaM / cosMI;
    pdf = (1.0f - w2) * p1 + w2 * p2;
    return shadowTerminatorFix(s, N, wi) * f;
}
X2_HD inline Color sampleBeckmann(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const float cosNO = dot(l.frame.z, s.wo);
    if (cosNO <= 0.0f) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const float w2 = ctCompensationWeight(l.ct);
    if (r1 < w2) {
        ctCompensationSample(l.ct, l.frame, Beckmann, r1 / w2, r2, wi);
    } else {
        const V3 m = beckmannMicrofacet(l.frame, l.ct.roughness, (r1 - w2) / (1.0f - w2), r2, cosNO);
        computeReflectionDirection(m, s.wo, wi);
    }
    return evalBeckmann(b, l, s, wi, pdf);
}
// GGXCookTorranceBsdfLobe_eval with an explicit roughness, cosines and frame (shared by glitter).
X2_CALL Color evalGGXFrame(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf, float roughness, float cosNO,
                                float cosNI, const Frame& f) {
    const CookTorranceParams& c = l.ct;
    pdf = 0.0f;
    if (cosNO <= 0.0f || cosNI <= 0.0f) return rgb(0);
    V3 m;
    if (!computeNormalizedHalfVector(s.wo, wi, m)) return rgb(0);
    const float cosMI = dot(m, wi);
    if (cosMI <= 0.0f) return rgb(0);
    const float cosThetaM = dot(m, f.z);
    if (cosThetaM <= 0.0f) return rgb(0);
    float alpha2 = roughness * roughness;
    const float cosThetaM2 = cosThetaM * cosThetaM, piCosThetaM4 = Pi * cosThetaM2 * cosThetaM2;
    const float tanThetaM2 = (1.0f - cosThetaM2) / cosThetaM2;
    float tmp = alpha2 + tanThetaM2, D4 = 0.25f * alpha2 / (piCosThetaM4 * tmp * tmp);
    const float invCosNO = 1.0f / cosNO, invCosNI = 1.0f / cosNI;
    const float G1o = 2.0f / (1.0f + sqrtf(1.0f + alpha2 * (1.0f - cosNO * cosNO) * (invCosNO * invCosNO)));
    const float G1i = 2.0f / (1.0f + sqrtf(1.0f + alpha2 * (1.0f - cosNI * cosNI) * (invCosNI * invCosNI)));
    Color fr = scaleAndFresnel(b, l, cosMI) * G1o * G1i * D4 * invCosNO * (s.includeCosine ? 1.0f : invCosNI);
    const float w2 = ctCompensationWeight(c);
    if (w2 > 0.0f) fr = fr + ctCompensationEval(c, GGXDistribution, cosNO, cosNI, s.includeCosine);
    const float alpha = widenRoughness(roughness, cosNO);
    alpha2 = alpha * alpha;
    tmp = alpha2 + tanThetaM2;
    D4 = 0.25f * alpha2 / (piCosThetaM4 * tmp * tmp);
    const float p2 = ctCompensationPdf(c, GGXDistribution, cosNI), p1 = D4 * cosThetaM / cosMI;
    pdf = (1.0f - w2) * p1 + w2 * p2;
    return fr;
}
X2_HD inline V3 sampleGGXFrame(const Slice& s, float r1, float r2, float roughness, float cosNO, const Frame& f) {
    const float alpha = widenRoughness(roughness, cosNO), alpha2 = alpha * alpha;
    const float tanThetaM2 = alpha2 * r1 / (1.0f - r1), cosThetaM = 1.0f / sqrtf(1.0f + tanThetaM2);
    const float sinThetaM = cosThetaM * sqrtf(tanThetaM2);
    const V3 m = localToGlobal(f, localSpherical(cosThetaM, sinThetaM, 2.0f * Pi * r2));
    V3 wi;
    computeReflectionDirection(m, s.wo, wi);
    return wi;
}
X2_HD inline Color evalGGX(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const V3 N = l.frame.z;
    const float Gs = shadowTerminatorFix(s, N, wi);
    return Gs * evalGGXFrame(b, l, s, wi, pdf, l.ct.roughness, dot(N, s.wo), dot(N, wi), l.frame);
}
X2_HD inline Color sampleGGX(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const float cosNO = dot(l.frame.z, s.wo);
    if (cosNO <= 0.0f) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const float w2 = ctCompensationWeight(l.ct);
    if (r1 < w2) ctCompensationSample(l.ct, l.frame, GGXDistribution, r1 / w2, r2, wi);
    else wi = sampleGGXFrame(s, (r1 - w2) / (1.0f - w2), r2, l.ct.roughness, cosNO, l.frame);
    return evalGGX(b, l, s, wi, pdf);
}
X2_HD inline Color evalGlitter(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    float cosNO = dot(l.ct.flakeNormal, s.wo), cosNI = dot(l.ct.flakeNormal, wi);
    Frame f;
    if (cosNO <= 0.0f || cosNI <= 0.0f) {
        f = l.frame;
        cosNO = dot(f.z, s.wo);
        cosNI = dot(f.z, wi);
    } else {
        f = frame(l.ct.flakeNormal);
    }
    return evalGGXFrame(b, l, s, wi, pdf, l.ct.roughness, cosNO, cosNI, f);
}
X2_HD inline Color sampleGlitter(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    bool usingFlake = true;
    float cosNO = dot(l.ct.flakeNormal, s.wo);
    Frame f;
    if (cosNO <= 0.0f) {
        f = l.frame;
        cosNO = dot(f.z, s.wo);
        usingFlake = false;
        if (cosNO <= 0.0f) {
            wi = V3{0, 0, 0};
            pdf = 0.0f;
            return rgb(0);
        }
    } else {
        f = frame(l.ct.flakeNormal);
    }
    wi = sampleGGXFrame(s, r1, r2, l.ct.roughness, cosNO, f);
    float cosNI = dot(f.z, wi);
    if (usingFlake && dot(l.frame.z, wi) <= 0.0f) {
        f = l.frame;
        cosNO = dot(f.z, s.wo);
        if (cosNO <= 0.0f) {
            wi = V3{0, 0, 0};
            pdf = 0.0f;
            return rgb(0);
        }
        wi = sampleGGXFrame(s, r1, r2, l.ct.roughness, cosNO, f);
        cosNI = dot(f.z, wi);
    }
    return evalGGXFrame(b, l, s, wi, pdf, l.ct.roughness, cosNO, cosNI, f);
}
X2_CALL Color evalAniso(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const CookTorranceParams& c = l.ct;
    const V3 N = l.frame.z;
    pdf = 0.0f;
    const float cosNO = dot(N, s.wo);
    if (cosNO <= 0.0f) return rgb(0);
    const float cosNI = dot(N, wi);
    if (cosNI <= 0.0f) return rgb(0);
    V3 m;
    if (!computeNormalizedHalfVector(s.wo, wi, m)) return rgb(0);
    const float cosMI = dot(m, wi);
    if (cosMI <= 0.0f) return rgb(0);
    const float cosThetaM = dot(m, N);
    if (cosThetaM <= 0.0f) return rgb(0);
    const float dotMX = dot(m, l.frame.x), dotMY = dot(m, l.frame.y);
    float cx = dotMX / c.roughness, cy = dotMY / c.roughness;
    cy = dotMY / c.roughnessV;
    const float cosThetaM2 = cosThetaM * cosThetaM;
    float D4 = 0.25f * expf(-(cx * cx + cy * cy) / cosThetaM2) / (Pi * c.roughness * c.roughnessV * cosThetaM2 * cosThetaM2);
    const float tXO = dot(l.frame.x, s.wo) * c.roughness, tYO = dot(l.frame.y, s.wo) * c.roughnessV;
    const float ao = cosNO / sqrtf(tXO * tXO + tYO * tYO);
    const float tXI = dot(l.frame.x, wi) * c.roughness, tYI = dot(l.frame.y, wi) * c.roughnessV;
    const float ai = cosNI / sqrtf(tXI * tXI + tYI * tYI);
    const float G = beckmannG1(ao) * beckmannG1(ai);
    const Color f = scaleAndFresnel(b, l, cosMI) * G * D4 * (1.0f / cosNO) * (s.includeCosine ? 1.0f : 1.0f / cosNI);
    const float alphaU = widenRoughness(c.roughness, cosNO), alphaV = widenRoughness(c.roughnessV, cosNO);
    cx = dotMX / alphaU;
    cy = dotMY / alphaV;
    D4 = 0.25f * expf(-(cx * cx + cy * cy) / cosThetaM2) / (Pi * alphaU * alphaV * cosThetaM2 * cosThetaM2);
    pdf = D4 * cosThetaM / cosMI;
    return shadowTerminatorFix(s, N, wi) * f;
}
X2_HD inline Color sampleAniso(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const CookTorranceParams& c = l.ct;
    const float cosNO = dot(l.frame.z, s.wo);
    if (cosNO <= 0.0f) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const float alphaU = widenRoughness(c.roughness, cosNO), alphaV = widenRoughness(c.roughnessV, cosNO);
    const float invU2 = 1.0f / (alphaU * alphaU), invV2 = 1.0f / (alphaV * alphaV);
    const float phi = TwoPi * r2;
    float sp, cp;
    sincosf2(phi, &sp, &cp);
    const float cosOrig = alphaU * cp, sinOrig = alphaV * sp;
    const float cosSqrdPhi = 1.0f / (sinOrig * sinOrig / (cosOrig * cosOrig) + 1.0f), sinSqrdPhi = 1.0f - cosSqrdPhi;
    const float sinPhiM = sinOrig < 0.0f ? -sqrtf(sinSqrdPhi) : sqrtf(sinSqrdPhi);
    const float cosPhiM = cosOrig < 0.0f ? -sqrtf(cosSqrdPhi) : sqrtf(cosSqrdPhi);
    const float denominator = cosSqrdPhi * invU2 + sinSqrdPhi * invV2;
    const float cosThetaMSqrd = denominator / (denominator - logf(fmaxf(r1, Epsilon)));
    const float cosThetaM = sqrtf(cosThetaMSqrd), sinThetaM = sqrtf(1.0f - cosThetaMSqrd);
    const V3 m = localToGlobal(l.frame, localSpherical(cosThetaM, sinThetaM, cosPhiM, sinPhiM));
    computeReflectionDirection(m, s.wo, wi);
    return evalAniso(b, l, s, wi, pdf);
}
X2_CALL Color evalBerry(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const CookTorranceParams& c = l.ct;
    const V3 N = l.frame.z;
    pdf = 0.0f;
    const float cosNO = dot(N, s.wo);
    if (cosNO <= 0.0f) return rgb(0);
    const float cosNI = dot(N, wi);
    if (cosNI <= 0.0f) return rgb(0);
    V3 m;
    if (!computeNormalizedHalfVector(s.wo, wi, m)) return rgb(0);
    const float cosMI = dot(m, wi);
    if (cosMI <= 0.0f) return rgb(0);
    const float cosThetaM = dot(m, N);
    if (cosThetaM <= 0.0f) return rgb(0);
    float alpha2 = c.roughness * c.roughness;
    const float cosThetaM2 = cosThetaM * cosThetaM, sinThetaM2 = 1.0f - cosThetaM2;
    float d0 = (alpha2 - 1.0f) / (Pi * logf(alpha2)), d1 = 1.0f / (alpha2 * cosThetaM2 + sinThetaM2), D4 = 0.25f * d0 * d1;
    const float invCosNO = 1.0f / cosNO, invCosNI = 1.0f / cosNI;
    const float G1o = 2.0f / (1.0f + sqrtf(1.0f + alpha2 * (1.0f - cosNO * cosNO) * (invCosNO * invCosNO)));
    const float G1i = 2.0f / (1.0f + sqrtf(1.0f + alpha2 * (1.0f - cosNI * cosNI) * (invCosNI * invCosNI)));
    const Color f = scaleAndFresnel(b, l, cosMI) * G1o * G1i * D4 * invCosNO * (s.includeCosine ? 1.0f : invCosNI);
    const float alpha = widenRoughness(c.roughness, cosNO);
    alpha2 = alpha * alpha;
    d0 = (alpha2 - 1.0f) / (Pi * logf(alpha2));
    d1 = 1.0f / (alpha2 * cosThetaM2 + sinThetaM2);
    D4 = 0.25f * d0 * d1;
    pdf = D4 * cosThetaM / cosMI;
    return shadowTerminatorFix(s, N, wi) * f;
}
X2_HD inline Color sampleBerry(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const float cosNO = dot(l.frame.z, s.wo);
    if (cosNO <= 0.0f) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const float alpha = widenRoughness(l.ct.roughness, cosNO), alpha2 = alpha * alpha;
    const float cosThetaM = sqrtf((1.0f - powf(alpha2, 1.0f - r1)) / (1.0f - alpha2));
    const float tanThetaM = sqrtf(1.0f - cosThetaM * cosThetaM) / cosThetaM, sinThetaM = cosThetaM * tanThetaM;
    const V3 m = localToGlobal(l.frame, localSpherical(cosThetaM, sinThetaM, 2.0f * Pi * r2));
    computeReflectionDirection(m, s.wo, wi);
    return evalBerry(b, l, s, wi, pdf);
}
X2_CALL Color evalTransmissionCT(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float etaT, float& pdf) {
    const CookTorranceParams& c = l.ct;
    const V3 N = l.frame.z;
    pdf = 0.0f;
    float cosNO = dot(N, s.wo), cosNI = dot(N, wi);
    if (cosNO * cosNI > 0.0f) return rgb(0);
    cosNO = cosNO > 0.0f ? fminf(cosNO, OneMinusEpsilon) : fmaxf(cosNO, -OneMinusEpsilon);
    cosNI = cosNI > 0.0f ? fminf(cosNI, OneMinusEpsilon) : fmaxf(cosNI, -OneMinusEpsilon);
    const float absCosNO = fabsf(cosNO);
    if (absCosNO <= Epsilon) return rgb(0);
    const float absCosNI = fabsf(cosNI);
    if (absCosNI <= Epsilon) return rgb(0);
    V3 m;
    if (!computeNormalizedRefractionHalfVector(c.etaI, s.wo, etaT, wi, m)) return rgb(0);
    if (c.etaI > etaT) m = -m;
    const float cosThetaM = dot(m, N);
    if (cosThetaM <= Epsilon) return rgb(0);
    const float cosMI = dot(m, wi), cosMO = dot(m, s.wo);
    if (cosNO * cosMO <= Epsilon || cosNI * cosMI <= Epsilon) return rgb(0);
    const float absCosMI = -cosMI;
    if (absCosMI <= Epsilon) return rgb(0);
    const float absCosMO = cosMO;
    if (absCosMO <= Epsilon) return rgb(0);
    float alpha2 = c.roughness * c.roughness;
    const float cosThetaM2 = cosThetaM * cosThetaM, cosThetaM4 = cosThetaM2 * cosThetaM2;
    const float minusTanThetaM2 = (cosThetaM2 - 1.0f) / cosThetaM2;
    float D = expf(minusTanThetaM2 / alpha2) / (Pi * alpha2 * cosThetaM4);
    const float ao = absCosNO * c.invRoughness * rsqrt(1.0f - cosNO * cosNO);
    const float ai = absCosNI * c.invRoughness * rsqrt(1.0f - cosNI * cosNI);
    const float G = beckmannG1(ao) * beckmannG1(ai);
    float denom = c.etaI * cosMO + etaT * cosMI;
    denom = 1.0f / (denom * denom);
    const float etaT2 = etaT * etaT;
    Color f = absCosMO * absCosMI * etaT2 * denom * G * D / absCosNO * (s.includeCosine ? 1.0f : 1.0f / absCosNI) *
              scaleAndFresnel(b, l, absCosMO);
    f = f + energy::transmissionEvalT(absCosNO, absCosNI, c.inputRoughness, c.etaI, etaT, c.favg.x, c.favgInv.x, s.includeCosine);
    const float alpha = widenRoughness(c.roughness, absCosNO);
    alpha2 = alpha * alpha;
    D = expf(minusTanThetaM2 / alpha2) / (Pi * alpha2 * cosThetaM4);
    pdf = etaT2 * D * cosThetaM * absCosMI * denom;
    return f * c.tint;
}
X2_HD inline Color sampleTransmissionCT(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const CookTorranceParams& c = l.ct;
    const float absCosNO = fabsf(dot(l.frame.z, s.wo));
    Color dispersion = rgb(1);
    float neta = c.neta, etaT = c.etaT, spectralPdf = 1.0f;
    pdf = 0.0f;
    if (c.allowDispersion) {
        sampleSpectralIOR(r1, c.etaR, c.etaG, c.etaB, etaT, spectralPdf, dispersion);
        neta = c.etaI / etaT;
    }
    const V3 m = beckmannMicrofacet(l.frame, c.roughness, r1, r2, absCosNO);
    computeReflectionDirection(m, s.wo, wi);
    float cosMO, cosMI;
    if (!computeRefractionDirection(m, s.wo, neta, wi, cosMO, cosMI)) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const Color r = evalTransmissionCT(b, l, s, wi, etaT, pdf);
    pdf *= spectralPdf;
    return dispersion * r;
}
X2_HD inline Color sampleMirrorReflection(const Bsdf& b, const Lobe& l, const Slice& s, V3& wi, float& pdf) {
    float cosTheta = fabsf(computeReflectionDirection(l.frame.z, s.wo, wi));
    pdf = 1.0f;
    return scaleAndFresnel(b, l, cosTheta) * (s.includeCosine ? 1.0f : 1.0f / cosTheta);
}
X2_HD inline Color sampleMirrorTransmission(const Bsdf& b, const Lobe& l, const Slice& s, float r1, V3& wi, float& pdf) {
    const MirrorParams& m = l.mirror;
    float neta;
    Color dispersion = rgb(1);
    if (m.allowDispersion) {
        float sampledEta;
        sampleSpectralIOR(r1, m.etaR, m.etaG, m.etaB, sampledEta, pdf, dispersion);
        neta = m.etaI / sampledEta;
    } else {
        neta = m.etaI / m.etaT;
        pdf = 1.0f;
    }
    float cosWo, cosWi;
    if (!computeRefractionDirection(l.frame.z, s.wo, neta, wi, cosWo, cosWi)) {
        pdf = 0.0f;
        return rgb(0);
    }
    return m.tint * scaleAndFresnel(b, l, cosWo) * dispersion * (s.includeCosine ? 1.0f : 1.0f / cosWi);
}
X2_HD inline Color evalRetro(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    pdf = 0.0f;
    const V3 N = l.frame.z;
    const float cosThetaI = fminf(dot(N, wi), OneMinusEpsilon);
    if (cosThetaI <= Epsilon) return rgb(0);
    const float cosOI = fminf(dot(wi, s.wo), OneMinusEpsilon);
    if (cosOI <= Epsilon) return rgb(0);
    const float alphaP = 2.0f / (l.retro.roughness * l.retro.roughness) - 2.0f;
    const float power = powf(cosOI, alphaP) * OneOverTwoPi;
    const Color f = scaleAndFresnel(b, l, cosThetaI) * (alphaP + 2.0f) * power * (s.includeCosine ? cosThetaI : 1.0f);
    pdf = (alphaP + 1.0f) * power;
    return shadowTerminatorFix(s, N, wi) * f;
}
X2_HD inline Color sampleRetro(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    if (dot(l.frame.z, s.wo) <= 0.0f) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const float alphaP = 2.0f / (l.retro.roughness * l.retro.roughness) - 2.0f;
    const float cosThetaM = powf(r1, 1.0f / (alphaP + 1.0f)), sinThetaM = sqrtf(1.0f - cosThetaM * cosThetaM);
    wi = localToGlobal(frame(s.wo), localSpherical(cosThetaM, sinThetaM, 2.0f * Pi * r2));
    return evalRetro(b, l, s, wi, pdf);
}
X2_HD inline Color evalEyeCaustic(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    pdf = 0.0f;
    const V3 N = l.frame.z;
    const float cosThetaO = dot(l.eye.Ng, s.wo);
    if (cosThetaO <= Epsilon) return rgb(0);
    const float cosI = fminf(dot(N, wi), OneMinusEpsilon);
    if (cosI <= Epsilon) return rgb(0);
    const float phong = powf(cosI, l.eye.exponent);
    const Color f = l.eye.causticColor * scaleAndFresnel(b, l, cosThetaO) * (l.eye.normalization * phong) *
                    (s.includeCosine ? cosI : 1.0f);
    pdf = (l.eye.exponent + 1) * OneOverTwoPi * phong;
    return shadowTerminatorFix(s, N, wi) * f;
}
X2_HD inline Color sampleEyeCaustic(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    if (dot(l.eye.Ng, s.wo) <= 0.0f) {
        wi = V3{0, 0, 0};
        pdf = 0.0f;
        return rgb(0);
    }
    const float cosThetaM = powf(r1, 1 / (l.eye.exponent + 1)), sinThetaM = sqrtf(1 - cosThetaM * cosThetaM);
    wi = localToGlobal(l.frame, localSpherical(cosThetaM, sinThetaM, TwoPi * r2));
    return evalEyeCaustic(b, l, s, wi, pdf);
}
// BsdfFabric.isph
X2_HD inline float dwaFabricSpecular(V3 wo, V3 wi, V3 thread, float exponent, float normalization, float& pdf) {
    V3 H;
    if (!computeNormalizedHalfVector(wo, wi, H)) return 0.0f;
    const float cosHWo = dot(H, wo);
    if (cosHWo < Epsilon) return 0.0f;
    const float sinThetaH = clampf(dot(H, thread), -.99f, .99f), oneMinus = 1.0f - fabsf(sinThetaH);
    if (oneMinus < Epsilon) return 0.0f;
    const float p = powf(oneMinus, exponent);
    pdf = (exponent + 1.0f) * OneOverPi * p * 0.25f / cosHWo;
    return normalization * p;
}
X2_HD inline float kajiyaKaySpecular(V3 wo, V3 wi, V3 thread, float exponent, float normalization, float& pdf) {
    const float cosThetaO = clampf(dot(thread, wo), -0.99f, 0.99f), sinThetaO = sqrtf(1 - cosThetaO * cosThetaO);
    const float cosThetaIP = -1 * clampf(dot(thread, wi), -0.99f, 0.99f), sinThetaIP = sqrtf(1 - cosThetaIP * cosThetaIP);
    const float cosThetaD = cosThetaO * cosThetaIP + sinThetaO * sinThetaIP;
    if (cosThetaD < Epsilon || cosThetaD > 1.f) return 0.0f;
    const float p = powf(cosThetaD, exponent), brdf = normalization * p;
    if (sinThetaIP > Epsilon) {
        pdf = (exponent + 1) * OneOverTwoPi * p;
        pdf *= sqrtf(clampf(1 - cosThetaD * cosThetaD, 0.0f, 1.0f));
        pdf /= sinThetaIP;
        if (brdf / pdf > 4) pdf = brdf / 4;
    }
    return brdf;
}
X2_HD inline Color evalFabric(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    pdf = 0.0f;
    const FabricParams& f = l.fabric;
    const float cosWi = dot(l.frame.z, wi);
    if (cosWi <= Epsilon) return rgb(0);
    const float cosWo = dot(l.frame.z, s.wo);
    if (cosWo <= Epsilon) return rgb(0);
    const float brdf = f.useDwaFabric ? dwaFabricSpecular(s.wo, wi, f.threadDirection, f.specularExponent, f.normalization, pdf)
                                      : kajiyaKaySpecular(s.wo, wi, f.threadDirection, f.specularExponent, f.normalization, pdf);
    return scaleAndFresnel(b, l, cosWo) * brdf * f.color * (s.includeCosine ? cosWi : 1.0f);
}
X2_HD inline Color sampleFabric(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const FabricParams& f = l.fabric;
    if (dot(l.frame.z, s.wo) <= Epsilon) {
        pdf = 0.0f;
        return rgb(0);
    }
    V3 o;
    if (f.useDwaFabric) {
        const float sinThetaO = clampf(dot(f.threadDirection, s.wo), -.99f, .99f), thetaO = asinf(sinThetaO);
        float thetaH = asinf(1.0f - powf(r1, 1.0f / (f.specularExponent + 1.0f)));
        if (r2 < 0.5f) thetaH *= -1.0f;
        const float thetaI = 2.0f * thetaH - thetaO;
        float sI, cI, sP, cP;
        sincosf2(thetaI, &sI, &cI);
        sincosf2(Pi * r2, &sP, &cP);
        o = {sI, cI * cP, cI * sP};
    } else {
        const float thetaO = safeAcos(clampf(dot(f.threadDirection, s.wo), -.99f, .99f));
        const float thetaD = safeAcos(powf(r1, 1 / (f.specularExponent + 1)));
        float thetaIP = thetaO + thetaD;
        if (thetaIP >= Pi) thetaIP = thetaO - thetaD;
        if (thetaD < thetaO && r2 < 0.5f) thetaIP = thetaO - thetaD;
        float sI, cI, sP, cP;
        sincosf2(thetaIP, &sI, &cI);
        sincosf2(Pi * r2, &sP, &cP);
        o = {-cI, sI * cP, sI * sP};
    }
    wi = normalize(localToGlobal(l.frame, o));
    return evalFabric(b, l, s, wi, pdf);
}
X2_HD inline Color evalVelvet(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    pdf = 0.0f;
    const FabricParams& f = l.fabric;
    const V3 N = l.frame.z;
    const float cosNO = dot(N, s.wo);
    if (cosNO <= Epsilon) return rgb(0);
    const float cosNI = dot(N, wi);
    if (cosNI <= Epsilon) return rgb(0);
    V3 H;
    if (!computeNormalizedHalfVector(s.wo, wi, H)) return rgb(0);
    const float cosNH = clampf(dot(N, H), -0.99f, 0.99f), sinNH = sqrtf(1.0f - cosNH * cosNH);
    const float velvet = f.normalization * powf(sinNH, f.specularExponent) * cosNI;
    pdf = cosNI * OneOverPi;
    return scaleAndFresnel(b, l, cosNO) * velvet * f.color * (s.includeCosine ? cosNI : 1.0f);
}

//----------------------------------------------------------------------------
// A base (unwrapped) lobe.
// BsdfFlatDiffuse.ispc: Fujii's Oren-Nayar with a terminator shift, and the normal bent toward the light by flatness.
X2_HD inline float orenNayarFalloff(V3 n, V3 v, V3 l, float a, float b, float terminatorShift) {
    const float nl = fmaxf(0.0f, cosf(fminf(HalfPi, dwAcos(clampf(dot(n, l), -1.0f, 1.0f)) * terminatorShift)));
    const float nv = fmaxf(dot(n, v), 0.0f);
    const float s = dot(l, v) - nl * nv;
    float t = 1.0f;
    if (s > 0.0f) t = fmaxf(nl, nv) + Epsilon;
    return nl * (a + b * s / t);
}
X2_CALL Color evalFlatDiffuse(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const V3 N = l.frame.z;
    const float terminatorShift = l.diffuse.terminatorShift + 1.0f;
    const float theta = fminf(HalfPi, terminatorShift * dwAcos(clampf(dot(N, wi), -1.0f, 1.0f)));
    const float a = 1.0f - l.diffuse.flatnessFalloff;
    const float bb = 1.0f + a * a * a * a * 100.0f;
    const float c = HalfPi / bb;
    const float d = c - HalfPi;
    const float t = (theta > HalfPi - c) ? cosf((theta + d) * bb) : 1.0f;
    const float flatness = l.diffuse.flatness * t;
    const V3 flatN = normalize(N + (wi - N) * flatness);
    const float cosWi = orenNayarFalloff(flatN, s.wo, wi, l.diffuse.A, l.diffuse.B, terminatorShift);
    pdf = cosWi * OneOverPi;
    const bool refl = (l.type & Reflection) != 0;
    float cosWo = 1.0f;
    if (l.fresnel != NoIndex) cosWo = fmaxf(dot(refl ? flatN : -flatN, s.wo), 0.0f);
    const float Gs = refl ? shadowTerminatorFix(s, flatN, wi) : 1.0f;
    const Color result = l.diffuse.albedo * OneOverPi * Gs * scaleAndFresnel(b, l, cosWo) * (s.includeCosine ? cosWi : 1.0f);
    // An ad hoc normalization against the energy flatness loses.
    return result * lerpf(1.0f, 0.75f, biasf(l.diffuse.flatness, 0.75f));
}
// ToonBsdfLobe_eval: the ramp at 1 - cos(wi), flat (no cosine), over 2 pi.
X2_CALL Color evalToon(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    V3 N = l.frame.z;
    if (l.toon.extendRamp && dot(N, wi) < 0) N = normalize(lerp(cross(wi, cross(N, wi)), wi, Epsilon));
    const float cosThetaWi = dot(N, wi);
    pdf = fmaxf(cosThetaWi, 0.0f) * OneOverPi;
    float cosThetaWo = 1.0f;
    if (l.fresnel != NoIndex) cosThetaWo = fmaxf(dot(N, s.wo), 0.0f);
    const Color ramp = l.toon.ramp < b.rampCount ? rampEval(b.ramps[l.toon.ramp], (1.0f - cosThetaWi) / l.toon.rampInputScale) : rgb(0);
    const Color albedo = clamp(l.toon.albedo * ramp, 0.0f, 1.0f);
    // MOONRAY_MODO_TOON_TERMINATOR: cut off by the shading normal alone, not faded by the faces'.
    const float Gs = (l.flags & FlagModoToon) ? (cosThetaWi > 0.0f ? 1.0f : 0.0f) : shadowTerminatorFix(s, N, wi);
    return Gs * albedo * scaleAndFresnel(b, l, cosThetaWo) * OneOverTwoPi;
}
X2_HD inline V3 toonRotateVector(V3 v, V3 axis, float theta) {
    const float ct = cosf(theta), st = sinf(theta);
    return ct * v + st * cross(axis, v) + dot(axis, v) * (1.f - ct) * axis;
}
// ToonSpecularBsdfLobe_eval: the normal turned by the stretches, a ramp over the reflection's angle.
X2_CALL Color evalToonSpecular(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const ToonParams& t = l.toon;
    V3 N = l.frame.z;
    const V3 wo = s.wo;
    V3 R = wi - 2.0f * dot(wi, N) * N;
    const float rotU = clampf(t.stretchU * (dot(R, t.dPds) + dot(wo, t.dPds)), -0.5f, 0.5f);
    N = toonRotateVector(N, t.dPdt, rotU);
    const float rotV = clampf(-t.stretchV * (dot(R, t.dPdt) + dot(wo, t.dPdt)), -0.5f, 0.5f);
    N = toonRotateVector(N, t.dPds, rotV);
    const float cosNO = dot(N, wo), cosNI = dot(N, wi);
    pdf = 0.0f;
    if (cosNO <= 0.0f || cosNI <= 0.0f) return rgb(0);
    R = wi - 2.0f * dot(wi, N) * N;
    const float thetaRO = powf(1.0f - clampf(dot(-wo, R), 0.0f, 1.0f), 0.56f);
    if (thetaRO <= 0.0f) return rgb(0);
    const float ramp = t.ramp < b.rampCount ? rampEval(b.ramps[t.ramp], thetaRO / t.rampInputScale).x : 0.0f;
    pdf = 0.5f * OneOverPi * ramp;
    float cosThetaWo = 1.0f;
    if (l.fresnel != NoIndex) cosThetaWo = fmaxf(dot(N, s.wo), 0.0f);
    const Color f = lerp(l.scale, t.normalization * scaleAndFresnel(b, l, cosThetaWo), t.fresnelBlend);
    return ramp * t.intensity * t.tint * OneOverPi * f;
}
// HairToonSpecularBsdfLobe: its embedded hair R lobes (no Fresnel, white scale), the direct one's value through the
// ramp by its luminance and tinted; sampled by the indirect one when indirect reflections are on. Its own scale and
// Fresnel weigh only its albedo.
X2_HD inline Lobe hairToonR(const Lobe& l, U32 comp) {
    Lobe h;
    h.kind = KindHairR;
    h.type = Reflection | Glossy;
    h.flags = FlagSpherical | FlagHair | FlagIgnoresIncomingDifferentials;
    h.frame = l.frame;
    h.hair = HairParams{};
    h.hair.record = l.hairToon.record;
    h.hair.dDFactor = comp ? l.hairToon.dDFactor : 0.0f;
    return h;
}
X2_CALL Color evalHairToonSpecular(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const Lobe h = hairToonR(l, 0);
    const Color hairEval = hair::evalSeparate(b, h, s, wi, pdf, 0);
    const float ramp = l.hairToon.ramp < b.rampCount ? rampEval(b.ramps[l.hairToon.ramp], luminance(hairEval)).x : 0.0f;
    return l.hairToon.tint * ramp * l.hairToon.intensity * OneOverPi;
}
X2_CALL Color sampleHairToonSpecular(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    if (!l.hairToon.enableIndirect) {
        pdf = 0.0f;
        return rgb(0);
    }
    const Lobe h = hairToonR(l, 1);
    return hair::sampleSeparate(b, h, s, r1, r2, wi, pdf, 1) * l.hairToon.indirectIntensity;
}
X2_CALL Color baseEval(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    switch (l.kind) {
    case KindLambert: {
        const V3 N = l.frame.z;
        const bool refl = (l.type & Reflection) != 0;
        const float cosWi = fmaxf(dot(N, wi), 0.0f);
        pdf = cosWi * OneOverPi;
        float cosWo = 1.0f;
        if (l.fresnel != NoIndex) cosWo = fmaxf(dot(refl ? N : -N, s.wo), 0.0f);
        const float Gs = refl ? shadowTerminatorFix(s, N, wi) : 1.0f;
        return Gs * l.diffuse.albedo * scaleAndFresnel(b, l, cosWo) * OneOverPi * (s.includeCosine ? cosWi : 1.0f);
    }
    case KindOrenNayar: {
        const V3 N = l.frame.z;
        const bool refl = (l.type & Reflection) != 0;
        const float nl = fmaxf(dot(N, wi), 0.0f), nv = fmaxf(dot(N, s.wo), 0.0f), sv = dot(wi, s.wo) - nl * nv;
        const float t = sv > 0.0f ? fmaxf(nl, nv) + Epsilon : 1.0f;
        const float cosWi = nl * (l.diffuse.A + l.diffuse.B * sv / t);
        pdf = cosWi * OneOverPi;
        float cosWo = 1.0f;
        if (l.fresnel != NoIndex) cosWo = fmaxf(dot(refl ? N : -N, s.wo), 0.0f);
        const float Gs = refl ? shadowTerminatorFix(s, N, wi) : 1.0f;
        return l.diffuse.albedo * OneOverPi * Gs * scaleAndFresnel(b, l, cosWo) * (s.includeCosine ? cosWi : 1.0f);
    }
    case KindFlatDiffuse: return evalFlatDiffuse(b, l, s, wi, pdf);
    case KindToon: return evalToon(b, l, s, wi, pdf);
    case KindToonSpecular: return evalToonSpecular(b, l, s, wi, pdf);
    case KindCookTorrance: return evalBeckmann(b, l, s, wi, pdf);
    case KindGGX: return evalGGX(b, l, s, wi, pdf);
    case KindAnisoCookTorrance: return evalAniso(b, l, s, wi, pdf);
    case KindBerryCookTorrance: return evalBerry(b, l, s, wi, pdf);
    case KindGlitterGGX: return evalGlitter(b, l, s, wi, pdf);
    case KindTransmissionCookTorrance: return evalTransmissionCT(b, l, s, wi, l.ct.etaT, pdf);
    case KindRetroreflection: return evalRetro(b, l, s, wi, pdf);
    case KindEyeCaustic: return evalEyeCaustic(b, l, s, wi, pdf);
    case KindFabric: return evalFabric(b, l, s, wi, pdf);
    case KindVelvet: return evalVelvet(b, l, s, wi, pdf);
    case KindHairOneSampler: return hair::evalOneSampler(b, l, s, wi, pdf);
    case KindHairR:
    case KindHairTRT:
    case KindHairTT:
    case KindHairTRRT: return hair::evalSeparate(b, l, s, wi, pdf);
    case KindHairDiffuse: return hair::evalHairDiffuse(l, s, wi, pdf);
    case KindStochasticFlakes: return flakes::eval(b, l, s, wi, pdf);
    case KindHairToonSpecular: return evalHairToonSpecular(b, l, s, wi, pdf);
    default: pdf = 0.0f; return rgb(0);  // the mirrors
    }
}
X2_CALL Color baseSample(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    switch (l.kind) {
    case KindLambert:
    case KindOrenNayar:
    case KindFlatDiffuse:
    case KindVelvet:
    case KindToon:
        wi = localToGlobal(l.frame, sampleLocalHemisphereCosine(r1, r2));
        return baseEval(b, l, s, wi, pdf);
    case KindToonSpecular:
        // Its indirect reflections' GGX lobe, when on; else no sample.
        if (l.toon.enableIndirect && l.toon.indirect < b.recordCount)
            return sampleGGX(b, b.records[l.toon.indirect], s, r1, r2, wi, pdf) * l.toon.indirectIntensity;  // no recursion (OptiX)
        pdf = 0.0f;
        return rgb(0);
    case KindCookTorrance: return sampleBeckmann(b, l, s, r1, r2, wi, pdf);
    case KindGGX: return sampleGGX(b, l, s, r1, r2, wi, pdf);
    case KindAnisoCookTorrance: return sampleAniso(b, l, s, r1, r2, wi, pdf);
    case KindBerryCookTorrance: return sampleBerry(b, l, s, r1, r2, wi, pdf);
    case KindGlitterGGX: return sampleGlitter(b, l, s, r1, r2, wi, pdf);
    case KindTransmissionCookTorrance: return sampleTransmissionCT(b, l, s, r1, r2, wi, pdf);
    case KindMirrorReflection: return sampleMirrorReflection(b, l, s, wi, pdf);
    case KindMirrorTransmission: return sampleMirrorTransmission(b, l, s, r1, wi, pdf);
    case KindMirrorRetroreflection: {
        wi = s.wo;
        pdf = 1.0f;
        const float c = fabsf(dot(l.frame.z, s.wo));
        return scaleAndFresnel(b, l, c) * (s.includeCosine ? 1.0f : 1.0f / c);
    }
    case KindRetroreflection: return sampleRetro(b, l, s, r1, r2, wi, pdf);
    case KindEyeCaustic: return sampleEyeCaustic(b, l, s, r1, r2, wi, pdf);
    case KindFabric: return sampleFabric(b, l, s, r1, r2, wi, pdf);
    case KindHairOneSampler: return hair::sampleOneSampler(b, l, s, r1, r2, wi, pdf);
    case KindHairR:
    case KindHairTRT:
    case KindHairTT:
    case KindHairTRRT: return hair::sampleSeparate(b, l, s, r1, r2, wi, pdf);
    case KindHairDiffuse: return hair::sampleHairDiffuse(l, s, r1, r2, wi, pdf);
    case KindStochasticFlakes: return flakes::sample(b, l, s, r1, r2, wi, pdf);
    case KindHairToonSpecular: return sampleHairToonSpecular(b, l, s, r1, r2, wi, pdf);
    default: pdf = 0.0f; return rgb(0);
    }
}
X2_CALL Color baseAlbedo(const Bsdf& b, const Lobe& l, const Slice& s) {
    const V3 N = l.kind == KindEyeCaustic ? l.eye.Ng : l.frame.z;
    switch (l.kind) {
    case KindLambert:
    case KindOrenNayar:
    case KindFlatDiffuse: return scaleAndFresnel(b, l, fmaxf(dot(N, s.wo), 0.0f)) * l.diffuse.albedo;
    case KindToon: return scaleAndFresnel(b, l, fmaxf(dot(N, s.wo), 0.0f)) * l.toon.albedo;  // LambertBsdfLobe_albedo
    case KindMirrorReflection:
    case KindMirrorRetroreflection: return scaleAndFresnel(b, l, fabsf(dot(N, s.wo)));
    case KindMirrorTransmission: return l.mirror.tint * scaleAndFresnel(b, l, fabsf(dot(N, s.wo)));
    case KindTransmissionCookTorrance: return scaleAndFresnel(b, l, fmaxf(dot(N, s.wo), 0.0f));
    case KindEyeCaustic: return l.eye.causticColor * scaleAndFresnel(b, l, fmaxf(dot(N, s.wo), 0.0f));
    case KindVelvet: {
        const float c = fmaxf(dot(N, s.wo), 0.0f);
        return scaleAndFresnel(b, l, c) * l.fabric.color * velvetAlbedoAt(c, l.fabric.roughness);
    }
    case KindHairOneSampler:
    case KindHairR:
    case KindHairTRT:
    case KindHairTT:
    case KindHairTRRT: return l.scale;  // HairBsdfLobe_albedo
    case KindHairDiffuse: return hair::albedoHairDiffuse(l, s);
    default: return scaleAndFresnel(b, l, fmaxf(dot(N, s.wo), 0.0f));
    }
}
// The lobes' differentials functions: dDdx/dDdy in, the scattered ones out.
X2_CALL void baseDifferentials(const Lobe& l, V3 wo, V3 wi, float r1, float r2, V3 dNdx, V3 dNdy, V3& dDdx, V3& dDdy) {
    switch (l.kind) {
    case KindLambert:
    case KindOrenNayar:
    case KindFlatDiffuse:
    case KindToon:
        localHemisphereCosineDifferentials(r1, r2, dDdx, dDdy);
        squarifyRectangle(dDdx, dDdy);
        dDdx = localToGlobal(l.frame, dDdx);
        dDdy = localToGlobal(l.frame, dDdy);
        return;
    case KindCookTorrance:
    case KindGGX:
    case KindAnisoCookTorrance:
    case KindBerryCookTorrance:
    case KindGlitterGGX: {
        V3 H;
        if (!computeNormalizedHalfVector(wo, wi, H)) H = l.frame.z;
        reflectionDifferential(wo, wi, H, dNdx, dNdy, dDdx, dDdy);
        dDdx = dDdx * l.ct.dDFactor;
        dDdy = dDdy * l.ct.dDFactor;
        return;
    }
    case KindTransmissionCookTorrance: {
        V3 H;
        if (computeNormalizedRefractionHalfVector(l.ct.etaI, wo, l.ct.etaT, wi, H)) {
            if (l.ct.etaI > l.ct.etaT) H = -H;
        } else {
            H = l.frame.z;
        }
        refractionDifferential(l.ct.neta, wo, wi, H, dNdx, dNdy, dDdx, dDdy);
        dDdx = dDdx * l.ct.dDFactor;
        dDdy = dDdy * l.ct.dDFactor;
        return;
    }
    case KindMirrorReflection: reflectionDifferential(wo, wi, l.frame.z, dNdx, dNdy, dDdx, dDdy); return;
    case KindMirrorTransmission:
        refractionDifferential(l.mirror.etaI / l.mirror.etaT, wo, wi, l.frame.z, dNdx, dNdy, dDdx, dDdy);
        return;
    case KindMirrorRetroreflection:
        dDdx = -dDdx;
        dDdy = -dDdy;
        return;
    case KindRetroreflection:
        dDdx = dDdx * -l.retro.dDFactor;
        dDdy = dDdy * -l.retro.dDFactor;
        return;
    case KindEyeCaustic:
        dDdx = dNdx * l.eye.dDFactor;
        dDdy = dNdy * l.eye.dDFactor;
        return;
    case KindFabric: {
        V3 H;
        if (!computeNormalizedHalfVector(wo, wi, H)) H = l.frame.z;
        reflectionDifferentialNoCurvature(H, dDdx, dDdy);
        dDdx = normalize(dDdx) * l.fabric.dDFactor;
        dDdy = normalize(dDdy) * l.fabric.dDFactor;
        return;
    }
    case KindVelvet: {
        V3 H;
        if (!computeNormalizedHalfVector(wo, wi, H)) H = l.frame.z;
        reflectionDifferentialNoCurvature(H, dDdx, dDdy);
        dDdx = dDdx * l.fabric.dDFactor;
        dDdy = dDdy * l.fabric.dDFactor;
        return;
    }
    case KindHairOneSampler:
    case KindHairR:
    case KindHairTRT:
    case KindHairTT:
    case KindHairTRRT:
    case KindHairDiffuse: hair::differentials(l, wo, wi, dDdx, dDdy); return;
    case KindStochasticFlakes: flakes::differentials(l, wo, wi, dNdx, dNdy, dDdx, dDdy); return;
    case KindHairToonSpecular:
        if (l.hairToon.enableIndirect) hair::differentials(hairToonR(l, 1), wo, wi, dDdx, dDdy);
        return;
    default: return;
    }
}
// BSDF_LOBE_PROPERTY_ROUGHNESS of a base lobe, or false.
X2_HD inline bool baseRoughness(const Lobe& l, float& u, float& v) {
    switch (l.kind) {
    case KindLambert:
    case KindOrenNayar:
    case KindFlatDiffuse:
    case KindToon: u = v = 1.0f; return true;
    case KindCookTorrance:
    case KindGGX:
    case KindBerryCookTorrance:
    case KindGlitterGGX:
    case KindTransmissionCookTorrance: u = v = l.ct.inputRoughness; return true;
    case KindAnisoCookTorrance: u = l.ct.inputRoughness; v = l.ct.inputRoughnessV; return true;
    case KindMirrorReflection:
    case KindMirrorTransmission:
    case KindMirrorRetroreflection: u = v = 0.0f; return true;
    case KindRetroreflection: u = v = l.retro.inputRoughness; return true;
    case KindFabric:
    case KindVelvet: u = v = l.fabric.roughness; return true;
    case KindHairOneSampler:
    case KindHairR:
    case KindHairTRT:
    case KindHairTT:
    case KindHairTRRT:
    case KindHairDiffuse: return hair::roughness(l, u, v);
    case KindStochasticFlakes: u = v = l.flakes.randomness; return true;
    default: return false;
    }
}

//----------------------------------------------------------------------------
// Wrapper chains: a lobe record and the records it wraps, outermost first.
constexpr U32 MaxChain = 8;
struct Chain {
    U32 records[MaxChain];
    U32 depth = 0;
};
// The wrapper kinds by name: lobe kinds added after them (FlatDiffuse, the toon lobes) are base lobes.
X2_HD inline bool isWrapper(U32 kind) {
    return kind == KindUnder || kind == KindUnderClearcoat || kind == KindUnderClearcoatTransmission || kind == KindIridescence;
}
X2_HD inline bool chain(const Bsdf& b, U32 record, Chain& c) {
    c.depth = 0;
    while (record != NoIndex && record < b.recordCount) {
        if (c.depth >= MaxChain) return false;
        c.records[c.depth++] = record;
        const Lobe& l = b.records[record];
        if (!isWrapper(l.kind)) return true;
        record = l.child;
    }
    return false;
}
// UnderBsdfLobe computeTransmission
X2_HD inline Color underTransmission(float thickness, Color attenuationColor, float attenuationWeight, float cos1, float cos2) {
    if (isZero(thickness)) return rgb(1);
    const float rcp1 = !isZero(cos1) ? 1.0f / fabsf(cos1) : 0.0f, rcp2 = !isZero(cos2) ? 1.0f / fabsf(cos2) : 0.0f;
    const float d = thickness * (rcp1 + rcp2);
    return lerp(rgb(1), rgb(powf(attenuationColor.x, d), powf(attenuationColor.y, d), powf(attenuationColor.z, d)),
                attenuationWeight);
}
// The albedo of the chain from level `from` (the wrappers' albedo functions).
X2_CALL Color chainAlbedo(const Bsdf& b, const Chain& c, U32 from, const Slice& s) {
    Color factor = rgb(1);
    for (U32 k = from; k + 1 < c.depth; ++k) {
        const Lobe& w = b.records[c.records[k]];
        if (w.kind == KindIridescence || w.fresnel == NoIndex) continue;  // passes its child's albedo through
        factor = factor * scaleAndFresnel(b, w, fmaxf(dot(w.under.N, s.wo), 0.0f));
    }
    return factor * baseAlbedo(b, b.records[c.records[c.depth - 1]], s);
}
// computeIridescenceColor, tintWithIridescence (BsdfIridescence.ispc).
X2_HD inline float fitInRange(float v, float oldMin, float oldMax, float newMin, float newMax) {
    const float range = oldMax - oldMin;
    if (isZero(range)) return newMin;
    return (newMax - newMin) * (v - oldMin) / range + newMin;
}
X2_CALL Color tintWithIridescence(const Bsdf& b, const IridescenceParams& p, float cosHV, Color lobeColor) {
    if (isBlack(lobeColor)) return rgb(0);
    float index = powf(fabsf(1.f - cosHV), p.exponent) * p.thickness;
    index = fmodf(index, 1.f);
    Color iri;
    if (p.colorControl == 0) {
        if (isEqual(p.primary.x, p.secondary.x) && isEqual(p.primary.y, p.secondary.y) && isEqual(p.primary.z, p.secondary.z)) {
            if (p.flipHue) iri = p.primary;
            else {
                const float h = rgbToHue(p.primary);
                iri = hueToRgb(fitInRange(index, 0.f, 1.f, h, h + 1.f));
            }
        } else {
            float hp = rgbToHue(p.primary), hs = rgbToHue(p.secondary);
            if (hs < hp && !p.flipHue) hs = hs + 1.f;
            else if (hp < hs && p.flipHue) hp = hp + 1.f;
            const float back = 1.f / (fabsf(hs - hp) / 0.166667f + 1.f), spectrum = 1.f - back;
            const float clamped = fitInRange(index, 0.f, spectrum, hp, hs);
            iri = index < spectrum ? hueToRgb(clamped) : lerp(hueToRgb(hs), hueToRgb(hp), (index - spectrum) / back);
        }
    } else {
        iri = p.ramp < b.rampCount ? evalColorRamp(b.ramps[p.ramp], index) : rgb(1);
    }
    const float att = saturate(lerpf(p.at90, p.at0, cosHV));
    iri = lerp(rgb(1), iri, att * p.iridescence);
    return lobeColor * iri;
}
X2_HD inline bool averageHalfCosines(V3 wo, V3 wi, float& avg) {
    V3 m;
    if (!computeNormalizedHalfVector(wo, wi, m)) return false;
    avg = (dot(m, wo) + dot(m, wi)) * 0.5f;
    return true;
}

// Per wrapper level of an evaluation: the slice handed inward and the cosines
// the wrapper needs on the way out.
struct Level {
    Slice inner;
    float cosWo, cosWoPrime;
    V3 wiInner;
};

// BsdfLobe_eval of a lobe record, wrappers and all.
X2_CALL Color lobeEval(const Bsdf& b, U32 record, const Slice& s, V3 wi, float& pdf) {
    pdf = 0.0f;
    Chain c;
    if (!chain(b, record, c)) return rgb(0);
    Level lv[MaxChain];
    Slice cur = s;
    V3 curWi = wi;
    U32 active = c.depth - 1;  // levels 0..active-1 are wrappers that act
    for (U32 k = 0; k + 1 < c.depth; ++k) {
        const Lobe& w = b.records[c.records[k]];
        Level& L = lv[k];
        L.inner = cur;
        L.wiInner = curWi;
        if (w.kind == KindIridescence) {
            if (b.records[w.child].type & Mirror) {
                pdf = 0.0f;
                return rgb(0);
            }
            continue;
        }
        if (w.fresnel == NoIndex) continue;  // inactive: the child's evaluation as it is
        if (w.kind == KindUnder) {
            L.cosWo = fmaxf(dot(w.under.N, cur.wo), 0.0f);
            continue;
        }
        V3 woPrime;
        float cosWo, cosWoPrime;
        if (!computeRefractionDirection(w.under.N, cur.wo, w.under.neta, woPrime, cosWo, cosWoPrime)) return rgb(0);
        L.cosWo = cosWo;
        L.cosWoPrime = cosWoPrime;
        L.inner.wo = -woPrime;
        if (w.kind == KindUnderClearcoat) {
            V3 wiPrime;
            float cosWi, cosWiPrime;
            if (!computeRefractionDirection(w.under.N, curWi, w.under.neta, wiPrime, cosWi, cosWiPrime)) return rgb(0);
            L.wiInner = -wiPrime;
        }
        cur = L.inner;
        curWi = L.wiInner;
    }
    (void)active;
    Color result = baseEval(b, b.records[c.records[c.depth - 1]], cur, curWi, pdf);
    for (int k = int(c.depth) - 2; k >= 0; --k) {
        const Lobe& w = b.records[c.records[k]];
        const Level& L = lv[k];
        // The slice and direction this level received.
        const Slice& outer = k == 0 ? s : lv[k - 1].inner;
        const V3 outerWi = k == 0 ? wi : lv[k - 1].wiInner;
        if (w.kind == KindIridescence) {
            float avg;
            if (!averageHalfCosines(outer.wo, outerWi, avg)) return rgb(0);
            result = tintWithIridescence(b, w.iri, avg, result) * scaleAndFresnel(b, w, avg);
            continue;
        }
        if (w.fresnel == NoIndex) continue;
        if (w.kind == KindUnder) {
            const float cosWi = fmaxf(dot(w.under.N, outerWi), 0.0f);
            result = result * scaleAndFresnel(b, w, L.cosWo) *
                     underTransmission(w.under.thickness, w.under.attenuationColor, w.under.attenuationWeight, L.cosWo, cosWi);
        } else if (w.kind == KindUnderClearcoatTransmission) {
            result = result * scaleAndFresnel(b, w, L.cosWo) *
                     underTransmission(w.under.thickness, w.under.attenuationColor, w.under.attenuationWeight, L.cosWoPrime, 0.0f);
        } else {  // KindUnderClearcoat
            V3 wiPrime;
            float cosWi, cosWiPrime;
            computeRefractionDirection(w.under.N, outerWi, w.under.neta, wiPrime, cosWi, cosWiPrime);
            result = result * scaleAndFresnel(b, w, L.cosWo);
            const Color ct = underTransmission(w.under.thickness, w.under.attenuationColor, w.under.attenuationWeight,
                                               L.cosWoPrime, cosWiPrime);
            const Color Fr = fresnelEval(b.fresnels, w.under.exitingFresnel, L.cosWoPrime), Ft = rgb(1) - Fr;
            const Color albedo = chainAlbedo(b, c, U32(k) + 1, L.inner);
            result = (result * ct * Ft) / cmax(rgb(1) - ct * Fr * albedo, rgb(0.01f));
            float jacobian = fabsf(cosWi) / fmaxf(fabsf(cosWiPrime), 0.01f);
            if (b.records[w.child].type & Glossy) jacobian *= w.under.neta * w.under.neta;
            pdf *= jacobian;
            result = result * jacobian;
        }
    }
    return result;
}

// BsdfLobe_sample of a lobe record, wrappers and all.
X2_CALL Color lobeSample(const Bsdf& b, U32 record, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    pdf = 0.0f;
    Chain c;
    if (!chain(b, record, c)) return rgb(0);
    Level lv[MaxChain];
    Slice cur = s;
    for (U32 k = 0; k + 1 < c.depth; ++k) {
        const Lobe& w = b.records[c.records[k]];
        Level& L = lv[k];
        L.inner = cur;
        if (w.kind == KindIridescence || w.fresnel == NoIndex) continue;
        if (w.kind == KindUnder) {
            L.cosWo = fmaxf(dot(w.under.N, cur.wo), 0.0f);
            continue;
        }
        V3 woPrime;
        float cosWo, cosWoPrime;
        if (!computeRefractionDirection(w.under.N, cur.wo, w.under.neta, woPrime, cosWo, cosWoPrime)) return rgb(0);
        L.cosWo = cosWo;
        L.cosWoPrime = cosWoPrime;
        L.inner.wo = -woPrime;
        cur = L.inner;
    }
    Color result = baseSample(b, b.records[c.records[c.depth - 1]], cur, r1, r2, wi, pdf);
    for (int k = int(c.depth) - 2; k >= 0; --k) {
        const Lobe& w = b.records[c.records[k]];
        const Level& L = lv[k];
        const Slice& outer = k == 0 ? s : lv[k - 1].inner;
        if (w.kind == KindIridescence) {
            if (b.records[w.child].type & Mirror) {
                const float cosNV = dot(w.iri.N, outer.wo);
                result = tintWithIridescence(b, w.iri, cosNV, result) * scaleAndFresnel(b, w, cosNV);
            } else {
                float avg;
                if (!averageHalfCosines(outer.wo, wi, avg)) return rgb(0);
                result = tintWithIridescence(b, w.iri, avg, result) * scaleAndFresnel(b, w, avg);
            }
            continue;
        }
        if (w.fresnel == NoIndex) continue;
        if (w.kind == KindUnder) {
            const float cosWi = fmaxf(dot(w.under.N, wi), 0.0f);
            result = result * scaleAndFresnel(b, w, L.cosWo) *
                     underTransmission(w.under.thickness, w.under.attenuationColor, w.under.attenuationWeight, L.cosWo, cosWi);
        } else if (w.kind == KindUnderClearcoatTransmission) {
            result = result * scaleAndFresnel(b, w, L.cosWo) *
                     underTransmission(w.under.thickness, w.under.attenuationColor, w.under.attenuationWeight, L.cosWoPrime, 0.0f);
        } else {  // KindUnderClearcoat: the sampled direction leaves through the coat
            if (isZero(pdf)) return rgb(0);
            const V3 wiPrime = wi;
            float cosWi, cosWiPrime;
            V3 out;
            if (!computeRefractionDirection(w.under.N, wiPrime, 1.0f / w.under.neta, out, cosWiPrime, cosWi)) {
                if (w.under.passThroughTIR) {
                    out = wiPrime;
                    cosWi = cosWiPrime;
                } else {
                    pdf = 0.0f;
                    return rgb(0);
                }
            } else {
                out = -out;
            }
            wi = out;
            result = result * scaleAndFresnel(b, w, L.cosWo);
            const Color ct = underTransmission(w.under.thickness, w.under.attenuationColor, w.under.attenuationWeight,
                                               L.cosWoPrime, cosWiPrime);
            const Color Fr = fresnelEval(b.fresnels, w.under.exitingFresnel, L.cosWoPrime), Ft = rgb(1) - Fr;
            const Color albedo = chainAlbedo(b, c, U32(k) + 1, L.inner);
            result = (result * ct * Ft) / cmax(rgb(1) - ct * Fr * albedo, rgb(0.01f));
            float jacobian = fabsf(cosWi) / fmaxf(fabsf(cosWiPrime), 0.01f);
            if (b.records[w.child].type & Glossy) jacobian *= w.under.neta * w.under.neta;
            pdf *= jacobian;
            result = result * jacobian;
        }
    }
    return result;
}
X2_HD inline Color lobeAlbedo(const Bsdf& b, U32 record, const Slice& s) {
    Chain c;
    if (!chain(b, record, c)) return rgb(0);
    return chainAlbedo(b, c, 0, s);
}
X2_HD inline const Lobe& baseLobe(const Bsdf& b, U32 record) {
    Chain c;
    chain(b, record, c);
    return b.records[c.records[c.depth ? c.depth - 1 : 0]];
}
X2_HD inline void lobeDifferentials(const Bsdf& b, U32 record, V3 wo, V3 wi, float r1, float r2, V3 dNdx, V3 dNdy, V3& dDdx,
                                    V3& dDdy) {
    const Lobe& l = baseLobe(b, record);
    if (l.kind == KindToonSpecular) {
        // Its indirect reflections' lobe's, when on; else the incoming ones unchanged.
        if (l.toon.enableIndirect && l.toon.indirect < b.recordCount)
            baseDifferentials(b.records[l.toon.indirect], wo, wi, r1, r2, dNdx, dNdy, dDdx, dDdy);
        return;
    }
    baseDifferentials(l, wo, wi, r1, r2, dNdx, dNdy, dDdx, dDdy);
}
X2_HD inline bool lobeRoughness(const Bsdf& b, U32 record, float& u, float& v) {
    return baseRoughness(baseLobe(b, record), u, v);
}
}}}
