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
#include "async_gpu_device.h"
// One program renders uniform and adaptive frames: the launch's adaptive flag turns on the adaptive film (its odd
// samples, the passes' counts), the error pass and the pass chain. The path tracer is out of line (X2_CALL), so
// the adaptive parts cost a uniform frame no registers, and OptiX compiles one module instead of two of nearly the
// same code.

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


// The film's math filters (async_cpu.h mergeAov, Film.cc's atomicMathFilter): averages and sums add, min and max keep
// the least and greatest, the closest keeps the nearer sample's values under its pixel's lock; force-consistent
// sampling keeps nothing, as MoonRay's vector film does.
static __device__ void atomicMinFloat(float* a, float v) {
    int old = __float_as_int(*a);
    while (v < __int_as_float(old)) {
        const int seen = atomicCAS(reinterpret_cast<int*>(a), old, __float_as_int(v));
        if (seen == old) break;
        old = seen;
    }
}
static __device__ void atomicMaxFloat(float* a, float v) {
    int old = __float_as_int(*a);
    while (v > __int_as_float(old)) {
        const int seen = atomicCAS(reinterpret_cast<int*>(a), old, __float_as_int(v));
        if (seen == old) break;
        old = seen;
    }
}
static __device__ void mergeAovs(const aov::Tables& t, U32 pixel, const float* values, const float* depths) {
    float* acc = params.aovs + size_t(pixel) * t.channels;
    for (U32 i = 0; i < t.count; ++i) {
        const aov::Entry& e = t.entries[i];
        float* d = acc + e.offset;
        const float* v = values + e.offset;
        switch (e.filter) {
        case aov::FilterAvg:
        case aov::FilterSum:
            for (U32 c = 0; c < e.channels; ++c)
                if (v[c] != 0.0f) atomicAdd(d + c, v[c]);
            break;
        case aov::FilterMin:
            for (U32 c = 0; c < e.channels; ++c) atomicMinFloat(d + c, v[c]);
            break;
        case aov::FilterMax:
            for (U32 c = 0; c < e.channels; ++c) atomicMaxFloat(d + c, v[c]);
            break;
        case aov::FilterClosest: {
            volatile float* depth = params.aovDepths + size_t(pixel) * t.closestCount + e.closest;
            if (!(depths[e.closest] < *depth)) break;
            U32* lock = params.aovLocks + pixel;
            for (bool done = false; !done;) {  // no thread spins on a lock its own warp holds
                if (atomicCAS(lock, 0u, 1u) == 0u) {
                    __threadfence();
                    if (depths[e.closest] < *depth) {
                        *depth = depths[e.closest];
                        for (U32 c = 0; c < e.channels; ++c) reinterpret_cast<volatile float*>(d)[c] = v[c];
                    }
                    __threadfence();
                    atomicExch(lock, 0u);
                    done = true;
                }
            }
            break;
        }
        default: break;
        }
    }
}
// A sample's Cryptomatte events into its pixel's fragment lists (CryptoBuffer::add), in every category.
static __device__ void mergeCrypto(U32 pixel, const aov::CryptoEvent* events, U32 count) {
    for (U32 k = 0; k < count; ++k) {
        const aov::CryptoEvent& e = events[k];
        if (!e.used || !(e.increment || e.credit)) continue;
        for (U32 c = 0; c < params.cryptoCategories; ++c) {
            const float id = c == 0 ? e.id : c == 1 ? e.materialId : e.assetId;
            U32* head = params.cryptoHeads + size_t(pixel) * params.cryptoCategories + c;
            U32* lock = params.cryptoLocks + pixel;
            for (bool done = false; !done;) {  // no thread spins on a lock its own warp holds
                if (atomicCAS(lock, 0u, 1u) != 0u) continue;
                __threadfence();
                volatile U32* node = nullptr;
                for (U32 n = *reinterpret_cast<volatile U32*>(head); n != ~0u;) {
                    volatile U32* m = params.cryptoNodes + size_t(n) * params.cryptoNodeWords;
                    if (__uint_as_float(m[1]) == id && (!params.cryptoMultiPresence || m[4] == e.presenceDepth)) {
                        node = m;
                        break;
                    }
                    n = m[0];
                }
                if (!node) {
                    const U32 n = atomicAdd(params.cryptoNodeCount, 1u);
                    if (n < params.cryptoNodeCapacity) {
                        node = params.cryptoNodes + size_t(n) * params.cryptoNodeWords;
                        for (U32 w = 2; w < params.cryptoNodeWords; ++w) node[w] = 0u;
                        node[0] = *reinterpret_cast<volatile U32*>(head);
                        node[1] = __float_as_uint(id);
                        node[3] = 1u;  // a new fragment counts one sample (Cryptomatte.cc's Fragment)
                        node[4] = e.presenceDepth;
                        __threadfence();
                        *reinterpret_cast<volatile U32*>(head) = n;
                    } else {
                        atomicAdd(&params.state->errors, 1u);
                    }
                } else if (e.increment) {
                    node[3] = node[3] + 1u;
                }
                if (node) {
                    node[2] = __float_as_uint(__uint_as_float(node[2]) + e.weight);
                    if (params.cryptoExtras) {
                        const float d[21] = {e.position.x, e.position.y, e.position.z, e.p0.x, e.p0.y, e.p0.z, e.normal.x, e.normal.y, e.normal.z,
                                             e.beauty[0], e.beauty[1], e.beauty[2], e.beauty[3], e.refP.x, e.refP.y, e.refP.z,
                                             e.refN.x, e.refN.y, e.refN.z, e.uv[0], e.uv[1]};
                        for (U32 w = 0; w < 21; ++w)
                            if (e.increment || (w >= 9 && w < 13)) node[5 + w] = __float_as_uint(__uint_as_float(node[5 + w]) + d[w]);
                    }
                }
                __threadfence();
                atomicExch(lock, 0u);
                done = true;
            }
        }
    }
}
// mode 4: a pixel's accumulators readied for a frame (initAovPixel): +inf for min, -inf for max, 0 for the rest,
// and the closest filter's depths +inf.
static __device__ void initAovs() {
    const unsigned i = optixGetLaunchIndex().x;
    if (i >= params.pixels) return;
    const aov::Tables& t = *params.aovTables;
    float* acc = params.aovs + size_t(i) * t.channels;
    for (U32 k = 0; k < t.count; ++k) {
        const aov::Entry& e = t.entries[k];
        const float v = e.filter == aov::FilterMin ? aov::infinity() : e.filter == aov::FilterMax ? -aov::infinity() : 0.0f;
        for (U32 c = 0; c < e.channels; ++c) acc[e.offset + c] = v;
    }
    for (U32 k = 0; k < t.closestCount; ++k) params.aovDepths[size_t(i) * t.closestCount + k] = aov::infinity();
    if (params.aovLocks) params.aovLocks[i] = 0u;
    if (params.heat) params.heat[i] = 0.0;
    if (params.cryptoHeads) {
        for (U32 c = 0; c < params.cryptoCategories; ++c) params.cryptoHeads[size_t(i) * params.cryptoCategories + c] = ~0u;
        params.cryptoLocks[i] = 0u;
        if (i == 0) *params.cryptoNodeCount = 0u;
    }
}

static __device__ __noinline__ void run(GpuBackend& backend, U32 pixel, U32 index, U32 tries, U32 pass, bool chain = false) {
    Radiance r;
    const aov::Tables& at = *params.aovTables;
    if (at.channels) {
        r.aov = reinterpret_cast<float*>(params.scratch + U64L(optixGetLaunchIndex().x) * params.scratchStride + params.aovOffset);
        r.aovDepth = r.aov + at.channels;
        r.aovBackup = r.aovDepth + at.closestCount;
    }
    if (params.cryptoHeads) {
        r.crypto = reinterpret_cast<aov::CryptoEvent*>(params.scratch + U64L(optixGetLaunchIndex().x) * params.scratchStride + params.cryptoOffset);
        r.cryptoCapacity = params.cryptoEvents;
    }
    const long long began = params.heat ? clock64() : 0;
    const SampleStatus status = integrate(*params.config, pixel, index, backend, r);
    if (status == SampleStatus::Done) {
        if (at.channels) mergeAovs(at, pixel, r.aov, r.aovDepth);
        if (params.cryptoHeads) mergeCrypto(pixel, r.crypto, r.cryptoCount);
        if (params.heat) atomicAdd(params.heat + pixel, double(clock64() - began) * params.secondsPerTick);
        double* s = params.sums + size_t(pixel) * 4;
        atomicAdd(s + 0, r.rgb[0]);
        atomicAdd(s + 1, r.rgb[1]);
        atomicAdd(s + 2, r.rgb[2]);
        atomicAdd(s + 3, r.alpha);
        atomicAdd(params.counts + pixel, 1u);
        if (params.adaptive) {
            if (index & 1) {  // MoonRay's Beauty Odd: the odd-index samples
                double* o = params.odd + size_t(pixel) * 4;
                atomicAdd(o + 0, r.rgb[0]);
                atomicAdd(o + 1, r.rgb[1]);
                atomicAdd(o + 2, r.rgb[2]);
                atomicAdd(o + 3, r.alpha);
            }
            atomicAdd(&params.state->passDone[pass], 1u);
        }
    } else if (status == SampleStatus::Skip) {
        // No camera ray: taken, nothing added.
        if (params.adaptive) atomicAdd(&params.state->passDone[pass], 1u);
    } else if (status == SampleStatus::Miss) {
        // Park it; the host sized this launch so the queue cannot overflow.
        const U64L at = atomicAdd(&params.state->parkedTail, 1ull);
        params.parked[at % params.parkedCapacity] = {pixel, index, tries, pass};
        if (chain) params.state->chainStall = 1;  // the chain waits for the host to land its tile
    } else if (status == SampleStatus::Defer) {
        // For the CPU lane (async_render.h): nothing of the sample reaches the GPU's film.
        const U64L at = atomicAdd(&params.state->deferredTail, 1ull);
        params.deferred[at % params.deferredCapacity] = {pixel, index, 0u, pass};
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

// The film's per-pixel adaptive errors, read by the host's error trees.
static __device__ void errors() {
    const unsigned i = optixGetLaunchIndex().x;
    if (i >= params.pixels) return;
    params.errors[i] = pixelError(params.sums + size_t(i) * 4, params.odd + size_t(i) * 4, params.counts[i]);
}

// The samples a launch renders, from wherever they come, for one call of run(): OptiX inlines a program's whole call
// graph into its entry, so each call of the path tracer would be a copy of it, its traces with it. The parked samples
// first (they started before anything else here), then the launch's chunk items; or a pass the chain made on the
// device (async_adaptive.cu, mode 3).
struct Feed {
    U32 phase = 0;  // 0 the parked samples, 1 the chunk items, 2 the chain's pass, 3 none left
    __device__ bool next(U32& pixel, U32& index, U32& tries, U32& pass, bool& chain) {
        const auto& c = *params.config;
        for (;;) {
            if (phase == 0) {
                const U64L k = params.parkedBegin + atomicAdd(&params.state->unparked[params.slot], 1u);
                if (k >= params.parkedEnd) {
                    phase = 1;
                    continue;
                }
                const Parked p = params.parked[k % params.parkedCapacity];
                pixel = p.pixel;
                index = p.index;
                tries = p.tries + 1;
                pass = p.pass;
                chain = false;
                return true;
            }
            if (phase == 1) {
                const U64L item = params.itemBegin + atomicAdd(&params.state->claimed[params.slot], 1u);
                if (item >= params.itemEnd) {
                    phase = 3;
                    continue;
                }
                const U64L chunkIndex = item / params.itemsPerChunk;
                const U32 offset = U32(item - chunkIndex * params.itemsPerChunk);
                const Chunk chunk = params.ring[chunkIndex % params.ringCapacity];
                const U32 s = offset / TilePixels, position = offset % TilePixels;
                if (s >= chunk.count) continue;
                const U32 at = tilePixel(chunk.tile, position, c.width, c.height, c.viewport);
                if (at == ~0u) continue;
                U32 sampleIndex = chunk.first + s, samplePass = 0;
                if (params.adaptive) {
                    // Only the tile's active pixels, each from its own sample-index base.
                    const U32 slot = chunkPass(chunk) % PassSlots;
                    if (!(params.passMask[slot][chunk.tile] >> position & 1)) continue;
                    sampleIndex = params.passBase[slot][at] + chunkOffset(chunk) + s;
                    samplePass = chunkPass(chunk);
                }
                pixel = at;
                index = sampleIndex;
                tries = 0;
                pass = samplePass;
                chain = false;
                return true;
            }
            if (phase == 2) {
                // Threads claim items one at a time, as in every render, so slow samples do not hold up a thread's share.
                DeviceState* s = params.state;
                const U64L perTile = U64L(params.chainSize) * TilePixels, items = U64L(s->activeTiles) * perTile;
                const U64L item = atomicAdd(&s->chainClaimed, 1ull);
                if (item >= items) {
                    phase = 3;
                    continue;
                }
                const U32 tile = U32(item / perTile), rest = U32(item % perTile);
                const U32 sample = rest / TilePixels, position = rest % TilePixels;
                if (!(params.activeMasks[tile] >> position & 1)) continue;
                pixel = tilePixel(params.activeTiles[tile], position, c.width, c.height);
                index = params.chainBase[pixel] + sample;
                tries = 0;
                pass = params.chainPass;
                chain = true;
                return true;
            }
            return false;
        }
    }
};


extern "C" __global__ void __raygen__async() {
    if (params.mode == 1) {
        commit();
        return;
    }
    if (params.mode == 4) {
        initAovs();
        return;
    }
    if (params.mode == 2) {
        errors();
        return;
    }
    Feed feed;
    if (params.mode == 3) {
        // A pass the chain made runs only if its own compaction ran: after a stall or once the frame has converged,
        // the chain's later renders find another pass there and do nothing.
        if (*reinterpret_cast<volatile U32*>(&params.state->chainPass) != params.chainPass) return;
        feed.phase = 2;
    }
    GpuBackend backend;
    U32 pixel, index, tries, pass;
    bool chain;
    while (feed.next(pixel, index, tries, pass, chain)) run(backend, pixel, index, tries, pass, chain);
}
