// The GPU program's extras module (INDEXER.md, 5): the camera's ray, the light and visibility AOVs' accumulation and
// the material AOVs, as direct callables of the path tracer. None of them traces; out of the ray generation program,
// whose whole call graph OptiX compiles as one task, they compile beside it, in parallel.
#include "async_gpu_device.h"

extern "C" __device__ unsigned __direct_callable__camera(const surface::Camera* c, float x, float y, float lensU, float lensV, float time,
                                                         surface::Ray* out) {
    return unsigned(surface::cameraSampleHere(*c, x, y, lensU, lensV, time, *out));
}

extern "C" __device__ bool __direct_callable__aovLight(const aov::Tables* t, float* aovs, float* depths, surface::V3 match,
                                                       const surface::V3* nonMatch, U32 prefixFlags, int state) {
    return aov::lightHere(*t, aovs, depths, match, nonMatch, prefixFlags, state);
}

extern "C" __device__ bool __direct_callable__aovVisibility(const aov::Tables* t, float* aovs, float hits, float attempts, int state,
                                                            bool passthrough) {
    return aov::visibilityHere(*t, aovs, hits, attempts, state, passthrough);
}

extern "C" __device__ void __direct_callable__materialAovs(const aov::Tables* t, float* aovs, float* depths, const aov::MaterialHit* h,
                                                           float depth) {
    aov::materialAovsHere(*t, aovs, depths, *h, depth);
}
