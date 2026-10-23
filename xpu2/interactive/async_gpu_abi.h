// Data shared by the asynchronous GPU lane's host side (async_gpu.h) and its
// OptiX program (async_gpu.cu).
#pragma once
#include "async_adaptive_core.h"
#include "async_integrator.h"
#if !defined(__CUDACC_RTC__)
#include <optix_types.h>
#endif

namespace xpu2::interactive::async {

using U64L = unsigned long long;
constexpr U32 Slots = 4;  // launches whose claim counters may be live at once

// A sample parked by a texture miss in the GPU's bounded queue (TEXWAIT). It
// runs again on the GPU once its tile is resident, with the same identity.
struct Parked {
    U32 pixel, index, tries, pass;
};
static_assert(sizeof(Parked) == 16, "Parked samples are 16 bytes");

// A change to the fine-detail tile cache, applied on the device between
// launches: the tile's page-table entry points at its slot, or is cleared.
struct TileUpdate {
    U32 tile, slot;  // slot ~0u evicts
};
constexpr U32 NoSlot = ~0u;

struct DeviceState {
    U32 claimed[Slots];       // per-launch claim counters over the launch's chunk items
    U32 unparked[Slots];      // per-launch claim counters over the parked samples it runs first
    U64L parkedTail;          // samples ever parked (a monotonic ring position)
    U64L requestTail;         // tile requests ever made (a monotonic ring position)
    U32 errors;
    U32 pad;
    U32 passDone[MaxPasses];  // adaptive frames: samples completed per pass

    // The adaptive pass chain (async_adaptive.cu). chainStop: the trees have
    // converged or a pass came out empty; chainStall: a chain render parked a
    // sample, so the chain waits for the host. chainPass is the pass the chain
    // made last, which only its own render runs.
    U32 chainStop, chainStall, chainPass, activeTiles;
    U32 chainPasses;     // passes the chain made, an empty last one too
    U32 treeUpdates;
    U64L chainClaimed;   // the chain render's claim counter
    U64L chainSamples;   // samples the chain planned
};
constexpr U32 NoPass = ~0u;

// What the chain's CUDA kernels work on, passed by value to each.
struct ChainArgs {
    DeviceState* state;
    const double* sums;
    const double* odd;
    const U32* counts;
    float* errors;
    const adaptive::IBox* regions;  // each region's bounds, with their overlap
    adaptive::Node* nodes;          // each region's tree at nodeOffset[r], nodeCapacity[r] nodes
    const U32* nodeOffset;
    const U32* nodeCapacity;
    double* sat;                    // each region's summed-area table at satOffset[r]
    const U64L* satOffset;
    U32* regionDone;
    U64L* tileMask;                 // every tile's active pixels for the pass being made
    const U64L* inImage;            // every tile's pixels inside the image
    const U32* tileOrder;           // the tiles cell by cell, as the work grid holds them
    U32* activeTiles;               // the pass's tiles with active pixels, in that order
    U64L* activeMasks;
    U32* planned;                   // samples each pixel will have once the pass has run
    U32* base;                      // each active pixel's first sample index in the pass
    U32 width, height, tiles, tilesX, regionCount;
    float target;
    adaptive::Layout layout;
};

// Launch parameters. mode 0 renders; mode 1 applies tile-cache updates; mode 2
// works out every pixel's adaptive error from the film; mode 3 renders a pass
// the chain made on the device.
struct LaunchParams {
    const mixed::Config* config;
    const surface::Lambert* materials;
    const lights::Light* lights;  // the path tracer's lights, and each mesh's mask over them
    const U32* meshLights;
    const volume::Shader* volumes;  // the volumes bound to meshes (volume_core.h), and each mesh's (-1: none)
    const int* meshVolumes;
    const float* walkSequences;  // MoonRay's integrator sequences for the random walk (cpu_scene.h), or null
    // The path tracer's materials: each mesh's material record and shading attributes, and the
    // records' parameter pool (shade_material.h).
    const shade::MaterialRecord* meshMaterials;
    const shade::MeshAttributes* meshAttributes;
    const float* materialPool;
    // Per launch thread: the path tracer's Bsdf and pending rays (async_integrator.h).
    unsigned char* scratch;
    U64L scratchStride;
    U64L glitterOffset;  // the glitter scratch's place in a thread's scratch (0: the scene has no glitter)
    U64L traversable;  // OptixTraversableHandle
    const mixed::Geometry* geometry;
    const tex::Maps* maps;
    // The scene's textures, as the maps index them (cpu::Plan::textures).
    const tex::Image* const* textures;
    U32 textureCount;

    // Work: chunk items [itemBegin, itemEnd); item = chunk * itemsPerChunk + offset,
    // offset = sample * 64 + position in the tile, so neighbouring threads take
    // neighbouring pixels of the same sample.
    const Chunk* ring;
    U32 ringCapacity, slot;
    U64L itemBegin, itemEnd;
    U32 itemsPerChunk, maxTries;
    // Parked samples [parkedBegin, parkedEnd) run first.
    Parked* parked;
    U32 parkedCapacity, pad0;
    U64L parkedBegin, parkedEnd;

    DeviceState* state;
    double* sums;  // 4 per pixel: rgb and alpha
    U32* counts;   // samples per pixel

    // Fine-detail cache. Tile ids start at 1; 0 is untracked.
    U32* tileState;  // 0 absent, 1 requested, 2 resident
    U32* requests;   // ring of requested tile ids
    U32 requestCapacity, updateCount;
    unsigned char* touched;
    const TileUpdate* updates;
    const U64L* pageEntry;  // address of each tile's page-table entry
    const surface::V3* slab;
    U32 slabTileTexels, mode;

    // Adaptive frames: the pass tables (async_integrator.h), the odd-index sums,
    // and the per-pixel errors the trees are built from.
    U32 adaptive, pixels;
    const U64L* passMask[PassSlots];
    const U32* passBase[PassSlots];
    double* odd;
    float* errors;

    // mode 3: the chain's pass (its active tiles, masks and bases) and its size.
    const U32* activeTiles;
    const U64L* activeMasks;
    const U32* chainBase;
    U32 chainPass, chainSize;
};

}  // namespace xpu2::interactive::async
