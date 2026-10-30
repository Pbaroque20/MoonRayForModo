// The GPU program's material module (INDEXER.md, 5): a hit's material, its Bsdf with the map interpreter
// (shade_material.h), and a material's presence, as direct callables. OptiX compiles this module beside the path
// tracer's (async_gpu.cu), in parallel, and never inlines a callable into its caller. They trace no rays.
#include "async_gpu_device.h"

extern "C" __device__ unsigned __direct_callable__shade(const shade::MaterialRecord* m, const float* pool, const shade::State* st,
                                                        const DeviceTextures* textures, shade::Bsdf* bsdf, float* presence,
                                                        shade::DwaParams* slots, shade::GlitterScratch* glitter) {
    return shade::shadeMaterial(*m, pool, *st, *textures, *bsdf, *presence, slots, glitter);
}

extern "C" __device__ unsigned __direct_callable__presence(const shade::MaterialRecord* m, const float* pool, const shade::State* st,
                                                           const DeviceTextures* textures, float* presence) {
    return shade::materialPresence(*m, pool, *st, *textures, *presence);
}
