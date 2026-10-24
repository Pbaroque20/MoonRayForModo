// One complete sample of the admitted spatial domain, shared by the CPU and CUDA
// lanes of the asynchronous renderer (async_render.h).
//
// The estimator, random-number dimensions and operation order are those of
// resume::spatialStep, so every sample has the same expected value as the parity
// pipeline's. What differs is the shape: a sample runs start to finish in one
// call instead of as resumable stages, because the asynchronous lanes schedule
// whole samples. A sample that meets a texture tile that is not resident returns
// Miss before it has contributed anything; it is run again later, on either
// device, with the same identity and so the same random numbers (spec ACC-02,
// ACC-03: a started sample is never dropped).
#pragma once
#include "gpu_jobs.h"
#include "light_core.h"
#include "resume_core.h"
#include "shade_material.h"
#include "volume_core.h"

namespace xpu2::interactive::async {

using sample::U32;
using sample::U64;
using surface::V3;

enum class SampleStatus : U32 { Done = 0, Miss = 1, Error = 2 };

// Radiance and alpha (primary-hit coverage) of one sample.
struct Radiance {
    double rgb[3] = {0, 0, 0};
    double alpha = 0;
};

// Backend: trace(ray) -> resume::Hit (geom == ~0u on a miss),
//          material(hit, ray, Lambert&) -> tex::Status,
//          visible(origin, direction) -> bool,
// and for the path tracer: visible(origin, direction, distance) -> bool,
//          light(i) -> const lights::Light&, lightMask(geom) -> U32.
template <class Backend>
X2_HD inline SampleStatus integratePaths(const mixed::Config& c, U32 pixel, U32 index, Backend& backend, Radiance& out);

// The prototype's estimator: a camera hit, its emission, and cosine-sampled
// rays to a constant environment (Config::paths == 0).
template <class Backend>
X2_HD inline SampleStatus integrateDirect(const mixed::Config& c, U32 pixel, U32 index,
                                          Backend& backend, Radiance& out) {
    using namespace surface;
    if (c.surfaceLimit == 0 || c.surfaceLimit > 8 || pixel >= c.width * c.height)
        return SampleStatus::Error;
    const sample::Identity id{pixel, index, c.seed, 0};

    float x, y;
    Ray ray;
    if (!filter(c.filter, c.filterWidth, sample::draw(id, 0, c.sampling), x) ||
        !filter(c.filter, c.filterWidth, sample::draw(id, 1, c.sampling), y) ||
        !cameraRay(c.camera, float(pixel % c.width) + x, float(pixel / c.width) + y, ray))
        return SampleStatus::Error;

    double radiance[3] = {0, 0, 0}, throughput[3] = {1, 1, 1};
    U32 depth = 0, primaryHit = 0;
    for (;;) {
        resume::Hit hit = backend.trace(ray);
        if (hit.geom == ~0u) {
            if (depth) {
                radiance[0] += throughput[0] * c.sky.x;
                radiance[1] += throughput[1] * c.sky.y;
                radiance[2] += throughput[2] * c.sky.z;
            }
            break;
        }
        if (!depth) primaryHit = 1;

        Lambert material;
        const U32 dimension = 16 + 2 * depth;
        const U32 status = backend.material(hit, ray, material);
        if (status == tex::Miss) return SampleStatus::Miss;
        Sample bsdf;
        if (status != tex::Ready ||
            !lambert(material, hit.normal, sample::draw(id, dimension, c.sampling),
                     sample::draw(id, dimension + 1, c.sampling), bsdf))
            return SampleStatus::Error;

        radiance[0] += throughput[0] * material.emission.x;
        radiance[1] += throughput[1] * material.emission.y;
        radiance[2] += throughput[2] * material.emission.z;
        if (bsdf.pdf <= 0) break;
        throughput[0] *= bsdf.f.x / bsdf.pdf;
        throughput[1] *= bsdf.f.y / bsdf.pdf;
        throughput[2] *= bsdf.f.z / bsdf.pdf;

        if (++depth == c.surfaceLimit) {
            // The last interaction looks along its sampled direction for the sky.
            if (backend.visible(hit.origin, bsdf.wi)) {
                radiance[0] += throughput[0] * c.sky.x;
                radiance[1] += throughput[1] * c.sky.y;
                radiance[2] += throughput[2] * c.sky.z;
            }
            break;
        }
        ray = {hit.origin, bsdf.wi, {}, {}, 0, 3.402823466e38f};
    }
    out.rgb[0] = radiance[0];
    out.rgb[1] = radiance[1];
    out.rgb[2] = radiance[2];
    out.alpha = primaryHit;
    return SampleStatus::Done;
}

namespace paths {
using surface::V3;
X2_HD inline V3 times(V3 a, V3 b) { return {a.x * b.x, a.y * b.y, a.z * b.z}; }
X2_HD inline float luminance(V3 a) { return 0.299f * a.x + 0.587f * a.y + 0.114f * a.z; }
X2_HD inline bool black(V3 a) { return a.x == 0 && a.y == 0 && a.z == 0; }
// MoonRay's smartClamp: the largest channel at most the clamp, hue kept.
X2_HD inline V3 smartClamp(V3 a, float clamp) {
    if (clamp <= 0) return a;
    const float m = fmaxf(a.x, fmaxf(a.y, a.z));
    return m > clamp ? surface::mul(a, clamp / m) : a;
}
// Russian roulette on one contribution (applyRussianRoulette): below the
// threshold it survives with probability lum / threshold and is scaled back up.
X2_HD inline bool roulette(float lum, float threshold, float u, float& scale) {
    scale = 1;
    if (lum >= threshold) return true;
    if (lum < u * threshold) return false;
    scale = threshold / lum;
    return true;
}
// Uniform numbers for one vertex, from its branch's Philox stream at the
// vertex's bounce: one Philox block per four draws, the word picked by a switch
// (an indexed word would sit in local memory on the GPU).
struct Stream {
    sample::Identity id;
    U32 dimension, group = ~0u, w0 = 0, w1 = 0, w2 = 0, w3 = 0;
    X2_HD Stream(const sample::Identity& i, U32 bounce, U32 offset)
        : id(i), dimension(sample::CameraDimensions + bounce * sample::DimensionsPerBounce + offset) {}
    X2_HD void skip(U32 n) { dimension += n; }
    X2_HD float next() {
        if ((dimension >> 2) != group) {
            group = dimension >> 2;
            const sample::Words b = sample::block(id, group);
            w0 = b.v[0];
            w1 = b.v[1];
            w2 = b.v[2];
            w3 = b.v[3];
        }
        U32 w;
        switch (dimension++ & 3) {
        case 0: w = w0; break;
        case 1: w = w1; break;
        case 2: w = w2; break;
        default: w = w3;
        }
        return sample::unit(w);
    }
};
X2_HD inline void add(double r[3], V3 v) {
    r[0] += v.x;
    r[1] += v.y;
    r[2] += v.z;
}
}  // namespace paths

// MoonRay's path tracer (PATH_TRACER.md; pbr/integrator PathIntegrator.cc,
// PathIntegratorMultiSampler.cc, PathIntegratorUtil.cc) over the shading
// library's Bsdf. At every surface hit: self-emission; for each light of the
// hit's light set, light samples evaluated with every lobe that faces the
// sample's side, each weighted by the power heuristic against that lobe; for
// each lobe, BSDF samples that may meet a light (MIS against the light, none for
// mirror lobes) and continue the path where the lobe's depth limits allow.
// Russian roulette and clamping past the first non-mirror hit. At a hit with
// nonMirrorDepth 0 each lobe takes bsdf_samples squared samples (mirror lobes
// one) and each light light_samples squared; deeper, one of each, so the path
// branches into every lobe, as MoonRay's multi-sampler does.
//
// The branches still to trace are a small stack of pending rays, so no hit's
// Bsdf outlives its own samples (on the GPU, a thread's local memory holds one).
namespace paths {
using surface::V3;
// A ray still to be traced and what its hit inherits.
struct Pending {
    V3 origin, dir, T;
    U64 branch;
    U32 depth, nonMirrorDepth, diffuseDepth, glossyDepth, mirrorDepth, hairDepth, presenceDepth;
    float minRoughness[2], accumOpacity;
    shade::RayDiff diff;  // its differentials (a camera ray's come from the camera)
    U32 subsurfaceDepth = 0;
    float farT = 3.402823466e+38f;  // a subsurface exit sample's ray stops at the light it meets
    float nearT = 0.0f;             // a ray from a curve skips what is nearer than this
    U32 volumeDepth = 0;            // the volume scattering it has been through (PathVertex::volumeDepth)
    U32 lobeType = 0;               // the type of the lobe it is a sample of, 0 for a camera ray (PathVertex::lobeType)
};
constexpr U32 MaxPending = 32;
// A child's address in the sample's tree: a 64-bit mix of its parent's, the
// lobe and the sample (collisions within one sample's tree have probability
// about 2^-64 a pair; the radix tree of sample_stream.h cannot hold the
// multi-sampler's branching).
X2_HD inline U64 childBranch(U64 parent, U32 a, U32 b) {
    U64 z = parent + 0x9e3779b97f4a7c15ull * (U64(a) * 0x10001u + U64(b) + 1);
    z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
    z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
    return z ^ (z >> 31);
}
}  // namespace paths

//----------------------------------------------------------------------------
// Volumes (PathIntegratorVolume.cc) over homogeneous BaseVolumes bound to closed meshes (volume_core.h).
namespace paths {
// collectVolumeIntervals: a ray's crossings past its start, in order, and the regions it starts in.
template <class Backend>
X2_HD inline U32 volumeIntervals(Backend& backend, V3 org, V3 dir, float tnear, volume::Crossing* x, U32& regions) {
    U32 n = backend.volumeCrossings(org, dir, tnear, x, volume::MaxCrossings);
    regions = volume::interiority(x, n);
    return n;
}
}  // namespace paths

// transmittance(): Beer's law over each homogeneous stretch of [tnear, tfar], the extinction scaled; nothing once it
// falls to the transmittance threshold, nor through a volume that reaches to infinity.
template <class Backend>
X2_CALL V3 volumeTransmittance(const mixed::Config& c, Backend& backend, paths::Stream& s, V3 org, V3 dir, float tnear, float tfar,
                               float scale) {
    volume::Crossing x[volume::MaxCrossings];
    U32 regions;
    const U32 n = paths::volumeIntervals(backend, org, dir, tnear, x, regions);
    V3 tr{1, 1, 1};
    if (n == 0 && regions == 0) return tr;
    float tStart = tnear;
    auto segment = [&](float t0, float t1) -> bool {
        if (!regions) return true;
        if (t1 >= volume::FarLimit) return false;
        const float rnd = c.volumeOverlapMode == volume::OverlapRnd ? s.next() : 0.0f;
        const V3 sigmaT = volume::evalSigmaT(backend.volumes(), regions, c.volumeOverlapMode, rnd, t1 - t0);
        tr = volume::times(tr, volume::expNeg(sigmaT, (t1 - t0) * scale));
        return volume::lum(tr) > c.volumeTransmittanceThreshold;
    };
    for (U32 i = 0; i < n; ++i) {
        if (x[i].t > tfar) break;
        if (x[i].t - tStart > volume::Epsilon) {
            if (!segment(tStart, x[i].t)) return V3{0, 0, 0};
            tStart = x[i].t;
        }
        volume::apply(regions, x[i]);
    }
    if (tfar - tStart > volume::Epsilon && !segment(tStart, tfar)) return V3{0, 0, 0};
    return tr;
}

// estimateInScatteringSourceTermDirect: a light sample from a point in a volume, unoccluded, through the volumes
// on its way (their extinction scaled), times the phase function.
template <class Backend>
X2_CALL V3 volumeSourceTerm(const mixed::Config& c, Backend& backend, paths::Stream& s, const lights::Light& L, V3 P, V3 rayDir, float g,
                            const float ul[3], float scale) {
    V3 wi;
    lights::Hit lh;
    float r[3] = {ul[0], ul[1], ul[2]};
    if (!lights::sample(L, P, nullptr, r, wi, lh)) return V3{0, 0, 0};
    float pdfL;
    const V3 Li = lights::eval(L, P, wi, lh, pdfL);
    if (shade::isSampleInvalid(Li, pdfL) || !volume::finitef(pdfL)) return V3{0, 0, 0};
    const float far = lights::HitEpsilonEnd * lh.distance;
    if (!backend.visible(P, wi, volume::HitEpsilonStart, far)) return V3{0, 0, 0};
    const V3 tr = volumeTransmittance(c, backend, s, P, wi, 0.0f, far, scale);
    const float ph = volume::phaseEval(g, V3{-rayDir.x, -rayDir.y, -rayDir.z}, wi);
    return volume::scaled(volume::times(tr, Li), ph / pdfL);
}

// computeRadianceVolume over [tnear, tfar] of a ray: its homogeneous stretches (decoupledRayMarching), their single
// scattering (integrateVolumeScatteringDirect: per light, equi-angular and distance samples with MIS) and, with a
// max volume depth above one, the multiple scattering approximation (approximateVolumeMultipleScattering). The
// path's throughput takes the transmittance; its volume depth goes up when it scattered.
template <class Backend>
X2_CALL V3 volumeRadiance(const mixed::Config& c, const sample::Identity& root, Backend& backend, paths::Pending& pv, V3 org, V3 dir,
                          float tnear, float tfar) {
    using namespace paths;
    V3 radiance{0, 0, 0};
    volume::Crossing x[volume::MaxCrossings];
    U32 regions;
    const U32 n = volumeIntervals(backend, org, dir, tnear, x, regions);
    if (n == 0 && regions == 0) return radiance;
    const volume::Shader* shaders = backend.volumes();
    const U64 volumeBranch = childBranch(pv.branch, 0xfffc, pv.volumeDepth);
    sample::Identity vid = root;
    vid.branch = childBranch(volumeBranch, 0, 0);
    Stream marching(vid, pv.depth, 0);
    volume::Step steps[volume::MaxSteps];
    U32 count = 0;
    V3 vt{1, 1, 1};
    float tStart = tnear;
    auto march = [&](float t0, float t1) {
        if (!regions || t1 >= volume::FarLimit || count + 1 >= volume::MaxSteps) return;
        const float rnd = c.volumeOverlapMode == volume::OverlapRnd ? marching.next() : 0.0f;
        const volume::Coefficients k = volume::evalShaders(shaders, regions, c.volumeOverlapMode, rnd, t1 - t0);
        steps[count++] = volume::Step{k.sigmaT, k.sigmaS, vt, k.g, t0, t1 - t0, k.lightMask};
        vt = volume::times(vt, volume::expNeg(k.sigmaT, t1 - t0));
    };
    for (U32 i = 0; i < n; ++i) {
        if (x[i].t > tfar) break;
        if (x[i].t - tStart > volume::Epsilon) {
            march(tStart, x[i].t);
            tStart = x[i].t;
        }
        volume::apply(regions, x[i]);
    }
    if (tfar - tStart > volume::Epsilon) march(tStart, tfar);
    if (count == 0) return radiance;
    const V3 T = pv.T;
    if (pv.volumeDepth < c.maxVolumeDepth) {
        // The steps' weights for distance sampling: their scattering, through what lies before them.
        float density[volume::MaxSteps];
        for (U32 i = 0; i < count; ++i)
            density[i] = volume::lum(volume::times(volume::scaled(steps[i].sigmaS, steps[i].delta), steps[i].tr));
        volume::Distribution dist;
        volume::tabulate(dist, density, count);
        const float rayEnd = steps[count - 1].tStart + steps[count - 1].delta;
        // integrateVolumeScatteringDirect
        const bool highQuality = pv.nonMirrorDepth == 0;
        const U32 samplesPerLight = highQuality ? c.lightSamples : 1, scatterCount = highQuality ? c.volumeIlluminationSamples : 1;
        if (scatterCount > 0) {
            const float invN = 1.0f / float(samplesPerLight * scatterCount);
            for (U32 li = 0; li < c.lightCount; ++li) {
                const lights::Light& L = backend.light(li);
                const bool equiAngular = volume::bounded(L);
                for (U32 ls = 0; ls < samplesPerLight; ++ls) {
                    for (U32 ts = 0; ts < scatterCount; ++ts) {
                        sample::Identity sid = root;
                        sid.branch = childBranch(volumeBranch, 1 + li, ls * scatterCount + ts);
                        Stream ss(sid, pv.depth, 0);
                        float D = 0.0f, thetaA = 0.0f, thetaB = 0.0f, offset = 0.0f;
                        if (equiAngular) {
                            // equiAngularVolumeScattering: about a pivot on the light (its sample reused at the point)
                            const float ue = ss.next();
                            const float uel[3] = {ss.next(), ss.next(), ss.next()};
                            const V3 pivot = volume::pivot(L, uel);
                            offset = surface::dot(surface::add(pivot, surface::mul(org, -1.0f)), dir);
                            const V3 foot = surface::add(org, surface::mul(dir, offset));
                            D = shade::length(surface::add(pivot, surface::mul(foot, -1.0f)));
                            thetaA = atan2f(steps[0].tStart - offset, D);
                            thetaB = atan2f(rayEnd - offset, D);
                            const float te = volume::sampleEquiAngular(ue, D, thetaA, thetaB);
                            const float pdfTe = volume::pdfEquiAngular(te, D, thetaA, thetaB);
                            if (pdfTe != 0.0f && volume::finitef(pdfTe)) {
                                const float tePrime = te + offset;
                                U32 k = 0;  // findInterval: the last step starting at or before tePrime
                                while (k + 1 < count && steps[k + 1].tStart <= tePrime) ++k;
                                const volume::Step& vp = steps[k];
                                if (!volume::black(vp.sigmaS) && (vp.lightMask >> li & 1)) {
                                    const V3 trScatter = volume::times(vp.tr, volume::expNeg(vp.sigmaT, tePrime - vp.tStart));
                                    float mis = 1.0f;
                                    const float pdfTd = volume::pdfDiscrete(dist, k) *
                                                        volume::pdfDistanceExponential(tePrime, volume::lum(vp.sigmaT), vp.tStart,
                                                                                       vp.tStart + vp.delta);
                                    if (volume::finitef(pdfTd)) mis = lights::powerHeuristic(pdfTe, pdfTd);
                                    const V3 Ls =
                                        volumeSourceTerm(c, backend, ss, L, surface::add(org, surface::mul(dir, tePrime)), dir, vp.g, uel, 1.0f);
                                    radiance = volume::plus(radiance, volume::scaled(volume::times(volume::times(T, vp.sigmaS), volume::times(trScatter, Ls)),
                                                                                     invN * mis / pdfTe));
                                }
                            }
                        }
                        // distanceVolumeScatteringDirect
                        const float ud = ss.next();
                        const float udl[3] = {ss.next(), ss.next(), ss.next()};
                        float pdfDensity, udRemapped;
                        const U32 k = volume::sampleDiscrete(dist, ud, pdfDensity, udRemapped);
                        if (pdfDensity == 0.0f) continue;
                        const volume::Step& vp = steps[k];
                        if (volume::black(vp.sigmaS) || !(vp.lightMask >> li & 1)) continue;
                        const float sigmaT = volume::lum(vp.sigmaT), t0 = vp.tStart, t1 = vp.tStart + vp.delta;
                        const float td = volume::sampleDistanceExponential(udRemapped, sigmaT, t0, t1);
                        const float pdfTd = pdfDensity * volume::pdfDistanceExponential(td, sigmaT, t0, t1);
                        if (pdfTd == 0.0f || !volume::finitef(pdfTd)) continue;
                        const V3 trScatter = volume::times(vp.tr, volume::expNeg(vp.sigmaT, td - t0));
                        float mis = 1.0f;
                        if (equiAngular) {
                            const float pdfTe = volume::pdfEquiAngular(td - offset, D, thetaA, thetaB);
                            if (volume::finitef(pdfTe)) mis = lights::powerHeuristic(pdfTd, pdfTe);
                        }
                        const V3 Ls = volumeSourceTerm(c, backend, ss, L, surface::add(org, surface::mul(dir, td)), dir, vp.g, udl, 1.0f);
                        radiance = volume::plus(radiance, volume::scaled(volume::times(volume::times(T, vp.sigmaS), volume::times(trScatter, Ls)),
                                                                         invN * mis / pdfTd));
                    }
                }
            }
        }
        ++pv.volumeDepth;
        // approximateVolumeMultipleScattering (Wrenninge 2015): scatter events along the ray, then free paths from
        // them with the extinction, contribution and anisotropy shrinking each order.
        if (pv.volumeDepth < c.maxVolumeDepth && c.volumeIlluminationSamples > 0) {
            const U32 scatterSamples = c.volumeIlluminationSamples;
            const float invN = 1.0f / float(scatterSamples);
            for (U32 i = 0; i < scatterSamples; ++i) {
                sample::Identity mid = root;
                mid.branch = childBranch(volumeBranch, 0xffff, i);
                Stream ms(mid, pv.depth, 0);
                float pdfDensity, utRemapped;
                const U32 k = volume::sampleDiscrete(dist, ms.next(), pdfDensity, utRemapped);
                const volume::Step& vp = steps[k];
                float sigmaT = volume::lum(vp.sigmaT);
                const float t0 = vp.tStart, t1 = vp.tStart + vp.delta;
                const float td = volume::sampleDistanceExponential(utRemapped, sigmaT, t0, t1);
                const float pdfT = pdfDensity * volume::pdfDistanceExponential(td, sigmaT, t0, t1);
                if (pdfT == 0.0f || !volume::finitef(pdfT)) continue;
                const V3 trScatter = volume::times(vp.tr, volume::expNeg(vp.sigmaT, td - t0));
                V3 scatterPoint = surface::add(org, surface::mul(dir, td));
                V3 throughput = volume::scaled(volume::times(volume::times(T, vp.sigmaS), trScatter), 1.0f / pdfT);
                const float up0 = ms.next(), up1 = ms.next();
                V3 scatterDir = volume::phaseSample(vp.g, V3{-dir.x, -dir.y, -dir.z}, up0, up1);
                for (U32 depth = pv.volumeDepth; depth < c.maxVolumeDepth; ++depth) {
                    if (volume::lum(throughput) < c.volumeTransmittanceThreshold) break;
                    const float ai = powf(c.volumeAttenuationFactor, float(depth)), bi = powf(c.volumeContributionFactor, float(depth)),
                                ci = powf(c.volumePhaseAttenuationFactor, float(depth));
                    const float tFreePath = -logf(1.0f - ms.next()) / sigmaT;
                    volume::Crossing y[volume::MaxCrossings];
                    U32 here;
                    const U32 m = volumeIntervals(backend, scatterPoint, scatterDir, volume::Epsilon, y, here);
                    for (U32 j = 0; j < m && y[j].t <= tFreePath; ++j) volume::apply(here, y[j]);
                    const V3 rayDir = scatterDir;
                    scatterPoint = surface::add(scatterPoint, surface::mul(scatterDir, tFreePath));
                    if (!here) break;
                    const float rnd = c.volumeOverlapMode == volume::OverlapRnd ? ms.next() : 0.0f;
                    const volume::Coefficients kk = volume::evalShaders(shaders, here, c.volumeOverlapMode, rnd, -1.0f);
                    const float g = kk.g * ci;
                    sigmaT = volume::lum(kk.sigmaT);
                    if (volume::isZero(sigmaT)) break;
                    throughput = volume::scaled(volume::times(throughput, kk.sigmaS), 1.0f / sigmaT);
                    U32 firstVolume = 0;  // the light set of the first volume here
                    while (!(here >> firstVolume & 1)) ++firstVolume;
                    const U32 lightMask = shaders[firstVolume].lightMask;
                    for (U32 li = 0; li < c.lightCount; ++li) {
                        const float usl[3] = {ms.next(), ms.next(), ms.next()};
                        if (!(lightMask >> li & 1)) continue;
                        const V3 Ls = volumeSourceTerm(c, backend, ms, backend.light(li), scatterPoint, rayDir, g, usl, ai);
                        radiance = volume::plus(radiance, volume::scaled(volume::times(throughput, Ls), invN * bi));
                    }
                    const float uq0 = ms.next(), uq1 = ms.next();
                    scatterDir = volume::phaseSample(g, V3{-rayDir.x, -rayDir.y, -rayDir.z}, uq0, uq1);
                }
            }
        }
    }
    pv.T = volume::times(pv.T, vt);
    return radiance;
}

//----------------------------------------------------------------------------
// Diffusion subsurface scattering (PathIntegratorSubsurface.cc, which MoonRay's vector mode calls).
namespace paths {
// A subsurface exit sample: where it is, the normal it is lit with, the slice's geometric normal,
// and the offset origins of rays leaving it (facing: the side 'above' is on).
struct ExitPoint {
    V3 P, N, Ng, facing, above, below;
};
X2_HD inline V3 exitOrigin(const ExitPoint& x, V3 wi) { return shade::dot(wi, x.facing) >= 0.0f ? x.above : x.below; }
// The exit's Lambertian lobe (white, cosine included, the shadow terminator fix of the slice's Ng).
X2_HD inline shade::Color exitLambert(const mixed::Config& c, const ExitPoint& x, V3 wo, V3 wi, float& pdf) {
    const shade::Slice slice{x.Ng, wo, shade::AllLobeTypes, c.shadowTerminatorFix, true, true};
    const float cosWi = fmaxf(shade::dot(x.N, wi), 0.0f);
    pdf = cosWi * shade::OneOverPi;
    return shade::rgb(shade::shadowTerminatorFix(slice, x.N, wi) * shade::OneOverPi * cosWi);
}
}  // namespace paths

// computeRadianceSubsurfaceSample: an exit sample's light samples and Lambertian samples (MIS, no
// clamping or roulette), its bounces pushed from the entry point as MoonRay's parent ray starts there.
// At the first hit (strat) a pixel's exits draw their light and Lambertian samples from one stratified set, as
// MoonRay's one sequence a pixel: Sobol index strat * split + s, keyed by the exit kind (stratAddress).
template <class Backend>
X2_CALL V3 subsurfaceExitRadiance(const mixed::Config& c, const sample::Identity& root, Backend& backend, U32 mask,
                                       const paths::Pending& pv, U32 depthAdd, U32 subsurfaceDepth, const shade::State& entry,
                                       const resume::Hit& entryHit, const paths::ExitPoint& x, shade::Color pt, U32 split, U64 branch,
                                       bool doIndirect, paths::Pending* stack, U32& top, SampleStatus& status,
                                       bool stratified = false, U64 strat = 0, U64 stratAddress = 0) {
    using namespace paths;
    V3 radiance{0, 0, 0};
    pt = pt * (1.0f / float(split));
    for (U32 i = 0; i < c.lightCount; ++i) {
        if (!(mask >> i & 1)) continue;
        const lights::Light& L = backend.light(i);
        for (U32 s = 0; s < split; ++s) {
            sample::Identity id = root;
            id.branch = childBranch(branch, i, s);
            Stream ls(id, pv.depth, 0);
            float r[3] = {ls.next(), ls.next(), ls.next()};
            if (stratified) {
                const sample::Identity sid{root.pixel, strat * split + s, root.stream, childBranch(stratAddress, i, 0)};
                r[0] = sample::draw(sid, sample::CameraDimensions + 6, c.sampling);
                r[1] = sample::draw(sid, sample::CameraDimensions + 7, c.sampling);
            }
            V3 wi;
            lights::Hit lh;
            if (!lights::sample(L, x.P, &x.N, r, wi, lh)) continue;
            float pdfL;
            const V3 Li = lights::eval(L, x.P, wi, lh, pdfL);
            if (shade::isExactlyZero(Li) || !(pdfL > 0) || !shade::finite3(Li)) continue;
            float pdf;
            const shade::Color f = exitLambert(c, x, entry.wo, wi, pdf);
            if (shade::isSampleInvalid(f, pdf) || shade::dot(x.N, wi) < shade::Epsilon) continue;
            const shade::Color t = pt * Li * f * (1.0f / pdfL) * lights::powerHeuristic(pdfL, pdf);
            if (shade::finite3(t) && backend.visible(exitOrigin(x, wi), wi, lh.distance * lights::HitEpsilonEnd)) {
                shade::Color tv = t;
                if (c.volumeCount) {
                    sample::Identity tid = id;
                    tid.branch = childBranch(id.branch, 0xfffb, 0);
                    Stream vs(tid, pv.depth, 0);
                    tv = tv * volumeTransmittance(c, backend, vs, exitOrigin(x, wi), wi, 0.0f, lh.distance * lights::HitEpsilonEnd, 1.0f);
                }
                radiance += tv;
            }
        }
    }
    for (U32 s = 0; s < split; ++s) {
        sample::Identity id = root;
        id.branch = childBranch(branch, 0xffff, s);
        Stream bs(id, pv.depth, 0);
        float r1 = bs.next(), r2 = bs.next();
        const float choice = bs.next();
        if (stratified) {
            const sample::Identity sid{root.pixel, strat * split + s, root.stream, childBranch(stratAddress, 0xffff, 0)};
            r1 = sample::draw(sid, sample::CameraDimensions + 10, c.sampling);
            r2 = sample::draw(sid, sample::CameraDimensions + 11, c.sampling);
        }
        const V3 wi = shade::localToGlobal(shade::frame(x.N), shade::sampleLocalHemisphereCosine(r1, r2));
        float pdf;
        const shade::Color f = exitLambert(c, x, entry.wo, wi, pdf);
        if (shade::isSampleInvalid(f, pdf) || shade::dot(x.N, wi) < shade::Epsilon) continue;
        U32 hits = 0;
        for (U32 j = 0; j < c.lightCount; ++j) {
            lights::Hit lh;
            if ((mask >> j & 1) && lights::intersect(backend.light(j), x.P, &x.N, wi, 3.4028234663852886e+38f, lh)) ++hits;
        }
        V3 Li{0, 0, 0};
        float pdfL = 0.0f, lightDistance = 0.0f;
        bool lightHit = false;
        if (hits) {
            const U32 chosen = U32(choice * float(hits)) < hits ? U32(choice * float(hits)) : hits - 1;
            for (U32 j = 0, seen = 0; j < c.lightCount; ++j) {
                lights::Hit lh;
                if (!(mask >> j & 1) || !lights::intersect(backend.light(j), x.P, &x.N, wi, 3.4028234663852886e+38f, lh)) continue;
                if (seen++ != chosen) continue;
                Li = lights::eval(backend.light(j), x.P, wi, lh, pdfL) * float(hits);
                lightHit = !shade::isExactlyZero(Li) && pdfL > 0 && shade::finite3(Li);
                lightDistance = lh.distance;
                break;
            }
        }
        const shade::Color throughput = pt * f * (1.0f / pdf);
        if (doIndirect) {
            if (top >= MaxPending) {
                status = SampleStatus::Error;
                return radiance;
            }
            Pending child;
            child.volumeDepth = pv.volumeDepth;
            child.origin = shade::dot(wi, entryHit.normal) >= 0.0f ? entryHit.origin : entryHit.below;
            child.dir = wi;
            child.T = throughput;
            child.branch = childBranch(branch, 0xfffe, s);
            child.depth = pv.depth + 1;
            child.diffuseDepth = pv.diffuseDepth + depthAdd;
            child.nonMirrorDepth = pv.nonMirrorDepth + depthAdd;
            child.glossyDepth = pv.glossyDepth;
            child.mirrorDepth = pv.mirrorDepth;
            child.hairDepth = pv.hairDepth;
            child.presenceDepth = pv.presenceDepth;
            child.subsurfaceDepth = subsurfaceDepth;
            child.accumOpacity = pv.accumOpacity;
            child.lobeType = shade::Diffuse | shade::Reflection;  // the exit's Lambertian lobe
            child.farT = lightHit ? lightDistance * lights::HitEpsilonEnd : 3.402823466e+38f;
            // computeMinRoughness of a Lambertian lobe (roughness one).
            child.minRoughness[0] = shade::clampf(c.roughnessClamping, pv.minRoughness[0], 1.0f);
            child.minRoughness[1] = shade::clampf(c.roughnessClamping, pv.minRoughness[1], 1.0f);
            // scatterAndScale with scale one: the parent (entry) ray's differentials and a Lambertian lobe's.
            child.diff = shade::RayDiff{};
            if (entry.diffValid) {
                V3 dDdx, dDdy;
                shade::localHemisphereCosineDifferentials(r1, r2, dDdx, dDdy);
                shade::squarifyRectangle(dDdx, dDdy);
                const shade::Frame F = shade::frame(x.N);
                dDdx = shade::localToGlobal(F, dDdx);
                dDdy = shade::localToGlobal(F, dDdy);
                const V3 shift = entry.P - child.origin;
                child.diff.dOx = entry.dPdx + shift;
                child.diff.dOy = entry.dPdy + shift;
                child.diff.dDx = shade::normalize(wi + dDdx) - wi;
                child.diff.dDy = shade::normalize(wi + dDdy) - wi;
                child.diff.valid = shade::finite3(child.diff.dDx) && shade::finite3(child.diff.dDy) ? 1u : 0u;
            }
            stack[top++] = child;
        }
        if (lightHit) {
            const shade::Color t = throughput * Li * lights::powerHeuristic(pdf, pdfL);
            if (shade::finite3(t) && backend.visible(exitOrigin(x, wi), wi, lightDistance * lights::HitEpsilonEnd)) {
                shade::Color tv = t;
                if (c.volumeCount) {
                    sample::Identity tid = id;
                    tid.branch = childBranch(id.branch, 0xfffb, 1);
                    Stream vs(tid, pv.depth, 0);
                    tv = tv * volumeTransmittance(c, backend, vs, exitOrigin(x, wi), wi, 0.0f, lightDistance * lights::HitEpsilonEnd, 1.0f);
                }
                radiance += tv;
            }
        }
    }
    return radiance;
}
// computeRadiancePathTraceSubsurface: MoonRay's random walk (VolumeSubsurface). Each sample enters along a
// cosine direction below the surface: first a zero-scatter step with the zero-scatter extinction; if it does not
// leave, up to 256 scattering steps, isotropic then mostly Dwivedi sampled, with distances by the throughput's
// channels. A walk that leaves the object (through the same material, the exit facing away when asked) is lit at
// its exit as a white Lambertian; the sum is scaled up for the samples that never left. MoonRay draws the walk's
// distances and its backward-or-forward choices from two copies of one sequence (distanceSamples and
// dwivediDirectionSamples share their SequenceIDIntegrator), so each scatter event's choice is the distance draw
// before the one that led to it; the walk here keeps that pairing. In the first three non-mirror bounces MoonRay's
// sequences are its integrator tables (IntegratorSample: consecutive points of a bc_1D sequence for the distances
// and choices, another for the channels, a ppd_2D sequence for the directions, each chosen and Cranley-Patterson
// rotated by the sample's identity); the walk's estimate depends on that ordering, so the walk here draws from the
// same tables, the sequences and rotations chosen at random, and independent numbers after them.
template <class Backend>
X2_CALL V3 randomWalkRadiance(const mixed::Config& c, const sample::Identity& root, Backend& backend, U32 mask,
                                   const paths::Pending& pv, U32 subsurfaceDepth, const shade::State& st, const resume::Hit& hit,
                                   const shade::Bsdf& bsdf, bool doIndirect, paths::Pending* stack, U32& top, SampleStatus& status) {
    using namespace paths;
    using shade::Color;
    V3 radiance{0, 0, 0};
    const shade::BssrdfRecord& b = bsdf.bssrdf;
    const Color albedo = b.rwAlbedo, sigmaT = b.sigmaT, sigmaS = sigmaT * albedo, v0 = b.dwivediV0;
    const U32 n = pv.nonMirrorDepth == 0 ? c.bssrdfSamples : 1u;
    const Color fresnel =
        b.fresnel != shade::NoIndex ? shade::fresnelEval(bsdf.fresnels, b.fresnel, fabsf(shade::dot(st.N, st.wo))) : shade::rgb(1);
    const U64 branch = childBranch(pv.branch, 0xfffc, 0);
    const U32 material = backend.materialId(hit.geom);
    const shade::Frame frame = shade::frame(st.N);
    const float wBackwardSampling = 0.9f;
    auto expC = [](Color a) { return Color{expf(a.x), expf(a.y), expf(a.z)}; };
    U32 evaluated = 0;
    for (U32 s = 0; s < n; ++s) {
        sample::Identity id = root;
        id.branch = childBranch(branch, 1, s);
        Stream rs(id, pv.depth, 0);
        Color pt = b.scale * pv.T * fresnel * (1.0f / float(n));
        if (shade::isBlack(pt)) continue;
        // The walk's three sequences (MoonRay's tables up to sample 1015, as partitioned1D/2D use them).
        const float* tables = pv.nonMirrorDepth < 3 ? backend.walkSequences() : nullptr;
        U32 distanceBase = 0, channelBase = 0, directionBase = 0, kDistance = 0, kChannel = 0, kDirection = 0;
        float distanceShift = 0.0f, channelShift = 0.0f, directionShift[2] = {0.0f, 0.0f};
        if (tables) {
            auto sequence = [&]() { return U32(fminf(rs.next() * 4096.0f, 4095.0f)); };
            distanceBase = sequence() * 1024u;
            distanceShift = rs.next();
            channelBase = sequence() * 1024u;
            channelShift = rs.next();
            directionBase = 4096u * 1024u + sequence() * 2048u;
            directionShift[0] = rs.next();
            directionShift[1] = rs.next();
        }
        auto rotate = [](float x, float shift) {
            const float r = x + shift;
            return r >= 1.0f ? r - 1.0f : r;
        };
        auto nextDistance = [&]() { return tables && kDistance < 1016 ? rotate(tables[distanceBase + kDistance++], distanceShift) : rs.next(); };
        auto nextChannel = [&]() { return tables && kChannel < 1016 ? rotate(tables[channelBase + kChannel++], channelShift) : rs.next(); };
        auto nextDirection = [&](float& a, float& b2) {
            if (tables && kDirection < 1016) {
                a = rotate(tables[directionBase + 2 * kDirection], directionShift[0]);
                b2 = rotate(tables[directionBase + 2 * kDirection + 1], directionShift[1]);
                ++kDirection;
            } else {
                a = rs.next();
                b2 = rs.next();
            }
        };
        float u0, u1;
        nextDirection(u0, u1);
        V3 dir = -shade::localToGlobal(frame, shade::sampleLocalHemisphereCosine(u0, u1));
        // Below the surface: the hit's far-side origin.
        V3 org = shade::dot(dir, hit.normal) >= 0.0f ? hit.origin : hit.below;
        bool reachSurface = false, hadScatterEvent = false, choseDwivedi = false;
        float previousDistanceU = 0.0f;  // the last distance draw (the choice at the next scatter event)
        resume::Hit exitHit;
        shade::State exitState;
        auto valid = [&](const resume::Hit& h, const surface::Ray& ray) {
            if (h.geom == ~0u) return false;
            exitState = shade::State{};
            exitState.incoming = shade::RayDiff{};
            if (!backend.surfaceState(h, ray, exitState)) return false;
            return !b.resolveSelfIntersections || !exitState.entering;
        };
        // Zero scatter.
        {
            const float uChannel = nextChannel(), uDistance = nextDistance();
            previousDistanceU = uDistance;
            const float recip = 1.0f / (pt.x + pt.y + pt.z);
            const int ch = uChannel < pt.x * recip ? 0 : uChannel < (pt.x + pt.y) * recip ? 1 : 2;
            const float zs = ch == 0 ? b.zeroScatterSigmaT.x : ch == 1 ? b.zeroScatterSigmaT.y : b.zeroScatterSigmaT.z;
            const float tfar = -logf(1.0f - uDistance) / zs;
            const surface::Ray ray{org, dir, V3{0, 0, 0}, V3{0, 0, 0}, 0.0f, tfar};
            const resume::Hit h = backend.traceMaterial(ray, material);
            if (valid(h, ray)) {
                const float t1 = h.t;
                const Color tr{expf(-b.zeroScatterSigmaT.x * t1), expf(-b.zeroScatterSigmaT.y * t1), expf(-b.zeroScatterSigmaT.z * t1)};
                const float exitProbability = (pt.x * tr.x + pt.y * tr.y + pt.z * tr.z) * recip;
                pt = pt * tr * (1.0f / exitProbability);
                reachSurface = true;
                exitHit = h;
                ++evaluated;
            }
        }
        if (!reachSurface) {
            for (U32 nScatter = 0; nScatter < 256; ++nScatter) {
                if (shade::isBlack(pt)) break;
                const float phaseSamplingWeight = nScatter > 1 ? 0.1f : 1.0f;
                // sampleChannel
                const float uChannel = nextChannel();
                const float norm = 1.0f / (pt.x + pt.y + pt.z);
                const Color channelWeights = norm * pt;
                const int ch = uChannel < channelWeights.x ? 0 : uChannel < channelWeights.x + channelWeights.y ? 1 : 2;
                // sampleDistanceMultiScatter
                const float uDistance = nextDistance(), backward = previousDistanceU;
                previousDistanceU = uDistance;
                float NdotDir = shade::dot(dir, frame.z);
                // Dwivedi distances: longer steps back toward the normal (the choice is the previous direction's).
                const Color sigmaTPrime = sigmaT * (shade::rgb(1) - Color{NdotDir / v0.x, NdotDir / v0.y, NdotDir / v0.z});
                const float sT = ch == 0 ? sigmaT.x : ch == 1 ? sigmaT.y : sigmaT.z;
                const float sTP = ch == 0 ? sigmaTPrime.x : ch == 1 ? sigmaTPrime.y : sigmaTPrime.z;
                const float distance = -logf(1.0f - uDistance) / (choseDwivedi ? sTP : sT);
                Color tr = expC(-1.0f * sigmaT * distance);
                const Color pdfDistance = sigmaT * tr, pdfDistanceDwivedi = sigmaTPrime * expC(-1.0f * sigmaTPrime * distance);
                const surface::Ray ray{org, dir, V3{0, 0, 0}, V3{0, 0, 0}, 0.0f, distance};
                const resume::Hit h = backend.traceMaterial(ray, material);
                if (valid(h, ray)) {
                    if (!hadScatterEvent) break;  // zero scattering was counted above
                    tr = expC(-1.0f * sigmaT * h.t);
                    reachSurface = true;
                    const Color trp = expC(-1.0f * sigmaTPrime * h.t);
                    const float pdfSurf = pt.x * norm * (phaseSamplingWeight * tr.x + (1.0f - phaseSamplingWeight) * trp.x) +
                                          pt.y * norm * (phaseSamplingWeight * tr.y + (1.0f - phaseSamplingWeight) * trp.y) +
                                          pt.z * norm * (phaseSamplingWeight * tr.z + (1.0f - phaseSamplingWeight) * trp.z);
                    pt = pt * tr * (1.0f / pdfSurf);
                    exitHit = h;
                    break;
                }
                // A scattering event.
                hadScatterEvent = true;
                org = org + distance * dir;
                pt = pt * tr * sigmaS * shade::OneOverFourPi;
                float d0, d1;
                nextDirection(d0, d1);
                // sampleDirection
                if (d0 < phaseSamplingWeight) {
                    choseDwivedi = false;
                    const float r = d0 / phaseSamplingWeight;
                    const V3 local = shade::sampleSphereUniform(r, d1);
                    dir = shade::localToGlobal(frame, local);
                    NdotDir = backward < wBackwardSampling ? local.z : -local.z;
                } else {
                    choseDwivedi = true;
                    const float r = (d0 - phaseSamplingWeight) / (1.0f - phaseSamplingWeight);
                    const float vc = ch == 0 ? v0.x : ch == 1 ? v0.y : v0.z;
                    NdotDir = vc - (vc + 1.0f) * powf((vc - 1.0f) / (vc + 1.0f), r);
                    const float sine = sqrtf(fmaxf(0.0f, 1.0f - NdotDir * NdotDir)), phi = shade::TwoPi * d1;
                    const V3 local{sine * cosf(phi), sine * sinf(phi), NdotDir};
                    dir = backward < wBackwardSampling ? shade::normalize(shade::localToGlobal(frame, local))
                                                       : -shade::normalize(shade::localToGlobal(frame, local));
                }
                // calculateOneSamplePDF
                const Color pdfDwivedi = shade::OneOverTwoPi * b.dwivediNormPdf / (v0 - shade::rgb(NdotDir));
                const float pdfPhase = shade::OneOverFourPi;
                float pdfSampling = 0.0f;
                const float pd[3] = {pdfDistance.x, pdfDistance.y, pdfDistance.z},
                            pdd[3] = {pdfDistanceDwivedi.x, pdfDistanceDwivedi.y, pdfDistanceDwivedi.z},
                            pdw[3] = {pdfDwivedi.x, pdfDwivedi.y, pdfDwivedi.z}, cw[3] = {channelWeights.x, channelWeights.y, channelWeights.z};
                for (int k = 0; k < 3; ++k)
                    pdfSampling += cw[k] * (phaseSamplingWeight * pdfPhase * pd[k] + (1.0f - phaseSamplingWeight) * pdw[k] * pdd[k]);
                pt = pt * (1.0f / pdfSampling);
            }
            if (hadScatterEvent) ++evaluated;
        }
        if (!reachSurface) continue;
        // The exit: lit as a white Lambertian facing out of the object.
        const V3 nOut = -exitState.N;
        const ExitPoint x{exitState.P, nOut, nOut, exitHit.normal, exitHit.origin, exitHit.below};
        radiance += subsurfaceExitRadiance(c, root, backend, mask, pv, 1, subsurfaceDepth, st, hit, x, pt, 1, childBranch(branch, 2, s),
                                           doIndirect, stack, top, status);
        if (status != SampleStatus::Done) return radiance;
    }
    if (evaluated > 0 && evaluated < n) radiance = radiance * (float(n) / float(evaluated));
    return radiance;
}

// computeRadianceDiffusionSubsurface: local samples (probe rays along the entry's frame axes, MIS over the
// axes, area compensation) or, when the ray's footprint is wider than the profile, the entry point lit as
// Lambertian; then computeDiffusionForwardScattering's samples through the object.
template <class Backend>
X2_CALL V3 subsurfaceRadiance(const mixed::Config& c, const sample::Identity& root, Backend& backend, U32 mask,
                                   const paths::Pending& pv, U32 subsurfaceDepth, const shade::State& st, const resume::Hit& hit,
                                   V3 rayDir, const shade::Bsdf& bsdf, bool doIndirect, paths::Pending* stack, U32& top,
                                   SampleStatus& status) {
    using namespace paths;
    V3 radiance{0, 0, 0};
    if (!c.enableSss || c.bssrdfSamples < 1) return radiance;
    const shade::BssrdfRecord& b = bsdf.bssrdf;
    if (b.type == shade::BssrdfRandomWalk)
        return randomWalkRadiance(c, root, backend, mask, pv, subsurfaceDepth, st, hit, bsdf, doIndirect, stack, top, status);
    const float maxRadius = b.maxRadius, minRadius = maxRadius * 0.1f;
    const V3 P = st.P, N = st.N;
    const shade::Frame localF = shade::frame(N);
    const shade::Color scaleFresnelWo =
        (b.fresnel != shade::NoIndex ? shade::fresnelEval(bsdf.fresnels, b.fresnel, fabsf(shade::dot(N, st.wo))) : shade::rgb(1)) * b.scale;
    const U64 sssBranch = childBranch(pv.branch, 0xfffd, 0);
    // At the first non-mirror hit MoonRay draws a pixel's subsurface samples, and their exits' light and Lambertian
    // samples, from one sequence across the pixel's samples; here one stratified set, Sobol index index * split + i.
    const bool stratified = pv.nonMirrorDepth == 0;
    const U32 material = backend.materialId(hit.geom);
    const ExitPoint entryPoint{P, N, st.Ng, hit.normal, hit.origin, hit.below};
    // canSubstituteSubsurface
    const V3 dPdx = st.dPds * st.dsdx + st.dPdt * st.dtdx, dPdy = st.dPds * st.dsdy + st.dPdt * st.dtdy;
    const float footprint = (shade::dot(dPdx, dPdx) + shade::dot(dPdy, dPdy)) * 0.5f;
    U32 split;
    if (footprint / (maxRadius * maxRadius) > 0.85f) {
        const U32 lambertSplit = pv.nonMirrorDepth > 0 ? 1u : c.bsdfSamples;
        const shade::Color throughput = pv.T * shade::bssrdfDiffuseReflectance(b) * scaleFresnelWo;
        radiance += subsurfaceExitRadiance(c, root, backend, mask, pv, 1, subsurfaceDepth, st, hit, entryPoint, throughput, lambertSplit,
                                           childBranch(sssBranch, 1, 0), doIndirect, stack, top, status, stratified, root.index,
                                           childBranch(sssBranch, 1, 1));
        split = 1;
    } else {
        split = pv.nonMirrorDepth > 0 ? 2u : c.bssrdfSamples;
        if (split > 16) split = 16;
        const shade::Color ptSubsurface = pv.T * (1.0f / float(split));
        shade::Color measured{0, 0, 0};
        ExitPoint exits[16];
        shade::Color pts[16];
        U32 drawn[16];
        U32 n = 0;
        for (U32 i = 0; i < split; ++i) {
            sample::Identity id = root;
            id.branch = childBranch(sssBranch, 2, i);
            Stream ss(id, pv.depth, 0);
            float r1 = ss.next();
            float r2 = ss.next();
            if (stratified) {
                const sample::Identity sid{root.pixel, U64(root.index) * split + i, root.stream, childBranch(sssBranch, 2, 0xfff0)};
                r1 = sample::draw(sid, sample::CameraDimensions + 4, c.sampling);
                r2 = sample::draw(sid, sample::CameraDimensions + 5, c.sampling);
            }
            V3 directionProj;
            const int axis = shade::bssrdfSelectAxis(localF, r1, directionProj);
            V3 dPi;
            float r;
            const float pdf = shade::bssrdfSampleLocal(b, r1, r2, dPi, r);
            if (pdf == 0.0f) continue;
            const V3 PiTangent = P + shade::bssrdfOffsetLocalToGlobal(localF, axis, dPi);
            const float search = fmaxf(fminf(r, maxRadius), minRadius);
            const surface::Ray probe{PiTangent - directionProj * search, directionProj, V3{0, 0, 0}, V3{0, 0, 0}, 0.0f, 2.0f * search};
            const resume::Hit ph = backend.traceMaterial(probe, material);
            if (ph.geom == ~0u) continue;
            shade::State ps;
            ps.incoming = shade::RayDiff{};
            if (!backend.surfaceState(ph, probe, ps)) continue;
            if (-shade::dot(ps.N, directionProj) < shade::Epsilon) continue;
            const V3 dp = P - ps.P;
            r = shade::length(dp);
            if (r > maxRadius) continue;
            const shade::Color e = shade::bssrdfEval(b, r) * shade::bssrdfMISAxisWeight(localF, ps.N, dp, b);
            measured = measured + e;
            exits[n] = ExitPoint{ps.P, ps.N, ps.Ng, ph.normal, ph.origin, ph.below};
            pts[n] = ptSubsurface * e * scaleFresnelWo;
            drawn[n] = i;
            ++n;
        }
        measured = measured * (1.0f / float(split));
        const shade::Color compensation = shade::bssrdfAreaCompensation(measured, shade::bssrdfDiffuseReflectance(b));
        for (U32 k = 0; k < n; ++k) {
            radiance += subsurfaceExitRadiance(c, root, backend, mask, pv, 1, subsurfaceDepth, st, hit, exits[k], pts[k] * compensation, 1,
                                               childBranch(sssBranch, 3, k), doIndirect, stack, top, status, stratified,
                                               U64(root.index) * split + drawn[k], childBranch(sssBranch, 3, 0xfff0));
            if (status != SampleStatus::Done) return radiance;
        }
    }
    if (status != SampleStatus::Done) return radiance;
    // computeDiffusionForwardScattering: directions in an 85-degree cap into the surface, the profile at the
    // distance travelled, a Jacobian; its exit samples one bounce deeper still.
    const float cosThetaMax = cosf(85.0f / 180.0f * shade::Pi);
    const shade::Color ptSubsurface = pv.T * (1.0f / float(split));
    for (U32 i = 0; i < split; ++i) {
        sample::Identity id = root;
        id.branch = childBranch(sssBranch, 4, i);
        Stream ss(id, pv.depth, 0);
        float r1 = ss.next(), r2 = ss.next();
        if (stratified) {
            const sample::Identity sid{root.pixel, U64(root.index) * split + i, root.stream, childBranch(sssBranch, 4, 0xfff0)};
            r1 = sample::draw(sid, sample::CameraDimensions + 8, c.sampling);
            r2 = sample::draw(sid, sample::CameraDimensions + 9, c.sampling);
        }
        V3 local;
        const float pdf = shade::bssrdfSampleGlobal(r1, r2, cosThetaMax, local);
        const V3 direction = -shade::localToGlobal(localF, local);
        const surface::Ray back{shade::dot(direction, hit.normal) >= 0.0f ? hit.origin : hit.below, direction, V3{0, 0, 0},
                                V3{0, 0, 0}, 0.0f, maxRadius};
        const resume::Hit bh = backend.traceMaterial(back, material);
        if (bh.geom == ~0u) continue;
        shade::State bs;
        bs.incoming = shade::RayDiff{};
        if (!backend.surfaceState(bh, back, bs)) continue;
        const V3 Ni = -bs.N;
        if (-shade::dot(Ni, N) < shade::Epsilon) continue;
        const float r = bh.t;
        const float cosTheta = fabsf(shade::dot(Ni, direction));
        const float jacobian = r * r / fmaxf(cosTheta, 0.05f);
        const shade::Color pt = ptSubsurface * shade::bssrdfEval(b, r) * (jacobian / pdf) * scaleFresnelWo;
        if (!shade::finite3(pt)) continue;
        const ExitPoint x{bs.P, Ni, -bs.Ng, bh.normal, bh.origin, bh.below};
        radiance += subsurfaceExitRadiance(c, root, backend, mask, pv, 2, subsurfaceDepth, st, hit, x, pt, 1, childBranch(sssBranch, 5, i),
                                           doIndirect, stack, top, status, stratified, U64(root.index) * split + i,
                                           childBranch(sssBranch, 5, 0xfff0));
        if (status != SampleStatus::Done) return radiance;
    }
    return radiance;
}

template <class Backend>
X2_HD inline SampleStatus integratePaths(const mixed::Config& c, U32 pixel, U32 index, Backend& backend, Radiance& out) {
    using namespace paths;
    using shade::Color;
    if (pixel >= c.width * c.height || c.bsdfSamples == 0 || c.bsdfSamples > 64 || c.lightSamples == 0 || c.lightSamples > 64 ||
        c.lightCount > 32)
        return SampleStatus::Error;
    const sample::Identity root{pixel, index, c.seed, 0};
    float x, y;
    surface::Ray camera;
    if (!surface::filter(c.filter, c.filterWidth, sample::draw(root, 0, c.sampling), x) ||
        !surface::filter(c.filter, c.filterWidth, sample::draw(root, 1, c.sampling), y) ||
        !surface::cameraRay(c.camera, float(pixel % c.width) + x, float(pixel / c.width) + y, camera))
        return SampleStatus::Error;

    // The pending rays and the hit's Bsdf live in the backend's per-thread scratch: on the GPU,
    // global memory, so the path tracer's state across a trace is a few registers, not kilobytes.
    Pending* stack = backend.pending();
    shade::Bsdf& bsdf = backend.bsdf();
    U32 top = 0;
    stack[top++] = Pending{camera.origin, camera.direction, {1, 1, 1}, 0, 0, 0, 0, 0, 0, 0, 0, {0, 0}, 0, shade::RayDiff{}};
    // MoonRay's primary ray differential scale (initPrimaryRay): its scatterAndScale scales a diffuse lobe's by it.
    const float primaryScale = 1.0f / fminf(sqrtf(float(c.spp ? c.spp : 1)), 2.0f);
    V3 radiance{0, 0, 0};
    U32 primaryHit = 0;
    while (top) {
        Pending pv = stack[--top];
        const bool fromCamera = pv.depth == 0 && pv.presenceDepth == 0;
        // The camera ray keeps its differentials, for the texture footprint of the first hit.
        const surface::Ray ray{pv.origin, pv.dir, fromCamera ? camera.dx : V3{0, 0, 0}, fromCamera ? camera.dy : V3{0, 0, 0},
                               fromCamera ? camera.nearT : pv.nearT, fromCamera ? camera.farT : pv.farT};
        const resume::Hit hit = backend.trace(ray);
        // The volumes the ray passes on its way (computeRadianceVolume): their light, and the throughput through them.
        const U32 volumeDepthBefore = pv.volumeDepth;
        if (c.volumeCount) radiance += volumeRadiance(c, root, backend, pv, ray.origin, ray.direction, ray.nearT,
                                                      hit.geom == ~0u ? ray.farT : hit.t);
        if (hit.geom == ~0u) continue;  // a miss adds nothing: lights are reached through the BSDF samples
        if (pv.depth == 0) primaryHit = 1;

        shade::State st;
        st.minRoughness[0] = pv.minRoughness[0];
        st.minRoughness[1] = pv.minRoughness[1];
        st.pathType = pv.diffuseDepth ? shade::PathIndirectDiffuse
                      : pv.glossyDepth ? shade::PathIndirectGlossy
                      : pv.mirrorDepth ? shade::PathIndirectMirror
                                       : shade::PathPrimary;
        st.causticPath = pv.diffuseDepth > 0;
        st.incoming = pv.diff;
        st.subsurfaceAllowed = pv.subsurfaceDepth < c.maxSubsurfacePerPath;
        st.rayLobe = pv.lobeType;
        float presence = 1.0f;
        shade::reset(bsdf);
        const U32 status = backend.shade(hit, ray, st, bsdf, presence);
        if (status == tex::Miss) return SampleStatus::Miss;
        if (status != tex::Ready) return SampleStatus::Error;
        if (presence < 1.0f) {
            // A cut out surface (presence 0): the ray goes on through it (computeRadiancePresence).
            if (presence > 0.0f || pv.presenceDepth >= c.maxPresenceDepth) return SampleStatus::Error;
            Pending through = pv;
            through.origin = hit.below;
            through.nearT = hit.epsilon;  // from a curve: on from the hit, past its epsilon
            // The differentials go on through it (transferred to the hit, a camera ray's scaled).
            through.diff = st.incoming;
            through.diff.valid = st.diffValid ? 1u : 0u;
            through.diff.dOx = st.dPdx + (st.P - hit.below);
            through.diff.dOy = st.dPdy + (st.P - hit.below);
            ++through.presenceDepth;
            through.volumeDepth = volumeDepthBefore;  // a presence continuation keeps its volume depth
            stack[top++] = through;
            continue;
        }
        radiance += pv.T * bsdf.selfEmission;  // self-emission
        const bool subsurface = bsdf.bssrdf.type != shade::BssrdfNone;
        if (subsurface && hit.epsilon > 0.0f) return SampleStatus::Error;  // subsurface scattering on curves is not ported
        if ((bsdf.topCount == 0 && !subsurface) || bsdf.earlyTermination) continue;
        // A hit with subsurface counts toward max_subsurface_per_path for everything after it.
        const U32 subsurfaceDepth = pv.subsurfaceDepth + (subsurface ? 1u : 0u);

        // indirectFlags: the lobe types whose depth limits still allow a bounce.
        U32 indirectFlags = 0;
        if (c.bsdfSamples > 0 && c.maxDepth > 0 && pv.depth < c.maxDepth) {
            if (pv.diffuseDepth < c.maxDiffuseDepth) indirectFlags |= shade::AllDiffuse;
            if (pv.glossyDepth < c.maxGlossyDepth) indirectFlags |= shade::AllGlossy;
            if (pv.mirrorDepth < c.maxMirrorDepth) indirectFlags |= shade::AllMirror;
            if (pv.hairDepth < c.maxHairDepth) indirectFlags |= shade::AllSurfaceSides;
        }
        const bool doIndirect = indirectFlags != 0;
        // The culling normal: none for a Bsdf with both sides or spherical lobes.
        V3 cull{0, 0, 0};
        const V3* cullN = nullptr;
        if (!subsurface && !bsdf.spherical && (bsdf.type & shade::AllSurfaceSides) != shade::AllSurfaceSides) {
            cull = (bsdf.type & shade::Reflection) ? st.Ng : -st.Ng;
            cullN = &cull;
        }
        const shade::Slice slice{st.Ng, st.wo, shade::AllLobeTypes, c.shadowTerminatorFix, true, st.entering};
        const bool split = pv.nonMirrorDepth == 0;
        const U32 nl = split ? c.lightSamples : 1;
        const bool clampHere = pv.nonMirrorDepth >= c.clampDepth;
        const bool rr = pv.nonMirrorDepth > 0 && c.rrThreshold > 0;
        const U32 mask = backend.lightMask(hit.geom);
        // Subsurface scattering (computeRadianceSubsurface): its exit samples' light, and their bounces pushed.
        if (subsurface) {
            SampleStatus status = SampleStatus::Done;
            radiance += subsurfaceRadiance(c, root, backend, mask, pv, subsurfaceDepth, st, hit, ray.direction, bsdf, doIndirect,
                                           stack, top, status);
            if (status != SampleStatus::Done) return status;
        }
        // Sample counts per lobe (computeLobeSampleCount): mirrors take one.
        U32 lobeSamples[shade::MaxLobes];
        for (U32 k = 0; k < bsdf.topCount; ++k)
            lobeSamples[k] = (!split || (shade::topLobe(bsdf, k).type & shade::Mirror)) ? 1 : c.bsdfSamples;
        const V3 above = hit.origin, below = hit.below;
        // A curve's rays (PathIntegrator: the hit's epsilon hint): shadow rays skip its epsilon and reach at least twice
        // it; bounces skip the epsilon over the cosine to Ng.
        const float curveEpsilon = hit.epsilon;

        // Light samples (drawLightSamples, integrateLightSetSample).
        const U64 lightBranch = childBranch(pv.branch, 0xfffe, 0);
        for (U32 i = 0; i < c.lightCount; ++i) {
            if (!(mask >> i & 1)) continue;
            const lights::Light& L = backend.light(i);
            const U64 lightAddress = childBranch(lightBranch, i, 0);
            sample::Identity lid = root;
            lid.branch = lightAddress;
            Stream ls(lid, pv.depth, 0);
            for (U32 s = 0; s < nl; ++s) {
                float r[3] = {ls.next(), ls.next(), ls.next()};
                const float u = ls.next();
                if (split) {
                    // The hit's samples of a light are one stratified set (policy bit 4).
                    const sample::Identity strat{pixel, U64(index) * nl + s, c.seed, lightAddress};
                    r[0] = sample::draw(strat, sample::CameraDimensions + 2, c.sampling);
                    r[1] = sample::draw(strat, sample::CameraDimensions + 3, c.sampling);
                }
                V3 wi;
                lights::Hit lh;
                if (!lights::sample(L, st.P, cullN, r, wi, lh)) continue;
                float pdfL;
                const V3 Li = lights::eval(L, st.P, wi, lh, pdfL);
                if (shade::isExactlyZero(Li) || !(pdfL > 0) || !shade::finite3(Li)) continue;
                const Color factor = pv.T * Li * (1.0f / (float(nl) * pdfL));
                const U32 flags = shade::surfaceFlags(slice, bsdf.spherical, wi);
                Color t{0, 0, 0};
                bool any = false;
                for (U32 k = 0; k < bsdf.topCount; ++k) {
                    const shade::Lobe& lobe = shade::topLobe(bsdf, k);
                    if (!shade::matchesFlags(lobe.type, flags)) continue;
                    float pdf;
                    const Color f = shade::lobeEval(bsdf, bsdf.top[k], slice, wi, pdf);
                    if (shade::isSampleInvalid(f, pdf)) continue;
                    Color tk = factor * f * lights::powerHeuristic(float(nl) * pdfL, float(lobeSamples[k]) * pdf);
                    if (clampHere) tk = smartClamp(tk, c.clampValue);
                    t += tk;
                    any = true;
                }
                if (!any) continue;
                if (rr) {
                    float scale;
                    if (!roulette(shade::luminance(t), c.rrThreshold, u, scale)) continue;
                    t = t * scale;
                }
                if (shade::isExactlyZero(t) || !shade::finite3(t)) continue;
                const V3 shadowOrigin = curveEpsilon > 0.0f ? st.P : (shade::dot(wi, st.Ng) >= 0.0f ? above : below);
                const float shadowNear = curveEpsilon > 0.0f ? curveEpsilon : 0.0f;
                const float shadowFar = curveEpsilon > 0.0f ? fmaxf(lh.distance * lights::HitEpsilonEnd, 2.0f * curveEpsilon)
                                                            : lh.distance * lights::HitEpsilonEnd;
                if (backend.visible(shadowOrigin, wi, shadowNear, shadowFar)) {
                    if (c.volumeCount) {
                        // The volumes on the shadow ray's way (transmittance()).
                        sample::Identity tid = lid;
                        tid.branch = childBranch(lightAddress, s, 0xfffb);
                        Stream vs(tid, pv.depth, 0);
                        t = t * volumeTransmittance(c, backend, vs, shadowOrigin, wi, shadowNear, shadowFar, 1.0f);
                    }
                    radiance += t;
                }
            }
        }

        // BSDF samples (drawBsdfSamples, integrateBsdfSample, addIndirectAndDirectVisibleContributions).
        for (U32 k = 0; k < bsdf.topCount; ++k) {
            const U32 record = bsdf.top[k];
            const shade::Lobe& lobe = bsdf.records[record];
            const U32 nk = lobeSamples[k];
            const bool mirror = (lobe.type & shade::Mirror) != 0, hair = (lobe.flags & shade::FlagHair) != 0;
            const bool lobeIndirect = shade::matchesFlags(lobe.type, indirectFlags) || (hair && pv.hairDepth < c.maxHairDepth);
            const U64 lobeBranch = childBranch(pv.branch, k, 0xffff);
            for (U32 i = 0; i < nk; ++i) {
                const U64 sampleBranch = childBranch(lobeBranch, i, 0);
                sample::Identity bid = root;
                bid.branch = sampleBranch;
                Stream bs(bid, pv.depth, 0);
                float r1 = bs.next(), r2 = bs.next();
                const float choice = bs.next(), u = bs.next();
                if (split && !mirror) {
                    // The hit's samples of a lobe are one stratified set: Sobol indices index * nk + i.
                    const sample::Identity strat{pixel, U64(index) * nk + i, c.seed, lobeBranch};
                    r1 = sample::draw(strat, sample::CameraDimensions, c.sampling);
                    r2 = sample::draw(strat, sample::CameraDimensions + 1, c.sampling);
                }
                V3 wi;
                float pdf;
                const Color f = shade::lobeSample(bsdf, record, slice, r1, r2, wi, pdf);
                if (!shade::isSampleValid(f, pdf) || !shade::finite3(f) || !shade::finite3(wi)) continue;
                if (!shade::matchesFlags(lobe.type, shade::surfaceFlags(slice, bsdf.spherical, wi))) continue;
                const Color pt = pv.T * f * (1.0f / (float(nk) * pdf));
                // The lights the ray meets: one chosen uniformly, its radiance times their number.
                U32 hits = 0;
                for (U32 j = 0; j < c.lightCount; ++j) {
                    lights::Hit lh;
                    if ((mask >> j & 1) && lights::intersect(backend.light(j), st.P, cullN, wi, 3.4028234663852886e+38f, lh)) ++hits;
                }
                Color direct{0, 0, 0};
                float lightDistance = 0;
                bool lightHit = false;
                if (hits) {
                    const U32 chosen = U32(choice * float(hits)) < hits ? U32(choice * float(hits)) : hits - 1;
                    for (U32 j = 0, seen = 0; j < c.lightCount; ++j) {
                        lights::Hit lh;
                        if (!(mask >> j & 1) || !lights::intersect(backend.light(j), st.P, cullN, wi, 3.4028234663852886e+38f, lh))
                            continue;
                        if (seen++ != chosen) continue;
                        float pdfL;
                        const V3 Li = lights::eval(backend.light(j), st.P, wi, lh, pdfL) * float(hits);
                        if (!shade::isExactlyZero(Li) && pdfL > 0 && shade::finite3(Li)) {
                            direct = mirror ? Li * pt : Li * pt * lights::powerHeuristic(float(nk) * pdf, float(nl) * pdfL);
                            lightDistance = lh.distance;
                            lightHit = true;
                        }
                        break;
                    }
                }
                if (!lightHit && !doIndirect) continue;  // an invalid sample (integrateBsdfSample)
                if (clampHere) direct = smartClamp(direct, c.clampValue);
                Color indirect = doIndirect ? pt : Color{0, 0, 0};
                if (rr) {
                    float scale;
                    if (!roulette(fmaxf(shade::luminance(direct), shade::luminance(indirect)), c.rrThreshold, u, scale)) continue;
                    direct = direct * scale;
                    indirect = indirect * scale;
                }
                const V3 origin = shade::dot(wi, st.Ng) >= 0.0f ? above : below;
                float start = 0.0f;
                if (curveEpsilon > 0.0f) {
                    const float denom = fabsf(shade::dot(st.Ng, wi));
                    start = shade::isZero(denom) ? curveEpsilon : curveEpsilon / denom;
                }
                if (lightHit && !shade::isBlack(direct) && shade::finite3(direct) &&
                    backend.visible(origin, wi, start, lightDistance * lights::HitEpsilonEnd)) {
                    if (c.volumeCount) {
                        sample::Identity tid = bid;
                        tid.branch = childBranch(sampleBranch, 0xfffb, 0);
                        Stream vs(tid, pv.depth, 0);
                        direct = direct * volumeTransmittance(c, backend, vs, origin, wi, start, lightDistance * lights::HitEpsilonEnd, 1.0f);
                    }
                    radiance += direct;
                }
                if (!lobeIndirect || shade::isExactlyZero(indirect) || !shade::finite3(indirect)) continue;
                // Transparency threshold (mirror transmission lobes accumulate opacity).
                float opacity = pv.accumOpacity;
                if (mirror && (lobe.type & shade::Transmission)) {
                    const float transparency = (f.x + f.y + f.z) / 3.0f;
                    opacity = pv.accumOpacity + (1 - transparency) * (1 - pv.accumOpacity);
                    if (opacity > c.transparencyThreshold) continue;
                }
                if (top >= MaxPending) return SampleStatus::Error;
                Pending child;
                child.origin = origin;
                child.dir = wi;
                child.diff = shade::scatterDifferentials(bsdf, record, st, wi, r1, r2, origin, primaryScale);
                child.T = indirect;
                child.branch = sampleBranch;
                child.depth = pv.depth + 1;
                child.diffuseDepth = pv.diffuseDepth + ((lobe.type & shade::Diffuse) ? 1 : 0);
                child.glossyDepth = pv.glossyDepth + ((lobe.type & shade::Glossy) ? 1 : 0);
                child.mirrorDepth = pv.mirrorDepth + (mirror ? 1 : 0);
                child.nonMirrorDepth = pv.nonMirrorDepth + (mirror ? 0 : 1);
                child.hairDepth = pv.hairDepth + (hair ? 1 : 0);
                child.presenceDepth = pv.presenceDepth;
                child.subsurfaceDepth = subsurfaceDepth;
                child.farT = 3.402823466e+38f;
                child.nearT = start;
                // Every bounce counts toward the volume depth (PathIntegratorMultiSampler: parent's + 1), so with
                // max_volume_depth one only camera rays gather volume scattering.
                child.volumeDepth = pv.volumeDepth + 1;
                child.accumOpacity = opacity;
                child.lobeType = lobe.type;
                // computeMinRoughness: the path's roughness floor for later hair lobes.
                child.minRoughness[0] = child.minRoughness[1] = 0.0f;
                if (c.roughnessClamping > 0.0f) {
                    float ru, rv;
                    if (shade::lobeRoughness(bsdf, record, ru, rv)) {
                        child.minRoughness[0] = fminf(ru, rv) * c.roughnessClamping;
                        child.minRoughness[1] = fmaxf(ru, rv) * c.roughnessClamping;
                    }
                }
                child.minRoughness[0] = shade::clampf(child.minRoughness[0], pv.minRoughness[0], 1.0f);
                child.minRoughness[1] = shade::clampf(child.minRoughness[1], pv.minRoughness[1], 1.0f);
                stack[top++] = child;
            }
        }
    }
    out.rgb[0] = radiance.x;
    out.rgb[1] = radiance.y;
    out.rgb[2] = radiance.z;
    out.alpha = primaryHit;
    return SampleStatus::Done;
}

// The GPU programs carry one integrator (XPU2_PATHS_ONLY): two in one kernel cost
// the path tracer registers.
template <class Backend>
X2_HD inline SampleStatus integrate(const mixed::Config& c, U32 pixel, U32 index, Backend& backend, Radiance& out) {
#if defined(XPU2_PATHS_ONLY)
    return integratePaths(c, pixel, index, backend, out);
#else
    return c.paths ? integratePaths(c, pixel, index, backend, out) : integrateDirect(c, pixel, index, backend, out);
#endif
}

// The unit of work (spec §7): one 8x8 tile of the image and a range of sample
// indices, not yet started. 16 bytes, so moving one across PCIe is cheap.
struct Chunk {
    U32 tile;   // tile index, row-major over the image's 8x8 tiles
    U32 first;  // first sample index
    U32 count;  // number of sample indices
    U32 cell;   // owning cell, for per-cell accounting
};
static_assert(sizeof(Chunk) == 16, "Chunks are 16 bytes");

constexpr U32 TileSize = 8, TilePixels = TileSize * TileSize;

// Adaptive frames (async_adaptive.h): a chunk's first field holds its pass and its
// sample offset within the pass; each active pixel's sample index is its own base
// (the samples it already has) plus that offset, so a pixel's indices stay
// contiguous, as MoonRay keeps them. Pass tables live in a ring of PassSlots.
constexpr U32 MaxPasses = 160, PassSlots = 4, PassShift = 16;
X2_HD inline U32 chunkPass(const Chunk& c) { return c.first >> PassShift; }
X2_HD inline U32 chunkOffset(const Chunk& c) { return c.first & ((1u << PassShift) - 1); }

// A rounded product and sum that the CUDA compiler may not fuse into one
// multiply-add, so the host (built without contraction) and the GPU work a value
// out alike.
X2_HD inline float mulRn(float a, float b) {
#if defined(__CUDA_ARCH__)
    return __fmul_rn(a, b);
#else
    return a * b;
#endif
}
X2_HD inline float addRn(float a, float b) {
#if defined(__CUDA_ARCH__)
    return __fadd_rn(a, b);
#else
    return a + b;
#endif
}

// One pixel's adaptive error from its sums, its odd-index sums and its sample
// count, on either device and alike on both (MoonRay's
// estimatePixelErrorInternal): the luma of the difference between the even and
// odd half-images, over the square root of the pixel's luma, plus the alpha
// difference. ErrorNotReady until both halves have a sample.
constexpr float ErrorNotReady = -1.f;
X2_HD inline float pixelError(const double total[4], const double odd[4], U32 samples) {
    const float n = float(samples), nOdd = float(samples / 2), nEven = n - nOdd;
    if (nOdd <= 0 || nEven <= 0) return ErrorNotReady;
    float diff[4], avg[3];
    for (int c = 0; c < 4; ++c) {
        const float t = float(total[c]), o = float(odd[c]);
        if (t != t || o != o) return 0.f;
        diff[c] = fabsf(addRn(mulRn(t, nOdd), -mulRn(o, n)) / mulRn(nOdd, nEven));
        if (c < 3) avg[c] = t / n;
    }
    auto luma = [](const float v[3]) {
        return addRn(addRn(mulRn(0.299f, v[0]), mulRn(0.587f, v[1])), mulRn(0.114f, v[2]));
    };
    const float lumDiff = luma(diff), lumAvg = luma(avg);
    if (lumAvg <= 0) return diff[3];
    return addRn(lumDiff / sqrtf(lumAvg), diff[3]);
}

// Pixel of the i-th position of a tile, or ~0u when it lies outside the image.
X2_HD inline U32 tilePixel(U32 tile, U32 position, U32 width, U32 height) {
    const U32 tilesX = (width + TileSize - 1) / TileSize;
    const U32 x = (tile % tilesX) * TileSize + position % TileSize;
    const U32 y = (tile / tilesX) * TileSize + position / TileSize;
    return x < width && y < height ? y * width + x : ~0u;
}

}  // namespace xpu2::interactive::async
