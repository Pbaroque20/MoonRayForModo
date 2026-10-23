// Data shared by the asynchronous GPU lane's host side (async_gpu.h) and its
// OptiX program (async_gpu.cu).
#pragma once
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
    U32 pixel, index, tries, pad;
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
};

// Launch parameters. mode 0 renders; mode 1 applies tile-cache updates.
struct LaunchParams {
    const mixed::Config* config;
    const surface::Lambert* materials;
    U64L traversable;  // OptixTraversableHandle
    const mixed::Geometry* geometry;
    const tex::Maps* maps;

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
};

}  // namespace xpu2::interactive::async
