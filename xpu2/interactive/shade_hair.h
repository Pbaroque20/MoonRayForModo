// Private XPU2 shading library, shared CPU/CUDA: MoonRay's hair lobes (shading/ispc/bsdf/hair: HairUtil,
// HairState, BsdfHair, BsdfHairLobes, BsdfHairOneSampler, BsdfHairDiffuse). Derived from MoonRay Apache-2.0,
// Copyright 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
//
// A hair lobe's parameters are a record in its Bsdf's hair pool (shade_lobes.h HairRecord): the one-sampler lobe
// reads all four of its components, each separate lobe (R, TRT, TT, TRRT) its own. MoonRay's quirks are kept: the
// separate TRT, TT and TRRT lobes have a Fresnel only through the hair attenuator under an R lobe (TRRT without one
// is black), the one-sampler's ray differential factor is always the minimum (its widths start from zero), and the
// differentials' second direction is reflected from the first's result.
#pragma once
#include "shade_lobes.h"
#include "shade_colorcorrect.h"
namespace xpu2 { namespace interactive { namespace shade {
namespace hair {

// HairUtil.isph
constexpr float SqrtPiOver8 = 0.626657069f;
constexpr float DDFactorMin = 0.075f, DDFactorMax = 0.25f;
constexpr float DDFactorSlope = (DDFactorMax - DDFactorMin) / (0.0833f * Pi);
X2_HD inline float pow2(float v) { return v * v; }
X2_HD inline float pow3(float v) { return v * v * v; }
X2_HD inline float pow4(float v) {
    const float p2 = pow2(v);
    return p2 * p2;
}
X2_HD inline float pow20(float v) {
    const float p4 = pow4(v), p8 = p4 * p4, p16 = p8 * p8;
    return p16 * p4;
}
X2_HD inline float pow22(float v) { return pow20(v) * pow2(v); }
X2_HD inline float safeSqrt(float x) { return x > 0 ? sqrtf(x) : 0.0f; }
X2_HD inline float sqr(float x) { return x * x; }
X2_HD inline float sinhOf(float x) { return (expf(x) - expf(-x)) / 2; }
X2_HD inline float longitudinalVar(float r) { return sqr(0.726f * r + 0.812f * r * r + 3.7f * pow20(r)); }
X2_HD inline float azimuthalVar(float r) {
    const float v = SqrtPiOver8 * (0.265f * r + 1.194f * r * r + 5.372f * pow22(r));
    return fmaxf(v, 0.05f);
}
X2_HD inline Color absorptionCoefficients(Color hairColor, float aziRoughness) {
    Color sigmaA = rgb(0);
    const float p3 = pow3(aziRoughness), p4 = p3 * aziRoughness, p5 = p4 * aziRoughness;
    const float denom = 5.969f - 0.215f * aziRoughness + 2.532f * sqr(aziRoughness) - 10.73f * p3 + 5.574f * p4 + 0.245f * p5;
    if (!isZero(denom)) {
        sigmaA.x = sqr(logf(fmaxf(hairColor.x, Epsilon)) / denom);
        sigmaA.y = sqr(logf(fmaxf(hairColor.y, Epsilon)) / denom);
        sigmaA.z = sqr(logf(fmaxf(hairColor.z, Epsilon)) / denom);
    }
    return sigmaA;
}
X2_HD inline float besselI0(float x) {
    float sum = 0.0f, x2i = 1.0f;
    int ifact = 1, i4 = 1;
    for (int i = 0; i < 10; ++i) {
        if (i > 1) ifact *= i;
        sum += x2i / float(i4) / float(ifact) / float(ifact);
        x2i *= x * x;
        i4 *= 4;
    }
    return sum;
}
X2_HD inline float logBesselI0(float x) {
    if (x > 12.0f) return x + 0.5f * (logf(1.125f / TwoPi) - logf(x));
    return logf(besselI0(x));
}
X2_HD inline float deonLongitudinalM(float variance, float sinThetaI, float cosThetaI, float sinThetaO, float cosThetaO) {
    if (variance < Epsilon) return 0.0f;
    const float oneOverV = 1.0f / variance;
    const float b = sinThetaI * sinThetaO * oneOverV, x = cosThetaI * cosThetaO * oneOverV;
    if (variance <= 0.1f) return expf(logBesselI0(x) - b - oneOverV + 0.6931f + logf(0.5f * oneOverV));
    return 0.5f * oneOverV * expf(-b) * besselI0(x) / sinhOf(oneOverV);
}
X2_HD inline float logisticFunction(float x, float s) {
    x = fabsf(x);
    const float r = -x / s;
    return expf(r) / (s * sqr(1 + expf(r)));
}
X2_HD inline float logisticCDF(float x, float s) { return 1.0f / (1.0f + expf(-x / s)); }
X2_HD inline float trimmedLogisticFunction(float x, float s, float a, float b) {
    return logisticFunction(x, s) / (logisticCDF(b, s) - logisticCDF(a, s));
}
X2_HD inline float sampleTrimmedLogistic(float r, float s, float a, float b) {
    const float k = logisticCDF(b, s) - logisticCDF(a, s);
    const float logisticCdfX = r * k + logisticCDF(a, s);
    float x = 0.0f;
    if (!isZero(logisticCdfX)) x = -s * logf(1.0f / logisticCdfX - 1.0f);
    return clampf(x, a, b);
}
X2_HD inline U32 compact1By1(U32 x) {
    x &= 0x55555555u;
    x = (x ^ (x >> 1)) & 0x33333333u;
    x = (x ^ (x >> 2)) & 0x0f0f0f0fu;
    x = (x ^ (x >> 4)) & 0x00ff00ffu;
    x = (x ^ (x >> 8)) & 0x0000ffffu;
    return x;
}
X2_HD inline void demuxFloat(float f, float out[2]) {
    const U64 v = U64(double(f) * double(1ull << 32));
    out[0] = float(compact1By1(U32(v))) / float(1 << 16);
    out[1] = float(compact1By1(U32(v >> 1))) / float(1 << 16);
}
// Util.isph rangeAngle, roughness2Width; Transcendental.ispc dw_acos.
X2_HD inline float rangeAngle(float angle) {
    while (angle > Pi) angle -= TwoPi;
    while (angle < -Pi) angle += TwoPi;
    return angle;
}
X2_HD inline float roughness2Width(float roughness) {
    const float factor = 55.0f * Pi / 180.0f;
    const float exponent = 2.0f / (roughness * roughness);
    return factor * powf(exponent, -0.8f);
}
X2_HD inline float dwAcos(float x) {
    const float c0 = 1.5707963039207744f, c1 = -0.2145986966117427f, c2 = 0.08897731218991513f, c3 = -0.05016418844436275f;
    const float c4 = 0.030862751448600963f, c5 = -0.017045102007693682f, c6 = 0.006638618338665405f, c7 = -0.0012534570550072417f;
    const float c0t = 1.5707964f, c3t = -0.0501641f;
    if (x >= 0.0f) {
        const float p = c0 + x * (c1 + x * (c2 + x * (c3t + x * (c4 + x * (c5 + x * (c6 + x * c7))))));
        return p * sqrtf(1.0f - x);
    }
    const float p = c0t - x * (c1 - x * (c2 - x * (c3 - x * (c4 - x * (c5 - x * (c6 - x * c7))))));
    return 3.14159265f - p * sqrtf(1.0f + x);
}
X2_HD inline bool isZeroV(V3 v) { return isZero(v.x) && isZero(v.y) && isZero(v.z); }
// Mat4f_rotate(axis, angle) applied to a vector (transformVector: rows).
X2_HD inline V3 rotateAbout(V3 axis, float angle, V3 n) {
    const float s = sinf(angle), c = cosf(angle);
    const V3 v = normalize(axis);
    const float t = 1.0f - c;
    const V3 r0{v.x * v.x * t + c, v.x * v.y * t + v.z * s, v.x * v.z * t - v.y * s};
    const V3 r1{v.y * v.x * t - v.z * s, v.y * v.y * t + c, v.y * v.z * t + v.x * s};
    const V3 r2{v.z * v.x * t + v.y * s, v.z * v.y * t - v.x * s, v.z * v.z * t + c};
    return n.x * r0 + n.y * r1 + n.z * r2;
}

// HairState.isph and HairState.ispc
struct State {
    float eta = 1.0f, etaP = 1.0f, etaPP = 1.0f;
    V3 wo{0, 0, 0}, hairDir{0, 0, 1}, hairNorm{1, 0, 0}, hairBiNorm{0, 1, 0};
    float sinGammaO = 0, cosGammaO = 1, thetaD = 0, phiD = 0, sinThetaD = 0, cosThetaD = 1, cosPhiDOverTwo = 1;
    float phiO = 0, phiI = 0, phiH = 0, thetaO = 0, thetaI = 0, sinThetaI = 0, cosThetaI = 1, sinThetaO = 0, cosThetaO = 1;
    Color sigmaA{0, 0, 0}, absorptionTerm{1, 1, 1};
    bool usingCustomNormal = false;
};
X2_CALL void calculateHairFrame(State& hs, V3 wo, V3 hairDir, float hairRotation, V3 hairNormal) {
    float UdotO = clampf(dot(wo, hairDir), -1.0f, 1.0f);
    hs.hairDir = hairDir;
    if (hs.usingCustomNormal) hs.hairNorm = rotateAbout(hairDir, hairRotation, hairNormal);
    else hs.hairNorm = wo - UdotO * hairDir;
    hs.hairBiNorm = cross(hs.hairNorm, hairDir);
    if (lengthSqr(hs.hairBiNorm) > Epsilon) {
        hs.hairNorm = normalize(hs.hairNorm);
        hs.hairBiNorm = normalize(hs.hairBiNorm);
    } else {
        const Frame f = frame(wo);
        hs.hairNorm = f.x;
        hs.hairBiNorm = f.y;
    }
    hs.thetaO = HalfPi - dwAcos(UdotO);
    hs.sinThetaO = sinf(hs.thetaO);
    hs.cosThetaO = cosf(hs.thetaO);
    if (hs.usingCustomNormal) {
        const V3 proj = normalize(wo - hairDir * dot(wo, hairDir));
        const float cosPhiO = clampf(dot(proj, hs.hairNorm), -1.0f, 1.0f), sinPhiO = clampf(dot(proj, hs.hairBiNorm), -1.0f, 1.0f);
        hs.phiO = atan2f(sinPhiO, cosPhiO);
    } else {
        hs.phiO = 0.0f;
    }
    const float tmp = sqrtf(hs.eta * hs.eta - hs.sinThetaO * hs.sinThetaO);
    hs.etaP = tmp / hs.cosThetaO;
    hs.etaPP = hs.eta * hs.eta * hs.cosThetaO / tmp;
}
X2_HD inline Color absorptionTerm(float h, float eta, Color sigmaA, float etaP, float cosThetaO, float sinThetaO) {
    Color result = rgb(1);
    float cosGammaT = 0.0f;
    if (!isZero(cosThetaO)) {
        const float sinGammaT = h / etaP;
        cosGammaT = safeSqrt(1.0f - sinGammaT * sinGammaT);
    }
    const float sinThetaT = sinThetaO / eta, cosThetaT = safeSqrt(1.0f - sqr(sinThetaT));
    if (!isZero(cosThetaT)) {
        const float k = 2.0f * cosGammaT / cosThetaT;
        result = Color{expf(-sigmaA.x * k), expf(-sigmaA.y * k), expf(-sigmaA.z * k)};
    }
    return result;
}
X2_HD inline void calculateAbsorption(State& hs, float h, float ior, Color sigmaA) {
    hs.absorptionTerm = absorptionTerm(h, ior, sigmaA, hs.etaP, hs.cosThetaO, hs.sinThetaO);
}
X2_HD inline void computeAngles(const State& hs, V3 direction, V3 hairDir, float& outTheta, float& outPhi) {
    const float cosTheta = dot(direction, hairDir);
    outTheta = HalfPi - dwAcos(clampf(cosTheta, -1.0f, 1.0f));
    V3 proj = direction - hairDir * dot(direction, hairDir);
    const float l = lengthSqr(proj);
    if (l <= Epsilon) {
        outPhi = 0.0f;
        return;
    }
    proj = proj / sqrtf(l);
    const float cosPhi = clampf(dot(proj, hs.hairNorm), -1.0f, 1.0f);
    if (hs.usingCustomNormal) outPhi = atan2f(clampf(dot(proj, hs.hairBiNorm), -1.0f, 1.0f), cosPhi);
    else outPhi = dwAcos(cosPhi);  // the azimuth's symmetry: half the range, for evaluation only
}
X2_CALL void updateAngles(State& hs, V3 direction, float phiI, float thetaI) {
    (void)direction;
    hs.thetaI = thetaI;
    hs.phiI = phiI;
    hs.sinThetaI = sinf(thetaI);
    hs.cosThetaI = cosf(thetaI);
    if (hs.usingCustomNormal) {
        const V3 proj = normalize(hs.wo - hs.hairDir * dot(hs.wo, hs.hairDir));
        const float cosPhiO = clampf(dot(proj, hs.hairNorm), -1.0f, 1.0f), sinPhiO = clampf(dot(proj, hs.hairBiNorm), -1.0f, 1.0f);
        hs.phiO = atan2f(sinPhiO, cosPhiO);
    } else {
        hs.phiO = 0.0f;
    }
    hs.phiD = rangeAngle(hs.phiO - hs.phiI);
    hs.phiH = (hs.phiO + hs.phiI) * 0.5f;
    hs.thetaD = fabsf(hs.thetaO - hs.thetaI) * 0.5f;
    hs.cosPhiDOverTwo = cosf(hs.phiD * 0.5f);
    hs.sinThetaD = sinf(hs.thetaD);
    hs.cosThetaD = cosf(hs.thetaD);
    const float tmp = sqrtf(hs.eta * hs.eta - hs.sinThetaD * hs.sinThetaD);
    hs.etaP = tmp / hs.cosThetaD;
    hs.etaPP = hs.eta * hs.eta * hs.cosThetaD / tmp;
}
X2_HD inline V3 localToGlobal(const State& hs, float x, float y, float z) { return x * hs.hairDir + y * hs.hairNorm + z * hs.hairBiNorm; }
// HairState_init with wi (evaluation).
X2_HD inline void initWithWi(State& hs, V3 wo, V3 wi, V3 hairDir, float h, float ior, Color sigmaA, float hairRotation, V3 hairNormal) {
    hs.wo = wo;
    hs.eta = ior;
    hs.sigmaA = sigmaA;
    hs.usingCustomNormal = !isZero(hairRotation) && !isZeroV(hairNormal);
    calculateHairFrame(hs, wo, hairDir, hairRotation, hairNormal);
    computeAngles(hs, wi, hairDir, hs.thetaI, hs.phiI);
    updateAngles(hs, wi, hs.phiI, hs.thetaI);
    calculateAbsorption(hs, h, ior, sigmaA);
    hs.sinGammaO = h;
    hs.cosGammaO = safeSqrt(1.0f - h * h);
}
// HairState_init without wi (sampling).
X2_HD inline void initForSample(State& hs, V3 wo, V3 hairDir, float h, float ior, Color sigmaA, float hairRotation, V3 hairNormal) {
    hs.wo = wo;
    hs.hairDir = hairDir;
    hs.eta = ior;
    hs.sigmaA = sigmaA;
    hs.usingCustomNormal = !isZero(hairRotation) && !isZeroV(hairNormal);
    hs.phiI = 0.0f;
    hs.phiD = 0.0f;
    calculateHairFrame(hs, wo, hairDir, hairRotation, hairNormal);
    calculateAbsorption(hs, h, ior, sigmaA);
    hs.sinGammaO = h;
    hs.cosGammaO = safeSqrt(1.0f - h * h);
}
// HairState_init(wo, hairDir) (the hair diffuse lobe's frame).
X2_HD inline void initFrame(State& hs, V3 wo, V3 hairDir) {
    hs.usingCustomNormal = false;
    calculateHairFrame(hs, wo, hairDir, 0.0f, V3{0, 0, 0});
    hs.sinGammaO = 0.0f;
    hs.cosGammaO = 1.0f;
}

// HairBsdfLobe_evalHairFresnel: the lobe's Fresnel (its pool entry) along the fibre, or the layered cuticles'.
X2_HD inline Color evalHairFresnel(const Bsdf& b, const Lobe& l, const HairRecord& r, const State& hs, float cosTheta) {
    switch (r.fresnelType) {
    case HairFresnelDielectricCylinder: return fresnelEval(b.fresnels, l.fresnel, cosTheta * hs.cosGammaO);
    case HairFresnelLayeredCuticles: {
        // LayeredDielectricFresnel_evalFresnel (no weight)
        float cosThetaI = fminf(fmaxf(hs.cosGammaO, -1.0f), 1.0f);
        const float eta = 1.0f / r.ior, sinThetaTSqr = eta * eta * (1.0f - cosThetaI * cosThetaI);
        if (sinThetaTSqr >= 1.0f) return rgb(1);
        const float cosThetaT = sqrtf(1.0f - sinThetaTSqr);
        cosThetaI = fabsf(cosThetaI);
        const float etaI = r.mediumIor;
        const float sA = etaI * cosThetaI, sB = hs.etaP * cosThetaT, perp = (sA - sB) / (sA + sB), Fs = perp * perp;
        const float pA = hs.etaPP * cosThetaI, pB = etaI * cosThetaT, par = (pA - pB) / (pA + pB), Fp = par * par;
        const float t1 = Fs + (1.0f - Fs) * (1.0f - Fs) * Fs / (1.0f - Fs * Fs);
        const float t2 = Fp + (1.0f - Fp) * (1.0f - Fp) * Fp / (1.0f - Fp * Fp);
        const float F = 0.5f * t1 + 0.5f * t2, n = r.cuticle * F, d = 1.0f + (r.cuticle - 1.0f) * F;
        return rgb(clampf(n / d, 0.0f, 1.0f));
    }
    default: return fresnelEval(b.fresnels, l.fresnel, cosTheta);  // simple longitudinal
    }
}

// HairBaseBsdfLobe: the longitudinal term with the lobe's shift, the azimuthal cosine term, their sampling.
X2_HD inline float baseMTerm(const State& hs, float sinAlpha, float cosAlpha, float variance) {
    const float sinThetaICone = hs.sinThetaI * cosAlpha + hs.cosThetaI * sinAlpha;
    float cosThetaICone = hs.cosThetaI * cosAlpha - hs.sinThetaI * sinAlpha;
    cosThetaICone = fabsf(cosThetaICone);
    return deonLongitudinalM(variance, sinThetaICone, cosThetaICone, hs.sinThetaO, hs.cosThetaO);
}
X2_HD inline float baseNTerm(const State& hs) { return fmaxf(0.0f, 0.25f * hs.cosPhiDOverTwo); }
X2_CALL float baseSampleTheta(float sinAlpha, float cosAlpha, float variance, float r, float thetaO, float& thetaI) {
    float eps[2];
    demuxFloat(r, eps);
    const float sinThetaO = sinf(thetaO), cosThetaO = cosf(thetaO);
    eps[0] = fmaxf(eps[0], 1e-5f);
    const float cosTheta = 1.0f + variance * logf(eps[0] + (1.0f - eps[0]) * expf(-2.0f / variance));
    const float sinTheta = safeSqrt(1.0f - sqr(cosTheta));
    const float cosPhi = cosf(TwoPi * eps[1]);
    float sinThetaI = -cosTheta * sinThetaO + sinTheta * cosPhi * cosThetaO;
    float cosThetaI = safeSqrt(1.0f - sqr(sinThetaI));
    float sinThetaICone = sinThetaI * cosAlpha - cosThetaI * sinAlpha;
    float cosThetaICone = cosThetaI * cosAlpha + sinThetaI * sinAlpha;
    cosThetaICone = fabsf(cosThetaICone);
    sinThetaI = clampf(sinThetaICone, -1.0f, 1.0f);
    cosThetaI = cosThetaICone;
    thetaI = asinf(sinThetaI);
    sinThetaICone = sinThetaI * cosAlpha + cosThetaI * sinAlpha;
    cosThetaICone = cosThetaI * cosAlpha - sinThetaI * sinAlpha;
    return deonLongitudinalM(variance, sinThetaICone, cosThetaICone, sinThetaO, cosThetaO);
}
X2_HD inline float baseSamplePhi(float r2, float phiO, float& phiI) {
    const float sinPhi2 = clampf(2.0f * r2 - 1.0f, -1.0f, 1.0f);
    const float phi = 2.0f * asinf(sinPhi2);
    phiI = rangeAngle(phiO + phi);
    return cosf(phi * 0.5f) * 0.25f;
}
// The TT lobe's azimuth: a trimmed logistic about the back.
X2_HD inline float ttNTerm(const State& hs, float variance) { return trimmedLogisticFunction(rangeAngle(hs.phiD - Pi), variance, -Pi, Pi); }
X2_HD inline float ttSamplePhi(float variance, float r2, float phiO, float& phiI) {
    const float phiD = sampleTrimmedLogistic(r2, variance, -Pi, Pi);
    phiI = rangeAngle(phiO + phiD + Pi);
    return trimmedLogisticFunction(phiD, variance, -Pi, Pi);
}
// BsdfHairLobes.ispc applySaturation (the TT absorption's, toward the back).
X2_HD inline void ttSaturation(float saturation, Color& c, const State& hs) {
    if (isOne(saturation)) return;
    const float x = fabsf(hs.phiD * OneOverPi);
    float t = clampf((x - 0.8f) / 0.2f, 0.0f, 1.0f);
    t = t * t * (3.0f - 2 * t);
    const float s = lerpf(1.0f, saturation, t);
    applySaturation(s, s, s, c.x, c.y, c.z);
    c = Color{clampf(c.x, 0.0f, 1.0f), clampf(c.y, 0.0f, 1.0f), clampf(c.z, 0.0f, 1.0f)};
}
X2_HD inline Color ttAbsorption(const State& hs, Color scale, float saturation) {
    Color c = hs.absorptionTerm;
    ttSaturation(saturation, c, hs);
    return c * scale;
}
X2_HD inline Color trtAbsorption(const State& hs, Color scale) { return scale * hs.absorptionTerm * hs.absorptionTerm; }
// The glint (HairTRTBsdfLobe_evalNTermGlint and its absorption).
X2_HD inline float glintNTerm(const HairRecord& r, const State& hs, float& etaStar, float& etaP, float& trtWeight) {
    if (!r.showGlint) {
        etaStar = etaP = 0.f;
        trtWeight = 1.f;
        return 0.f;
    }
    const float eta = hs.eta, e = r.glintEccentricity;
    const float etaStar1 = 2.f * (eta - 1.f) * e * e - eta + 2.f;
    const float etaStar2 = 2.f * (eta - 1.f) / (e * e) - eta + 2.f;
    etaStar = 0.5f * ((etaStar1 + etaStar2) + cosf(2.f * hs.phiH) * (etaStar1 - etaStar2));
    etaP = safeSqrt(etaStar * etaStar - hs.sinThetaD * hs.sinThetaD) / hs.cosThetaD;
    const float hc = safeSqrt((4.f - etaP * etaP) / 3.f);
    const float gammai = asinf(hc), gammat = asinf(hc / etaP);
    const float phiC = etaP < 2 ? rangeAngle(2.f * 2.f * gammat - 2.f * gammai + 2.f * Pi) : 0.0f;
    const float g0 = trimmedLogisticFunction(0.f, r.glintRoughness, -Pi, Pi);
    const float g1 = trimmedLogisticFunction(rangeAngle(hs.phiD - phiC), r.glintRoughness, -Pi, Pi);
    const float g2 = trimmedLogisticFunction(rangeAngle(hs.phiD + phiC), r.glintRoughness, -Pi, Pi);
    const float w1 = g1 / g0, w2 = g2 / g0;
    trtWeight = 1.f - w1 - w2;
    return w1 * g1 + w2 * g2;
}
X2_HD inline Color glintAbsorption(const HairRecord& r, const State& hs, float etaStar, float etaP) {
    if (!r.showGlint) return rgb(0);
    Color g = absorptionTerm(hs.sinGammaO, etaStar, hs.sigmaA, etaP, hs.cosThetaO, hs.sinThetaO);
    applySaturationWithoutPreservingLuminance(r.glintSaturation, g.x, g.y, g.z);
    return g * g;
}
X2_HD inline Color trtNTermWithAbsorption(const HairRecord& r, const State& hs, Color scale) {
    float etaStar, etaP, trtWeight;
    const float glintN = glintNTerm(r, hs, etaStar, etaP, trtWeight);
    return trtWeight * baseNTerm(hs) * trtAbsorption(hs, scale) + glintN * glintAbsorption(r, hs, etaStar, etaP);
}
X2_HD inline Color trrtCompensation(Color f, Color oneMinusF, Color T) {
    const Color result = oneMinusF * oneMinusF * f * f;
    const Color oneMinusFT = rgb(1) - f * T;
    return result * T * T * T / oneMinusFT;
}

// A separate lobe's terms (HairRBsdfLobe, HairTRTBsdfLobe, HairTTBsdfLobe, HairTRRTBsdfLobe).
X2_HD inline Color separateFresnel(const Bsdf& b, const Lobe& l, const HairRecord& r, const State& hs) {
    const bool hasFresnel = l.fresnel != NoIndex;
    switch (l.kind) {
    case KindHairR: return hasFresnel ? evalHairFresnel(b, l, r, hs, hs.cosThetaD) : rgb(1);
    case KindHairTRT: {
        if (!hasFresnel) return rgb(1);
        const Color F = evalHairFresnel(b, l, r, hs, hs.cosThetaD);
        const Color oneMinusF = r.fresnelType == HairFresnelLayeredCuticles ? rgb(1) - F : F;
        return oneMinusF * oneMinusF * (rgb(1) - oneMinusF);
    }
    case KindHairTT: {
        if (!hasFresnel) return rgb(1);
        const Color F = evalHairFresnel(b, l, r, hs, hs.cosThetaD);
        const Color oneMinusF = r.fresnelType == HairFresnelLayeredCuticles ? rgb(1) - F : F;
        return oneMinusF * oneMinusF;
    }
    default: {  // TRRT
        if (!hasFresnel) return rgb(0);
        const Color oneMinusF = evalHairFresnel(b, l, r, hs, hs.cosThetaD);
        return trrtCompensation(rgb(1) - oneMinusF, oneMinusF, hs.absorptionTerm);
    }
    }
}
X2_HD inline Color separateNTermWithAbsorption(const Lobe& l, const HairRecord& r, const HairComponent& c, const State& hs) {
    switch (l.kind) {
    case KindHairR: return baseNTerm(hs) * l.scale;
    case KindHairTRT: return trtNTermWithAbsorption(r, hs, l.scale);
    case KindHairTT: return ttNTerm(hs, c.azimVariance) * ttAbsorption(hs, l.scale, c.saturation);
    default: return OneOverTwoPi * l.scale;  // TRRT
    }
}
X2_HD inline float separatePhiPdf(const Lobe& l, const HairComponent& c, const State& hs) {
    switch (l.kind) {
    case KindHairTT: return ttNTerm(hs, c.azimVariance);
    case KindHairTRRT: return OneOverTwoPi;
    default: return baseNTerm(hs);
    }
}
X2_CALL Color separateBsdf(const Bsdf& b, const Lobe& l, const HairRecord& r, const HairComponent& c, const State& hs) {
    return separateFresnel(b, l, r, hs) * baseMTerm(hs, c.sinAlpha, c.cosAlpha, c.longVariance) * separateNTermWithAbsorption(l, r, c, hs) *
           c.tint;
}
X2_HD inline bool clampTest(float cosThetaWi) { return fabsf(cosThetaWi) < 1.0f - Epsilon; }
// A separate lobe (its component c[comp]: 0, or a hair toon lobe's indirect 1).
X2_CALL Color evalSeparate(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf, U32 comp = 0) {
    const HairRecord& r = b.hairs[l.hair.record];
    if (!clampTest(dot(wi, r.hairDir))) {
        pdf = 0.0f;
        return rgb(0);
    }
    State hs;
    initWithWi(hs, s.wo, wi, r.hairDir, r.h, r.ior, r.sigmaA, r.hairRotation * r.uv[0], r.hairNormal);
    const HairComponent& c = r.c[comp];
    const Color f = separateBsdf(b, l, r, c, hs);
    pdf = fmaxf(0.0f, separatePhiPdf(l, c, hs) * baseMTerm(hs, c.sinAlpha, c.cosAlpha, c.longVariance));
    return f;
}
X2_CALL Color sampleSeparate(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf, U32 comp = 0) {
    const HairRecord& r = b.hairs[l.hair.record];
    const HairComponent& c = r.c[comp];
    State hs;
    initForSample(hs, s.wo, r.hairDir, r.h, r.ior, r.sigmaA, r.hairRotation * r.uv[0], r.hairNormal);
    float phiI = 0.0f;
    float phiPdf;
    if (l.kind == KindHairTT) phiPdf = ttSamplePhi(c.azimVariance, r2, hs.phiO, phiI);
    else if (l.kind == KindHairTRRT) {
        phiI = Pi * (2.0f * r2 - 1.0f);
        phiPdf = OneOverTwoPi;
    } else phiPdf = baseSamplePhi(r2, hs.phiO, phiI);
    const float sinPhi = sinf(phiI), cosPhi = cosf(phiI);
    float thetaI;
    const float thetaPdf = baseSampleTheta(c.sinAlpha, c.cosAlpha, c.longVariance, r1, hs.thetaO, thetaI);
    const float sinTheta = sinf(thetaI), cosTheta = cosf(thetaI);
    if (!clampTest(cosTheta)) {
        pdf = 0.0f;
        return rgb(0);
    }
    pdf = fmaxf(0.0f, phiPdf * thetaPdf);
    wi = normalize(localToGlobal(hs, sinTheta, cosTheta * cosPhi, cosTheta * sinPhi));
    updateAngles(hs, wi, phiI, thetaI);
    return separateBsdf(b, l, r, c, hs);
}

// HairOneSamplerBsdfLobe: R, TRT, TT and TRRT in one lobe, sampled by their Fresnel-weighted energies.
X2_HD inline void oneSamplerWeights(const Bsdf& b, const Lobe& l, const HairRecord& r, const State& hs, float weights[3], float cdf[3]) {
    const Color fresnel = evalHairFresnel(b, l, r, hs, hs.cosThetaO);
    const Color oneMinusF = cmax(rgb(0), rgb(1) - fresnel);
    float sum = 0.0f;
    weights[0] = weights[1] = weights[2] = 0.0f;
    if (r.c[HairR].show) {
        weights[0] = fmaxf(0.2f, luminance(fresnel * r.c[HairR].tint));
        sum += weights[0];
    }
    if (r.c[HairTRT].show) {
        weights[1] = luminance(fresnel * oneMinusF * oneMinusF * trtAbsorption(hs, r.c[HairTRT].tint));
        sum += weights[1];
    }
    if (r.c[HairTT].show) {
        weights[2] = luminance(oneMinusF * oneMinusF * ttAbsorption(hs, r.c[HairTT].tint, 1.0f));
        sum += weights[2];
    }
    if (!isZero(sum))
        for (int i = 0; i < 3; ++i) weights[i] /= sum;
    cdf[0] = weights[0];
    cdf[1] = cdf[0] + weights[1];
    cdf[2] = cdf[1] + weights[2];
}
X2_HD inline float oneSamplerPdf(const HairRecord& r, const State& hs, const float weights[3]) {
    float pdf = 0.0f;
    if (r.c[HairR].show)
        pdf += weights[0] * baseMTerm(hs, r.c[HairR].sinAlpha, r.c[HairR].cosAlpha, r.c[HairR].longVariance) * baseNTerm(hs);
    if (r.c[HairTRT].show)
        pdf += weights[1] * baseMTerm(hs, r.c[HairTRT].sinAlpha, r.c[HairTRT].cosAlpha, r.c[HairTRT].longVariance) * baseNTerm(hs);
    if (r.c[HairTT].show)
        pdf += weights[2] * baseMTerm(hs, r.c[HairTT].sinAlpha, r.c[HairTT].cosAlpha, r.c[HairTT].longVariance) *
               ttNTerm(hs, r.c[HairTT].azimVariance);
    return fmaxf(0.0f, pdf);
}
X2_CALL Color oneSamplerBsdf(const Bsdf& b, const Lobe& l, const HairRecord& r, const State& hs) {
    Color bsdf = rgb(0);
    const Color fresnel = evalHairFresnel(b, l, r, hs, hs.cosThetaD);
    const Color oneMinusF = rgb(1) - fresnel;
    if (r.c[HairR].show)
        bsdf = bsdf + fresnel * baseMTerm(hs, r.c[HairR].sinAlpha, r.c[HairR].cosAlpha, r.c[HairR].longVariance) *
                          (baseNTerm(hs) * r.c[HairR].tint);
    if (r.c[HairTRT].show)
        bsdf = bsdf + fresnel * oneMinusF * oneMinusF *
                          baseMTerm(hs, r.c[HairTRT].sinAlpha, r.c[HairTRT].cosAlpha, r.c[HairTRT].longVariance) *
                          trtNTermWithAbsorption(r, hs, r.c[HairTRT].tint);
    if (r.c[HairTT].show)
        bsdf = bsdf + oneMinusF * oneMinusF * baseMTerm(hs, r.c[HairTT].sinAlpha, r.c[HairTT].cosAlpha, r.c[HairTT].longVariance) *
                          (ttNTerm(hs, r.c[HairTT].azimVariance) * ttAbsorption(hs, r.c[HairTT].tint, r.c[HairTT].saturation));
    if (r.c[HairTRRT].show) {
        const Color trrt = trrtCompensation(fresnel, oneMinusF, hs.absorptionTerm);
        bsdf = bsdf + trrt * baseMTerm(hs, 0.0f, 1.0f, r.c[HairTRRT].longVariance) * (OneOverTwoPi * rgb(1));
    }
    return bsdf;
}
X2_CALL Color evalOneSampler(const Bsdf& b, const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const HairRecord& r = b.hairs[l.hair.record];
    State hs;
    initWithWi(hs, s.wo, wi, r.hairDir, r.h, r.ior, r.sigmaA, r.hairRotation * r.uv[0], r.hairNormal);
    const Color f = l.scale * oneSamplerBsdf(b, l, r, hs);
    float weights[3], cdf[3];
    oneSamplerWeights(b, l, r, hs, weights, cdf);
    pdf = oneSamplerPdf(r, hs, weights);
    return f;
}
X2_CALL Color sampleOneSampler(const Bsdf& b, const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    const HairRecord& r = b.hairs[l.hair.record];
    if (!r.c[HairR].show && !r.c[HairTT].show && !r.c[HairTRT].show) {
        pdf = 0.0f;
        return rgb(0);
    }
    State hs;
    initForSample(hs, s.wo, r.hairDir, r.h, r.ior, r.sigmaA, r.hairRotation * r.uv[0], r.hairNormal);
    float weights[3], cdf[3];
    oneSamplerWeights(b, l, r, hs, weights, cdf);
    float phiI = 0.0f, thetaI;
    const HairComponent* c;
    if (r1 < cdf[0]) {
        r1 = r1 / weights[0];
        c = &r.c[HairR];
        baseSamplePhi(r2, hs.phiO, phiI);
    } else if (r1 < cdf[1]) {
        r1 = (r1 - cdf[0]) / weights[1];
        c = &r.c[HairTRT];
        baseSamplePhi(r2, hs.phiO, phiI);
    } else {
        r1 = clampf((r1 - cdf[1]) / weights[2], 0.0f, 0.99f);
        c = &r.c[HairTT];
        ttSamplePhi(c->azimVariance, r2, hs.phiO, phiI);
    }
    baseSampleTheta(c->sinAlpha, c->cosAlpha, c->longVariance, r1, hs.thetaO, thetaI);
    const float sinPhi = sinf(phiI), cosPhi = cosf(phiI), sinTheta = sinf(thetaI), cosTheta = cosf(thetaI);
    if (fabsf(cosTheta) > 1.0f - Epsilon) {
        pdf = 0.0f;
        return rgb(0);
    }
    wi = localToGlobal(hs, sinTheta, cosTheta * cosPhi, cosTheta * sinPhi);
    updateAngles(hs, wi, phiI, thetaI);
    pdf = oneSamplerPdf(r, hs, weights);
    return l.scale * oneSamplerBsdf(b, l, r, hs);
}

// HairDiffuseBsdfLobe
X2_HD inline Color hairDiffuseBsdf(const Lobe& l, V3 wo, V3 wi, bool includeCosine) {
    const V3 hairDir = l.hair.dir;
    const V3 a = cross(hairDir, wi), o = cross(hairDir, wo);
    const float denominator = length(a) * length(o);
    if (denominator <= Epsilon) return rgb(0);
    const float kappa = dot(a, o) / denominator;
    const float front = (1.0f + kappa) / 2.0f, back = 1.0f - front;
    Color result = front * l.hair.refl + back * l.hair.trans;
    const float OneOverPiSqr = OneOverPi * OneOverPi;
    if (includeCosine) {
        const float minSin = cosf(90.0f / 180.0f * Pi);
        const float c = dot(hairDir, wi);
        const float sinHI = fmaxf(minSin, sqrtf(fabsf(1 - c * c)));
        result = result * sinHI * OneOverPiSqr;
    } else {
        result = result * OneOverPiSqr;
    }
    return l.scale * result;
}
X2_HD inline Color evalHairDiffuse(const Lobe& l, const Slice& s, V3 wi, float& pdf) {
    const float cosTheta = clampf(dot(wi, l.hair.dir), -1.f, 1.f);
    pdf = sqrtf(1.0f - cosTheta * cosTheta) / (Pi * Pi);
    return hairDiffuseBsdf(l, s.wo, wi, s.includeCosine);
}
X2_HD inline Color sampleHairDiffuse(const Lobe& l, const Slice& s, float r1, float r2, V3& wi, float& pdf) {
    State hs;
    initFrame(hs, s.wo, l.hair.dir);
    const float u = 2.0f * (r1 - 0.5f), v = r2;
    const float sinTheta = u, cosTheta = sqrtf(1.0f - u * u);
    const float phi = v * TwoPi, sinPhi = sinf(phi), cosPhi = cosf(phi);
    wi = normalize(sinTheta * l.hair.dir + (cosTheta * sinPhi) * hs.hairNorm + (cosTheta * cosPhi) * hs.hairBiNorm);
    pdf = cosTheta / (Pi * Pi);
    return hairDiffuseBsdf(l, s.wo, wi, s.includeCosine);
}
X2_HD inline Color albedoHairDiffuse(const Lobe& l, const Slice& s) {
    const float cosTheta = dot(s.wo, l.hair.dir);
    return l.scale * (sqrtf(fabsf(1.0f - cosTheta * cosTheta)) * OneOverPi * OneOverPi);
}
// HairBsdfLobe_computeReflectionDirectionDifferentialNoCurvature, as MoonRay has it: dDdy reflects the new dDdx.
X2_HD inline void reflectionNoCurvature(V3 H, V3& dDdx, V3& dDdy) {
    dDdx = dDdx - 2.0f * (dot(dDdx, H) * H);
    dDdy = dDdx - 2.0f * (dot(dDdy, H) * H);
}
X2_HD inline void differentials(const Lobe& l, V3 wo, V3 wi, V3& dDdx, V3& dDdy) {
    V3 H;
    if (!computeNormalizedHalfVector(wo, wi, H)) H = normalize(wo);  // MoonRay leaves H undefined here
    reflectionNoCurvature(H, dDdx, dDdy);
    if (l.kind == KindHairDiffuse) {
        dDdx = dDdx * 100.0f;
        dDdy = dDdy * 100.0f;
        return;
    }
    dDdx = normalize(dDdx) * l.hair.dDFactor;
    dDdy = normalize(dDdy) * l.hair.dDFactor;
}
// BSDF_LOBE_PROPERTY_ROUGHNESS (kept on the lobe: the one-sampler's R longitudinal and TT azimuthal roughness, a
// separate lobe's own, the diffuse lobe's one).
X2_HD inline bool roughness(const Lobe& l, float& u, float& v) {
    u = l.hair.roughU;
    v = l.hair.roughV;
    return true;
}
}  // namespace hair
}}}
