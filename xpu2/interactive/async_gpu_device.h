// What every module of the GPU program shares (async_gpu.cu, async_material.cu): the launch parameters, named as
// OptiX links them, and the textures' device side (a miss asks for the tile).
#pragma once
#include <optix.h>
#include <optix_device.h>
#include "async_gpu_abi.h"
using namespace xpu2::interactive;
using namespace xpu2::interactive::async;

extern "C" {
__constant__ LaunchParams params{};
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
    __device__ __noinline__ U32 lookup(U32 texture, tex::Binding b, const tex::Footprint& f, surface::V3& out) const {
        if (texture >= count || !images[texture]) return tex::Invalid;
        b.image = images[texture];
        b.swapCross = b.mode != 3 ? 1u : 0u;  // as XPU's vector shading looks up (displacement: in order)
        RequestSink sink;
        return tex::lookup(b, f, out, sink);
    }
};

// The material callables' places in the binding table (async_material.cu, async_gpu.h Program::create).
enum MaterialCall : unsigned {
    CallShade = 0,
    CallPresence = 1,
    CallMaps = shade::MapsCallable,
    CallLightSample = lights::LightSampleCallable,
    CallLightIntersect = lights::LightIntersectCallable,
    CallLightEval = lights::LightEvalCallable
};
