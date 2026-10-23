// One complete sample of the admitted spatial domain, shared by the CPU and CUDA
// lanes of the asynchronous renderer (async_render.h).
//
// The estimator, random-number dimensions and operation order are those of
// resume::spatialStep, so every sample has the same expected value as the parity
// pipeline's. What differs is the shape: a sample runs start to finish in one
// call instead of as resumable stages, because the asynchronous lanes schedule
// whole samples. A sample that meets a texture tile that is not resident returns
// Miss before it has contributed anything; it is run again later, on either
// device, with the same identity and so the same random numbers (spec ACC-02,
// ACC-03: a started sample is never dropped).
#pragma once
#include "gpu_jobs.h"
#include "resume_core.h"

namespace xpu2::interactive::async {

using sample::U32;
using sample::U64;

enum class SampleStatus : U32 { Done = 0, Miss = 1, Error = 2 };

// Radiance and alpha (primary-hit coverage) of one sample.
struct Radiance {
    double rgb[3] = {0, 0, 0};
    double alpha = 0;
};

// Backend: trace(ray) -> resume::Hit (geom == ~0u on a miss),
//          material(hit, ray, Lambert&) -> tex::Status,
//          visible(origin, direction) -> bool.
template <class Backend>
X2_HD inline SampleStatus integrate(const mixed::Config& c, U32 pixel, U32 index,
                                    Backend& backend, Radiance& out) {
    using namespace surface;
    if (c.surfaceLimit == 0 || c.surfaceLimit > 8 || pixel >= c.width * c.height)
        return SampleStatus::Error;
    const sample::Identity id{pixel, index, c.seed, 0};

    float x, y;
    Ray ray;
    if (!filter(c.filter, c.filterWidth, sample::draw(id, 0, c.sampling), x) ||
        !filter(c.filter, c.filterWidth, sample::draw(id, 1, c.sampling), y) ||
        !cameraRay(c.camera, float(pixel % c.width) + x, float(pixel / c.width) + y, ray))
        return SampleStatus::Error;

    double radiance[3] = {0, 0, 0}, throughput[3] = {1, 1, 1};
    U32 depth = 0, primaryHit = 0;
    for (;;) {
        resume::Hit hit = backend.trace(ray);
        if (hit.geom == ~0u) {
            if (depth) {
                radiance[0] += throughput[0] * c.sky.x;
                radiance[1] += throughput[1] * c.sky.y;
                radiance[2] += throughput[2] * c.sky.z;
            }
            break;
        }
        if (!depth) primaryHit = 1;

        Lambert material;
        const U32 dimension = 16 + 2 * depth;
        const U32 status = backend.material(hit, ray, material);
        if (status == tex::Miss) return SampleStatus::Miss;
        Sample bsdf;
        if (status != tex::Ready ||
            !lambert(material, hit.normal, sample::draw(id, dimension, c.sampling),
                     sample::draw(id, dimension + 1, c.sampling), bsdf))
            return SampleStatus::Error;

        radiance[0] += throughput[0] * material.emission.x;
        radiance[1] += throughput[1] * material.emission.y;
        radiance[2] += throughput[2] * material.emission.z;
        if (bsdf.pdf <= 0) break;
        throughput[0] *= bsdf.f.x / bsdf.pdf;
        throughput[1] *= bsdf.f.y / bsdf.pdf;
        throughput[2] *= bsdf.f.z / bsdf.pdf;

        if (++depth == c.surfaceLimit) {
            // The last interaction looks along its sampled direction for the sky.
            if (backend.visible(hit.origin, bsdf.wi)) {
                radiance[0] += throughput[0] * c.sky.x;
                radiance[1] += throughput[1] * c.sky.y;
                radiance[2] += throughput[2] * c.sky.z;
            }
            break;
        }
        ray = {hit.origin, bsdf.wi, {}, {}, 0, 3.402823466e38f};
    }
    out.rgb[0] = radiance[0];
    out.rgb[1] = radiance[1];
    out.rgb[2] = radiance[2];
    out.alpha = primaryHit;
    return SampleStatus::Done;
}

// The unit of work (spec §7): one 8x8 tile of the image and a range of sample
// indices, not yet started. 16 bytes, so moving one across PCIe is cheap.
struct Chunk {
    U32 tile;   // tile index, row-major over the image's 8x8 tiles
    U32 first;  // first sample index
    U32 count;  // number of sample indices
    U32 cell;   // owning cell, for per-cell accounting
};
static_assert(sizeof(Chunk) == 16, "Chunks are 16 bytes");

constexpr U32 TileSize = 8, TilePixels = TileSize * TileSize;

// Pixel of the i-th position of a tile, or ~0u when it lies outside the image.
X2_HD inline U32 tilePixel(U32 tile, U32 position, U32 width, U32 height) {
    const U32 tilesX = (width + TileSize - 1) / TileSize;
    const U32 x = (tile % tilesX) * TileSize + position % TileSize;
    const U32 y = (tile / tilesX) * TileSize + position / TileSize;
    return x < width && y < height ? y * width + x : ~0u;
}

}  // namespace xpu2::interactive::async
