// Private XPU2: participating media for the asynchronous path tracer, shared by the CPU and CUDA lanes. What MoonRay
// does along a ray through volumes bound to closed meshes (pbr/integrator PathIntegratorVolume.cc:
// collectVolumeIntervals, evalVolumeShaders, evalSigmaT, decoupledRayMarching's homogeneous case), its phase
// function (pbr/core VolumePhase.h), distance and equi-angular sampling (pbr/core Util.h, Distribution.cc's
// GuideDistribution1D) and BaseVolume's coefficients (moonray dso/volume/Base BaseVolume.cc) for volumes whose
// attributes are not bound (homogeneous: one value over each stretch of the ray, its ramps by the stretch's length).
// The integrator's use of them is in async_integrator.h. Derived from MoonRay Apache-2.0, Copyright 2023-2024
// DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "light_core.h"
#include "shade_color.h"

namespace xpu2::interactive::volume {
using surface::V3;
using sample::U32;

constexpr U32 MaxVolumes = 32;    // a scene's volumes: one bit each in a ray's regions
constexpr U32 MaxCrossings = 32;  // crossings collected along one ray
constexpr U32 MaxSteps = MaxCrossings + 2;
constexpr float Epsilon = 1.1920928955078125e-07f;  // scene_rdl2 sEpsilon
constexpr float HitEpsilonStart = 1e-5f;            // pbr sHitEpsilonStart
constexpr float FarLimit = 0.999f * lights::DistantDistance;  // sHitEpsilonEnd * sDistantLightDistance
enum OverlapMode : U32 { OverlapSum = 0, OverlapMax = 1, OverlapRnd = 2 };
enum ShaderFlags : U32 { UseAttenuationRamp = 1, UseAlbedoRamp = 2, MatchAlbedo = 4, InvertAttenuation = 8 };

// A BaseVolume with no bound attributes: its attenuation and albedo (diffuse) colours and their ramps over the depth
// a ray travels through it, its density ramp, the attenuation's intensity and factor, its anisotropy, and the lights
// its assignment's light set lets light it.
struct Shader {
    V3 attenuationColor, albedoColor;
    float intensity, factor, g;
    U32 flags, lightMask;
    float attenuationMin, attenuationMax, albedoMin, albedoMax, densityMin, densityMax;
    shade::ColorRamp attenuationRamp, albedoRamp;
    shade::FloatRamp densityRamp;
};
// A ray's crossing of a volume's mesh: where, which volume, and whether it enters (1) or leaves (2) it.
struct Crossing {
    float t;
    U32 volume, flags;
};
enum CrossingFlags : U32 { Entry = 1, Exit = 2 };
// VolumeProperties of a homogeneous stretch: its coefficients and the transmittance from the ray's start to it.
struct Step {
    V3 sigmaT, sigmaS, tr;
    float g, tStart, delta;
    U32 lightMask;
};

X2_HD inline V3 times(V3 a, V3 b) { return {a.x * b.x, a.y * b.y, a.z * b.z}; }
X2_HD inline V3 scaled(V3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
X2_HD inline V3 plus(V3 a, V3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
X2_HD inline V3 cmax0(V3 a) { return {fmaxf(a.x, 0.0f), fmaxf(a.y, 0.0f), fmaxf(a.z, 0.0f)}; }
X2_HD inline V3 expNeg(V3 a, float s) { return {expf(-a.x * s), expf(-a.y * s), expf(-a.z * s)}; }
X2_HD inline float lum(V3 a) { return 0.299f * a.x + 0.587f * a.y + 0.114f * a.z; }
X2_HD inline bool black(V3 a) { return a.x == 0.0f && a.y == 0.0f && a.z == 0.0f; }
X2_HD inline bool isZero(float x) { return fabsf(x) < Epsilon; }

// BaseVolume's ramp helpers: the ramp at the depth's place between its two depths.
X2_HD inline float rampT(float minDepth, float maxDepth, float depth) {
    const float t = fmaxf(depth - minDepth, 0.0f), interp = maxDepth - minDepth;
    return interp == 0.0f ? 0.0f : t / interp;
}
X2_HD inline V3 attenuationColor(const Shader& s, float depth) {
    const bool match = (s.flags & MatchAlbedo) != 0;
    V3 color = match ? s.albedoColor : s.attenuationColor;
    const bool useRamp = (s.flags & (match ? UseAlbedoRamp : UseAttenuationRamp)) != 0;
    if (useRamp && depth >= 0.0f) {
        color = match ? shade::rampEval(s.albedoRamp, rampT(s.albedoMin, s.albedoMax, depth))
                      : shade::rampEval(s.attenuationRamp, rampT(s.attenuationMin, s.attenuationMax, depth));
    }
    return (s.flags & InvertAttenuation) ? V3{1.0f - color.x, 1.0f - color.y, 1.0f - color.z} : color;
}
X2_HD inline V3 albedoColor(const Shader& s, float depth) {
    if ((s.flags & UseAlbedoRamp) && depth >= 0.0f) return shade::rampEval(s.albedoRamp, rampT(s.albedoMin, s.albedoMax, depth));
    return s.albedoColor;
}
// getDensity of density one: its density ramp at the depth (none for -1).
X2_HD inline float density(const Shader& s, float depth) {
    if (depth == -1.0f) return 1.0f;
    return shade::rampEval(s.densityRamp, rampT(s.densityMin, s.densityMax, depth));
}
// extinct() and albedo() of density one.
X2_HD inline V3 extinction(const Shader& s, float depth) {
    const float d = density(s, depth);
    return cmax0(scaled(times(scaled(V3{d, d, d}, s.intensity), attenuationColor(s, depth)), s.factor));
}
X2_HD inline V3 albedo(const Shader& s, float depth) {
    const float d = density(s, depth);
    return cmax0(times(V3{d, d, d}, albedoColor(s, depth)));
}

// evalVolumeShaders over the volumes a stretch is in (a bit each), as the overlap mode combines them: extinction,
// scattering, the anisotropy (scattering-weighted) and the light set of the chosen volume (the thickest for SUM).
struct Coefficients {
    V3 sigmaT, sigmaS;
    float g;
    U32 lightMask;
};
X2_HD inline Coefficients evalShaders(const Shader* shaders, U32 regions, U32 mode, float rnd, float depth) {
    Coefficients c{{0, 0, 0}, {0, 0, 0}, 0.0f, 0};
    V3 anisotropy{0, 0, 0}, sigmaTSum{0, 0, 0};
    float maxSigmaTLum = -3.402823466e+38f;
    U32 first = MaxVolumes;
    // RND: the volumes' running sums of extinction (luminance), then the one rnd picks.
    for (U32 v = 0; v < MaxVolumes; ++v) {
        if (!(regions >> v & 1)) continue;
        const Shader& s = shaders[v];
        const V3 sigmaTLocal = extinction(s, depth);
        const V3 scatter = times(albedo(s, depth), sigmaTLocal);
        if (first == MaxVolumes) first = v;
        const float l = lum(sigmaTLocal);
        if (mode == OverlapSum) {
            c.sigmaT = plus(c.sigmaT, sigmaTLocal);
            c.sigmaS = plus(c.sigmaS, scatter);
            anisotropy = plus(anisotropy, scaled(scatter, s.g));
            if (l > maxSigmaTLum) {
                maxSigmaTLum = l;
                c.lightMask = s.lightMask;
            }
        } else if (mode == OverlapMax) {
            if (l > maxSigmaTLum) {
                maxSigmaTLum = l;
                c.sigmaT = sigmaTLocal;
                c.sigmaS = scatter;
                anisotropy = scaled(scatter, s.g);
                c.lightMask = s.lightMask;
            }
        } else {
            sigmaTSum = plus(sigmaTSum, sigmaTLocal);
        }
    }
    if (mode == OverlapRnd && first != MaxVolumes) {
        const float total = lum(sigmaTSum);
        U32 chosen = first;
        float weight = 1.0f;
        if (total != 0.0f) {
            V3 running{0, 0, 0};
            chosen = MaxVolumes;
            U32 last = first;
            for (U32 v = 0; v < MaxVolumes; ++v) {
                if (!(regions >> v & 1)) continue;
                running = plus(running, extinction(shaders[v], depth));
                last = v;
                if (rnd < lum(running) / total) {
                    chosen = v;
                    break;
                }
            }
            if (chosen == MaxVolumes) chosen = last;  // past the last bound (rounding)
            weight = total / lum(extinction(shaders[chosen], depth));
        }
        const Shader& s = shaders[chosen];
        const V3 sigmaTLocal = extinction(s, depth);
        const V3 scatter = times(albedo(s, depth), sigmaTLocal);
        c.sigmaT = scaled(sigmaTLocal, weight);
        c.sigmaS = scaled(scatter, weight);
        anisotropy = scaled(scaled(scatter, s.g), weight);
        c.lightMask = s.lightMask;
    }
    c.g = lum(anisotropy);
    const float normalization = lum(c.sigmaS);
    if (normalization > 0.0f) c.g /= normalization;
    return c;
}
// evalSigmaT: the extinction alone (transmittance).
X2_HD inline V3 evalSigmaT(const Shader* shaders, U32 regions, U32 mode, float rnd, float depth) {
    return evalShaders(shaders, regions, mode, rnd, depth).sigmaT;
}

// collectVolumeIntervals' interiority: from the far end of the ray (outside every volume) back to its start, each
// volume's crossings counted so only its outermost entry and exit stay; the regions the start is in are returned.
X2_HD inline U32 interiority(Crossing* x, U32& n) {
    int count[MaxVolumes];
    for (U32 v = 0; v < MaxVolumes; ++v) count[v] = 0;
    U32 regions = 0;
    bool redundant = false;
    for (int i = int(n) - 1; i >= 0; --i) {
        const U32 v = x[i].volume;
        if (x[i].flags & Entry) {
            --count[v];
            if (count[v] == 0) regions &= ~(1u << v);
            else if (count[v] > 0) {
                x[i].flags &= ~Entry;
                redundant = true;
            }
        }
        if (x[i].flags & Exit) {
            if (count[v] == 0) regions |= 1u << v;
            else if (count[v] > 0) {
                x[i].flags &= ~Exit;
                redundant = true;
            }
            ++count[v];
        }
    }
    if (redundant) {
        U32 m = 0;
        for (U32 i = 0; i < n; ++i)
            if (x[i].flags) x[m++] = x[i];
        n = m;
    }
    return regions;
}
X2_HD inline void apply(U32& regions, const Crossing& x) {
    if (x.flags & Entry) regions |= 1u << x.volume;
    if (x.flags & Exit) regions &= ~(1u << x.volume);
}

// VolumePhase: Henyey-Greenstein (isotropic below |g| 1e-3).
X2_HD inline float phaseEval(float g, V3 wo, V3 wi) {
    if (fabsf(g) <= 1e-3f) return lights::OneOverFourPi;
    const float cosTheta = surface::dot(wo, wi), denom = 1 + g * g + 2 * g * cosTheta;
    return isZero(denom) ? 0.0f : lights::OneOverFourPi * (1 - g * g) / (denom * sqrtf(denom));
}
X2_HD inline V3 phaseSample(float g, V3 wo, float u1, float u2) {
    if (fabsf(g) <= 1e-3f) return shade::sampleSphereUniform(u1, u2);
    u1 = fmaxf(u1, Epsilon);  // clamp(u1, sEpsilon)
    const float sqrTerm = (1.0f - g * g) / (1.0f - g + 2.0f * g * u1);
    const float cosTheta = (1.0f + g * g - sqrTerm * sqrTerm) / (2.0f * g);
    const float sinTheta = sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta));
    const V3 local = shade::localSpherical(cosTheta, sinTheta, lights::TwoPi * u2);
    return shade::localToGlobal(shade::frame(V3{-wo.x, -wo.y, -wo.z}), local);
}

// Distance sampling proportional to exp(-sigma t) over [a, b], and equi-angular sampling about a pivot.
X2_HD inline float sampleDistanceExponential(float u, float sigma, float a, float b) {
    return a - logf(1.0f - u * (1.0f - expf(sigma * (a - b)))) / sigma;
}
X2_HD inline float pdfDistanceExponential(float t, float sigma, float a, float b) {
    return sigma / (expf((t - a) * sigma) - expf((t - b) * sigma));
}
X2_HD inline float sampleEquiAngular(float u, float D, float thetaA, float thetaB) { return D * tanf((1 - u) * thetaA + u * thetaB); }
X2_HD inline float pdfEquiAngular(float t, float D, float thetaA, float thetaB) { return D / ((thetaB - thetaA) * (D * D + t * t)); }
X2_HD inline bool finitef(float x) { return x - x == 0.0f; }

// GuideDistribution1D over the steps (discrete): weights to a cdf (all zero: uniform), and sampleDiscrete.
struct Distribution {
    float cdf[MaxSteps];
    float total;
    U32 n;
};
X2_HD inline void tabulate(Distribution& d, const float* w, U32 n) {
    d.n = n;
    float sum = 0.0f;
    for (U32 i = 0; i < n; ++i) sum += w[i];
    if (sum != 0.0f) {
        float partial = 0.0f;
        for (U32 i = 0; i + 1 < n; ++i) {
            partial += w[i];
            if (partial > sum) partial = sum;
            d.cdf[i] = partial;
        }
    } else {
        for (U32 i = 0; i + 1 < n; ++i) d.cdf[i] = float(i + 1) / float(n);
        sum = 1.0f;
    }
    d.cdf[n - 1] = sum;
    d.total = sum;
}
X2_HD inline U32 sampleDiscrete(const Distribution& d, float r, float& pdf, float& remapped) {
    const float rw = r * d.total;
    U32 i = 0;
    while (i + 1 < d.n && d.cdf[i] < rw) ++i;
    const float prev = i > 0 ? d.cdf[i - 1] : 0.0f, value = d.cdf[i] - prev;
    pdf = value / d.total;
    remapped = (rw - prev) / value;
    return i;
}
X2_HD inline float pdfDiscrete(const Distribution& d, U32 i) {
    const float prev = i > 0 ? d.cdf[i - 1] : 0.0f;
    return (d.cdf[i] - prev) / d.total;
}

// A light's equi-angular pivot (getEquiAngularPivot): a point on a rect or a disk, a spot's lens, a sphere's centre.
X2_HD inline bool bounded(const lights::Light& l) { return l.type != lights::Env && l.type != lights::Distant; }
X2_HD inline V3 pivot(const lights::Light& l, const float r[3]) {
    V3 local{0, 0, 0};
    if (l.type == lights::Rect) {
        local = V3{(0.5f - r[0]) * 2.0f * l.halfWidth, (0.5f - r[1]) * 2.0f * l.halfHeight, 0.0f};
    } else if (l.type == lights::Disk || l.type == lights::Spot) {
        const float rad = sqrtf(r[0]), angle = lights::TwoPi * r[1];
        local = V3{rad * cosf(angle), rad * sinf(angle), 0.0f};
        if (l.type == lights::Spot) local = V3{local.x * l.lensRadius, local.y * l.lensRadiusY, 0.0f};
    } else {
        return l.position;
    }
    return surface::add(l.position, lights::rows(l.local2Render, local));
}
}  // namespace xpu2::interactive::volume
