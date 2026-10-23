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

struct GpuBackend {
    __device__ resume::Hit trace(const surface::Ray& ray) {
        unsigned instance = ~0u, primitive = 0;
        optixTrace(params.traversable, f3(ray.origin), f3(ray.direction), ray.nearT, ray.farT, 0.f, 255,
                   OPTIX_RAY_FLAG_DISABLE_ANYHIT, 0, 1, 0, instance, primitive);
        resume::Hit h;
        if (instance == ~0u || instance >= params.config->meshes) return h;
        h.geom = instance;
        h.prim = primitive;
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
    __device__ bool visible(surface::V3 o, surface::V3 d) {
        unsigned occluded = 1, unused = 0;
        optixTrace(params.traversable, f3(o), f3(d), 0.f, __int_as_float(0x7f800000), 0.f, 255,
                   OPTIX_RAY_FLAG_DISABLE_ANYHIT | OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT |
                       OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT,
                   0, 1, 1, occluded, unused);
        return occluded == 0;
    }
};

static __device__ void run(GpuBackend& backend, U32 pixel, U32 index, U32 tries, U32 pass) {
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
