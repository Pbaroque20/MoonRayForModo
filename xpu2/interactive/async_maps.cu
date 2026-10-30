// The GPU program's map module (INDEXER.md, 5): the map interpreter (shade_mapnodes.h) as a direct callable, called
// by the material module's callables (async_material.cu). OptiX compiles it beside the other modules, in parallel.
#include "async_gpu_device.h"

extern "C" __device__ unsigned __direct_callable__maps(const float* pool, unsigned program, const shade::State* st,
                                                       const DeviceTextures* textures, shade::Color* regs) {
    return shade::runMapProgram(pool, program, *st, *textures, regs);
}
