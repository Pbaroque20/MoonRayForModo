// The GPU program's DwaBase module (INDEXER.md, 5): a DwaBase material tree resolved, its layers blended
// (shade_dwalayer.h), as a direct callable of the material module. OptiX compiles it beside the other modules.
#include "async_gpu_device.h"

extern "C" __device__ bool __direct_callable__dwaResolve(const float* pool, const shade::DwaTree* tree, const shade::State* st,
                                                         shade::DwaParams* slots, const shade::Color* regs) {
    return shade::resolveDwaTree(pool, *tree, *st, slots, regs);
}
