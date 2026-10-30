// The GPU program's light module (INDEXER.md, 5): the lights' shapes, sampled, intersected and evaluated
// (light_core.h), as direct callables of the path tracer. OptiX compiles it beside the other modules, in parallel.
#include "async_gpu_device.h"

extern "C" __device__ bool __direct_callable__lightSample(const lights::Light* l, surface::V3 p, const surface::V3* n, const float* r,
                                                          surface::V3* wi, lights::Hit* h, float footprint) {
    return lights::sampleShapeHere(*l, p, n, r, *wi, *h, footprint);
}

extern "C" __device__ bool __direct_callable__lightIntersect(const lights::Light* l, surface::V3 p, const surface::V3* n, surface::V3 wi,
                                                             float maxDistance, lights::Hit* h, bool fromCamera) {
    return lights::intersectShapeHere(*l, p, n, wi, maxDistance, *h, fromCamera);
}

extern "C" __device__ void __direct_callable__lightEval(const lights::Light* l, surface::V3 p, surface::V3 wi, const lights::Hit* h,
                                                        float* pdf, float footprint, bool fromCamera, surface::V3* out) {
    *out = lights::evalShapeHere(*l, p, wi, *h, *pdf, footprint, fromCamera);
}
