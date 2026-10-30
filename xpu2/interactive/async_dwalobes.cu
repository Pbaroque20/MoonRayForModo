// The GPU program's DwaBase lobe module (INDEXER.md, 5): a resolved DwaBase material's lobes made, glitter with them
// (shade_dwabase.h), as a direct callable of the material module. OptiX compiles it beside the other modules.
#include "async_gpu_device.h"

extern "C" __device__ bool __direct_callable__dwaLobes(const shade::DwaParams* p, const shade::DwaUniformParams* u, const shade::State* st,
                                                       shade::Builder* bb, const float* pool, shade::GlitterScratch* glitter) {
    return shade::createDwaLobes(*p, *u, *st, *bb, pool, glitter);
}
