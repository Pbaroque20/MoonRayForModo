// The asynchronous GPU lane's OptiX program (spec §10, design G2).
//
// Each launch is a fixed-size grid. Every thread claims one sample at a time
// with an atomic on its launch's own counter, first from the parked samples it
// was given, then from its range of chunk items, and exits when both are used
// up; the host sizes the ranges, never the grid (GPU-04). Neighbouring claims
// are neighbouring pixels of the same sample, so a warp traces coherent rays.
// Results accumulate in the device film in double precision (ACC-04, ACC-06).
// Traversal and triangle intersection use the hardware; the shared integrator
// reconstructs each hit with the same arithmetic as the CPU lane.
#include <optix.h>
#include <optix_device.h>
#include "async_gpu_abi.h"
// Two programs come from this file: XPU2_ADAPTIVE 0 for uniform frames, 1 for
// adaptive ones. OptiX links a pipeline's programs into one kernel, so the
// adaptive paths would otherwise cost every uniform frame registers.
#ifndef XPU2_ADAPTIVE
#define XPU2_ADAPTIVE 1
#endif
using namespace xpu2::interactive;
using namespace xpu2::interactive::async;

extern "C" {
__constant__ LaunchParams params{};
}

static __device__ float3 f3(surface::V3 v) { return make_float3(v.x, v.y, v.z); }

extern "C" __global__ void __miss__radiance() { optixSetPayload_0(0xffffffffu); }
extern "C" __global__ void __miss__shadow() { optixSetPayload_0(0u); }
extern "C" __global__ void __closesthit__triangle() {
    optixSetPayload_0(optixGetInstanceId());
    optixSetPayload_1(optixGetPrimitiveIndex());
}
// A curve span (MoonRay XPU's curve programs, curve_core.h): only the distance is reported; the hit is worked out
// again from the span afterwards, as on the CPU.
extern "C" __global__ void __intersection__curve() {
    const curves::Set& c = params.meshAttributes[optixGetInstanceId()].curve;
    const float3 o = optixGetObjectRayOrigin(), d = optixGetObjectRayDirection();
    curves::Hit h;
    if (curves::intersectSpan(c, optixGetPrimitiveIndex(), surface::V3{o.x, o.y, o.z}, surface::V3{d.x, d.y, d.z}, optixGetRayTmin(),
                              optixGetRayTmax(), h))
        optixReportIntersection(h.t, 0);
}
// A curve hit worked out again from its span (async_cpu.h's curveHit, the same arithmetic).
static __device__ bool curveHit(const curves::Set& c, const surface::Ray& ray, resume::Hit& out) {
    curves::Hit h;
    if (!curves::intersectSpan(c, out.prim, ray.origin, ray.direction, ray.nearT, ray.farT, h)) return false;
    out.t = h.t;
    out.u = h.u;
    out.v = h.v;
    out.point = shade::V3{ray.origin.x + ray.direction.x * h.t, ray.origin.y + ray.direction.y * h.t, ray.origin.z + ray.direction.z * h.t};
    out.origin = out.below = out.point;
    const bool roundCubic = c.round && c.basis == curves::BasisBspline;
    out.normal = roundCubic ? h.Ng : shade::normalize(-ray.direction);
    const U32 first = curves::spanVertex(c, out.prim);
    float radius;
    if (c.basis == curves::BasisLinear) {
        radius = curves::point(c, first).w * (1.0f - h.u) + curves::point(c, first + 1).w * h.u;
    } else {
        float w[4];
        curves::cubicWeights(c.basis, h.u, w);
        radius = w[0] * curves::point(c, first).w + w[1] * curves::point(c, first + 1).w + w[2] * curves::point(c, first + 2).w +
                 w[3] * curves::point(c, first + 3).w;
    }
    out.epsilon = 1.5f * radius;
    return shade::finite3(out.point) && out.epsilon > 0.0f;
}

// Records each missing fine-detail tile once (the first sample to miss it asks
// for it), and marks tracked tiles that are read.
struct RequestSink {
    __device__ void operator()(unsigned tile) const {
        if (!tile) return;
        if (atomicCAS(&params.tileState[tile], 0u, 1u) == 0u) {
            const U64L at = atomicAdd(&params.state->requestTail, 1ull);
            params.requests[at % params.requestCapacity] = tile;
        }
    }
    __device__ void touch(unsigned tile) const {
        if (!params.touched[tile]) params.touched[tile] = 1;
    }
};

// The scene's textures for the maps (shade_mapnodes.h): a miss asks for the tile.
struct DeviceTextures {
    const tex::Image* const* images;
    U32 count;
    __device__ U32 lookup(U32 texture, tex::Binding b, const tex::Footprint& f, surface::V3& out) const {
        if (texture >= count || !images[texture]) return tex::Invalid;
        b.image = images[texture];
        RequestSink sink;
        return tex::lookup(b, f, out, sink);
    }
};

struct GpuBackend {
    __device__ resume::Hit trace(const surface::Ray& ray) {
        unsigned instance = ~0u, primitive = 0;
        optixTrace(params.traversable, f3(ray.origin), f3(ray.direction), ray.nearT, ray.farT, 0.f, 1,
                   OPTIX_RAY_FLAG_DISABLE_ANYHIT, 0, 1, 0, instance, primitive);
        resume::Hit h;
        if (instance == ~0u || instance >= params.config->meshes) return h;
        h.geom = instance;
        h.prim = primitive;
        if (params.meshAttributes && params.meshAttributes[instance].curve.basis) {
            if (!curveHit(params.meshAttributes[instance].curve, ray, h)) return resume::Hit{};
            return h;
        }
        const auto m = params.geometry[instance];
        if (primitive >= m.triangleCount) {
            h.normal = {};
            return h;
        }
        const auto t = m.triangles[primitive];
        if (!resume::geometryHit(h, ray, m.vertices[t.a], m.vertices[t.b], m.vertices[t.c])) h.normal = {};
        return h;
    }
    __device__ unsigned material(const resume::Hit& h, const surface::Ray& ray, surface::Lambert& out) {
        const auto& c = *params.config;
        if (h.geom >= c.meshes) return tex::Invalid;
        out = params.materials[h.geom];
        if (!c.textures) return tex::Ready;
        if (!params.maps) return tex::Invalid;
        const auto m = params.geometry[h.geom];
        const auto t = m.triangles[h.prim];
        tex::Footprint f;
        if (!tex::footprint(m.vertices[t.a], m.vertices[t.b], m.vertices[t.c], ray, h.u, h.v, c.spp, f, c.spatial != 0))
            return tex::Invalid;
        const auto maps = params.maps[h.geom];
        surface::V3* bases[2] = {&out.albedo, &out.emission};
        const tex::Binding bindings[2] = {maps.diffuse, maps.emission};
        RequestSink sink;
        for (int i = 0; i < 2; ++i) {
            const auto& b = bindings[i];
            auto& v = *bases[i];
            if (!b.image || (v.x == 0 && v.y == 0 && v.z == 0)) continue;
            surface::V3 color;
            const auto status = tex::lookup(b, f, color, sink);
            if (status != tex::Ready) return status;
            v = {v.x * color.x, v.y * color.y, v.z * color.z};
        }
        return tex::Ready;
    }
    __device__ U32 materialId(U32 geom) const { return params.meshMaterials[geom].offset; }
    __device__ resume::Hit traceMaterial(surface::Ray ray, U32 material) {
        for (int k = 0; k < 64; ++k) {
            const resume::Hit h = trace(ray);
            if (h.geom == ~0u || materialId(h.geom) == material) return h;
            ray.nearT = h.t + fmaxf(1e-6f, h.t * 1e-6f);
            if (!(ray.nearT < ray.farT)) break;
        }
        return resume::Hit{};
    }
    __device__ bool surfaceState(const resume::Hit& h, const surface::Ray& ray, shade::State& st) {
        const auto& c = *params.config;
        if (h.geom >= c.meshes) return false;
        if (params.meshAttributes[h.geom].curve.basis) {
            if (!shade::curveState(params.meshAttributes[h.geom], h.prim, h.u, h.v, h.normal, h.point, ray.direction, st)) return false;
            st.geom = h.geom;
            shade::curveDifferentials(params.meshAttributes[h.geom], ray, c.spp, st);
            return true;
        }
        const auto m = params.geometry[h.geom];
        const auto t = m.triangles[h.prim];
        if (!shade::hitState(params.meshAttributes[h.geom], h.prim, t.a, t.b, t.c, m.vertices[t.a], m.vertices[t.b],
                             m.vertices[t.c], h.u, h.v, h.point, ray.direction, st))
            return false;
        st.geom = h.geom;
        shade::hitDifferentials(params.meshAttributes[h.geom], h.prim, t.a, t.b, t.c, m.vertices[t.a], m.vertices[t.b],
                                m.vertices[t.c], ray, c.spp, st);
        return true;
    }
    // The path tracer's hit: its shading state, and its material's Bsdf (shade_material.h).
    __device__ unsigned shade(const resume::Hit& h, const surface::Ray& ray, shade::State& st, shade::Bsdf& bsdf, float& presence) {
        const auto& c = *params.config;
        if (h.geom >= c.meshes) return tex::Invalid;
        if (params.meshAttributes[h.geom].curve.basis) {
            const shade::MeshAttributes& a = params.meshAttributes[h.geom];
            if (!shade::curveState(a, h.prim, h.u, h.v, h.normal, h.point, ray.direction, st)) return tex::Invalid;
            st.geom = h.geom;
            st.worldToRender = c.worldToRender;
            st.worldToObject = a.worldToObject;
            shade::curveDifferentials(a, ray, c.spp, st);
            const DeviceTextures textures{params.textures, params.textureCount};
            return shade::shadeMaterial(params.meshMaterials[h.geom], params.materialPool, st, textures, bsdf, presence, dwaSlots(),
                                        glitter());
        }
        const auto m = params.geometry[h.geom];
        const auto t = m.triangles[h.prim];
        if (!shade::hitState(params.meshAttributes[h.geom], h.prim, t.a, t.b, t.c, m.vertices[t.a], m.vertices[t.b],
                             m.vertices[t.c], h.u, h.v, h.point, ray.direction, st))
            return tex::Invalid;
        st.geom = h.geom;
        st.worldToRender = c.worldToRender;
        st.worldToObject = params.meshAttributes[h.geom].worldToObject;
        const shade::MaterialRecord& record = params.meshMaterials[h.geom];
        shade::hitDifferentials(params.meshAttributes[h.geom], h.prim, t.a, t.b, t.c, m.vertices[t.a], m.vertices[t.b],
                                m.vertices[t.c], ray, c.spp, st);
        const DeviceTextures textures{params.textures, params.textureCount};
        return shade::shadeMaterial(record, params.materialPool, st, textures, bsdf, presence, dwaSlots(), glitter());
    }
    __device__ bool visible(surface::V3 o, surface::V3 d) { return visible(o, d, __int_as_float(0x7f800000)); }
    // Unoccluded up to distance (a shadow ray toward a light).
    __device__ bool visible(surface::V3 o, surface::V3 d, float distance) { return visible(o, d, 0.0f, distance); }
    // Unoccluded between near and far (a shadow ray from a curve skips its epsilon).
    __device__ bool visible(surface::V3 o, surface::V3 d, float near, float distance) {
        unsigned occluded = 1, unused = 0;
        optixTrace(params.traversable, f3(o), f3(d), near, distance, 0.f, 1,
                   OPTIX_RAY_FLAG_DISABLE_ANYHIT | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT |
                       OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT,
                   0, 1, 1, occluded, unused);
        return occluded == 0;
    }
    __device__ shade::Bsdf& bsdf() {
        return *reinterpret_cast<shade::Bsdf*>(params.scratch + U64L(optixGetLaunchIndex().x) * params.scratchStride);
    }
    __device__ paths::Pending* pending() {
        return reinterpret_cast<paths::Pending*>(params.scratch + U64L(optixGetLaunchIndex().x) * params.scratchStride +
                                                 ((sizeof(shade::Bsdf) + 15) & ~size_t(15)));
    }
    __device__ shade::DwaParams* dwaSlots() {
        return reinterpret_cast<shade::DwaParams*>(params.scratch + U64L(optixGetLaunchIndex().x) * params.scratchStride +
                                                   ((sizeof(shade::Bsdf) + 15) & ~size_t(15)) +
                                                   ((sizeof(paths::Pending) * paths::MaxPending + 15) & ~size_t(15)));
    }
    __device__ shade::GlitterScratch* glitter() {
        if (!params.glitterOffset) return nullptr;
        return reinterpret_cast<shade::GlitterScratch*>(params.scratch + U64L(optixGetLaunchIndex().x) * params.scratchStride +
                                                        params.glitterOffset);
    }
    __device__ const lights::Light& light(U32 i) const { return params.lights[i]; }
    // The volumes, and a ray's crossings of their meshes past tnear, nearest first (the instances of visibility 2),
    // each entering or leaving by the triangle's geometric normal; repeats at one distance dropped.
    __device__ const volume::Shader* volumes() const { return params.volumes; }
    __device__ U32 volumeCrossings(surface::V3 o, surface::V3 d, float tnear, volume::Crossing* x, U32 max) {
        U32 n = 0;
        float t = tnear;
        for (U32 k = 0; k < 4 * max && n < max; ++k) {
            unsigned instance = ~0u, primitive = 0;
            optixTrace(params.traversable, f3(o), f3(d), t, __int_as_float(0x7f800000), 0.f, 2, OPTIX_RAY_FLAG_DISABLE_ANYHIT, 0, 1, 0,
                       instance, primitive);
            if (instance == ~0u || instance >= params.config->meshes) break;
            const auto m = params.geometry[instance];
            if (primitive >= m.triangleCount) break;
            const auto tri = m.triangles[primitive];
            const surface::V3 a = m.vertices[tri.a], b = m.vertices[tri.b], c = m.vertices[tri.c];
            const surface::Ray ray{o, d, {}, {}, t, __int_as_float(0x7f800000)};
            resume::Hit h;
            if (!resume::geometryHit(h, ray, a, b, c)) break;
            const surface::V3 ng = surface::cross(surface::add(b, surface::mul(a, -1.0f)), surface::add(c, surface::mul(a, -1.0f)));
            const U32 v = U32(params.meshVolumes[instance]);
            const U32 flags = surface::dot(d, ng) < 0.0f ? volume::Entry : volume::Exit;
            if (!(n > 0 && x[n - 1].t == h.t && x[n - 1].volume == v && x[n - 1].flags == flags)) x[n++] = volume::Crossing{h.t, v, flags};
            t = h.t + fmaxf(1e-6f, h.t * 1e-6f);
        }
        return n;
    }
    __device__ U32 lightMask(U32 geom) const { return params.meshLights[geom]; }
};

static __device__ void run(GpuBackend& backend, U32 pixel, U32 index, U32 tries, U32 pass, bool chain = false) {
    Radiance r;
    const SampleStatus status = integrate(*params.config, pixel, index, backend, r);
    if (status == SampleStatus::Done) {
        double* s = params.sums + size_t(pixel) * 4;
        atomicAdd(s + 0, r.rgb[0]);
        atomicAdd(s + 1, r.rgb[1]);
        atomicAdd(s + 2, r.rgb[2]);
        atomicAdd(s + 3, r.alpha);
        atomicAdd(params.counts + pixel, 1u);
#if XPU2_ADAPTIVE
        {
            if (index & 1) {  // MoonRay's Beauty Odd: the odd-index samples
                double* o = params.odd + size_t(pixel) * 4;
                atomicAdd(o + 0, r.rgb[0]);
                atomicAdd(o + 1, r.rgb[1]);
                atomicAdd(o + 2, r.rgb[2]);
                atomicAdd(o + 3, r.alpha);
            }
            atomicAdd(&params.state->passDone[pass], 1u);
        }
#endif
    } else if (status == SampleStatus::Miss) {
        // Park it; the host sized this launch so the queue cannot overflow.
        const U64L at = atomicAdd(&params.state->parkedTail, 1ull);
        params.parked[at % params.parkedCapacity] = {pixel, index, tries, pass};
        if (chain) params.state->chainStall = 1;  // the chain waits for the host to land its tile
    } else {
        atomicAdd(&params.state->errors, 1u);
    }
}

static __device__ void commit() {
    const unsigned i = optixGetLaunchIndex().x;
    if (i >= params.updateCount) return;
    const TileUpdate u = params.updates[i];
    auto** entry = reinterpret_cast<const surface::V3**>(params.pageEntry[u.tile]);
    *entry = u.slot == NoSlot ? nullptr : params.slab + size_t(u.slot) * params.slabTileTexels;
    params.tileState[u.tile] = u.slot == NoSlot ? 0u : 2u;
}

#if XPU2_ADAPTIVE
// The film's per-pixel adaptive errors, read by the host's error trees.
static __device__ void errors() {
    const unsigned i = optixGetLaunchIndex().x;
    if (i >= params.pixels) return;
    params.errors[i] = pixelError(params.sums + size_t(i) * 4, params.odd + size_t(i) * 4, params.counts[i]);
}
#endif

#if XPU2_ADAPTIVE
// A pass the chain made on the device (async_adaptive.cu). It runs only if its
// own compaction ran: after a stall or once the frame has converged, the chain's
// later renders find another pass there and do nothing. Threads claim items one
// at a time, as in every render, so slow samples do not hold up a thread's share.
static __device__ void chainRender(GpuBackend& backend) {
    DeviceState* s = params.state;
    if (*reinterpret_cast<volatile U32*>(&s->chainPass) != params.chainPass) return;
    const U64L perTile = U64L(params.chainSize) * TilePixels, items = U64L(s->activeTiles) * perTile;
    const auto& c = *params.config;
    for (;;) {
        const U64L item = atomicAdd(&s->chainClaimed, 1ull);
        if (item >= items) break;
        const U32 t = U32(item / perTile), rest = U32(item % perTile);
        const U32 sample = rest / TilePixels, position = rest % TilePixels;
        if (!(params.activeMasks[t] >> position & 1)) continue;
        const U32 pixel = tilePixel(params.activeTiles[t], position, c.width, c.height);
        run(backend, pixel, params.chainBase[pixel] + sample, 0, params.chainPass, true);
    }
}
#endif

extern "C" __global__ void __raygen__async() {
    if (params.mode == 1) {
        commit();
        return;
    }
#if XPU2_ADAPTIVE
    if (params.mode == 2) {
        errors();
        return;
    }
#endif
    GpuBackend backend;
#if XPU2_ADAPTIVE
    if (params.mode == 3) {
        chainRender(backend);
        return;
    }
#endif
    for (;;) {  // parked samples first: they started before anything else here
        const U64L k = params.parkedBegin + atomicAdd(&params.state->unparked[params.slot], 1u);
        if (k >= params.parkedEnd) break;
        const Parked p = params.parked[k % params.parkedCapacity];
        run(backend, p.pixel, p.index, p.tries + 1, p.pass);
    }
    const auto& c = *params.config;
    for (;;) {
        const U64L item = params.itemBegin + atomicAdd(&params.state->claimed[params.slot], 1u);
        if (item >= params.itemEnd) break;
        const U64L chunkIndex = item / params.itemsPerChunk;
        const U32 offset = U32(item - chunkIndex * params.itemsPerChunk);
        const Chunk chunk = params.ring[chunkIndex % params.ringCapacity];
        const U32 s = offset / TilePixels, position = offset % TilePixels;
        if (s >= chunk.count) continue;
        const U32 pixel = tilePixel(chunk.tile, position, c.width, c.height);
        if (pixel == ~0u) continue;
#if XPU2_ADAPTIVE
        // Only the tile's active pixels, each from its own sample-index base.
        const U32 slot = chunkPass(chunk) % PassSlots;
        if (!(params.passMask[slot][chunk.tile] >> position & 1)) continue;
        run(backend, pixel, params.passBase[slot][pixel] + chunkOffset(chunk) + s, 0, chunkPass(chunk));
#else
        run(backend, pixel, chunk.first + s, 0, 0);
#endif
    }
}
