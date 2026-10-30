// The GPU program's lobe module (INDEXER.md, 5): a Bsdf's lobes evaluated, sampled and their albedo
// (shade_lobes_eval.h, every lobe family under them), as direct callables of the path tracer. OptiX compiles it beside
// the other modules, in parallel.
#include "async_gpu_device.h"

extern "C" __device__ void __direct_callable__lobeEval(const shade::Bsdf* b, unsigned record, const shade::Slice* s, surface::V3 wi,
                                                       float* pdf, shade::Color* out) {
    *out = shade::lobeEvalHere(*b, record, *s, wi, *pdf);
}

extern "C" __device__ void __direct_callable__lobeSample(const shade::Bsdf* b, unsigned record, const shade::Slice* s, float r1, float r2,
                                                         surface::V3* wi, float* pdf, shade::Color* out) {
    *out = shade::lobeSampleHere(*b, record, *s, r1, r2, *wi, *pdf);
}

extern "C" __device__ void __direct_callable__lobeAlbedo(const shade::Bsdf* b, unsigned record, const shade::Slice* s, shade::Color* out) {
    *out = shade::lobeAlbedoHere(*b, record, *s);
}
