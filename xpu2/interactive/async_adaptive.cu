// The adaptive pass chain's bookkeeping on the GPU, as plain CUDA kernels on the
// GPU lane's stream between its OptiX renders (async_gpu.h): every pixel's error,
// the region trees, and the next pass's tile masks, in the order and with the
// arithmetic of the host's adaptive frame (async_adaptive.h, async_adaptive_core.h),
// so a pass needs no trip to the host and the host can queue a whole frame.
//
// Adapted from MoonRay rndr/adaptive, Apache-2.0, copyright 2023-2024 DreamWorks
// Animation LLC; see MOONRAY_LICENSE.txt.
#include "async_gpu_abi.h"
using namespace xpu2::interactive;
using namespace xpu2::interactive::async;
using namespace xpu2::interactive::async::adaptive;

// A chain step does nothing once the trees have converged, a pass came out
// empty, or a render parked a sample and the host must step in.
static __device__ bool halted(const ChainArgs& a) {
    const volatile DeviceState* s = a.state;
    return s->chainStop || s->chainStall;
}

// Every pixel's error from the device film.
extern "C" __global__ void chainErrors(ChainArgs a) {
    if (halted(a)) return;
    const U32 i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= a.width * a.height) return;
    a.errors[i] = pixelError(a.sums + size_t(i) * 4, a.odd + size_t(i) * 4, a.counts[i]);
}

// Rebuilds the region trees, one block a region: the summed-area table of its
// errors row by row and then column by column (the host's sums, in the host's
// order), then its nodes a level at a time, each decided as the host decides it.
extern "C" __global__ void chainTrees(ChainArgs a) {
    if (halted(a)) return;
    const U32 r = blockIdx.x;
    const IBox root = a.regions[r];
    const int w = root.x1 - root.x0, h = root.y1 - root.y0, w1 = w + 1;
    double* sat = a.sat + a.satOffset[r];
    Node* nodes = a.nodes + a.nodeOffset[r];
    __shared__ int notReady, unconverged, count;
    if (threadIdx.x == 0) {
        notReady = unconverged = 0;
        count = 1;
        nodes[0] = {{float(root.x0), float(root.y0), float(root.x1), float(root.y1)}, -1, 0};
        if (r == 0) ++a.state->treeUpdates;
    }
    __syncthreads();
    for (int x = threadIdx.x; x <= w; x += blockDim.x) sat[x] = 0;
    for (int y = threadIdx.x; y < h; y += blockDim.x) {
        const float* e = a.errors + size_t(root.y0 + y) * a.width + root.x0;
        double* out = sat + size_t(y + 1) * w1;
        double row = 0;
        out[0] = 0;
        for (int x = 0; x < w; ++x) {
            const float v = e[x];
            if (v < 0) notReady = 1;
            row += v;
            out[x + 1] = row;
        }
    }
    __syncthreads();
    // Not every pixel has both halves yet: the root alone, unconverged.
    if (notReady) {
        if (threadIdx.x == 0) a.regionDone[r] = 0;
        return;
    }
    for (int x = threadIdx.x + 1; x <= w; x += blockDim.x)
        for (int y = 1; y <= h; ++y) sat[size_t(y) * w1 + x] += sat[size_t(y - 1) * w1 + x];
    __syncthreads();

    const Sat s{sat, root.x0, root.y0, w1};
    const int capacity = int(a.nodeCapacity[r]);
    int begin = 0, end = 1;
    while (begin < end) {
        for (int i = begin + int(threadIdx.x); i < end; i += blockDim.x) {
            FBox left, right;
            const int fate = decide(s, root, nodes[i].bounds, a.target, left, right);
            if (fate == Converged) {
                nodes[i].complete = 1;
            } else if (fate == Split) {
                const int c = atomicAdd(&count, 2);
                if (c + 2 <= capacity) {
                    nodes[c] = {left, -1, 0};
                    nodes[c + 1] = {right, -1, 0};
                    nodes[i].children = c;
                } else {
                    unconverged = 1;  // beyond MoonRay's own bound: never
                }
            } else {
                unconverged = 1;
            }
        }
        __syncthreads();
        begin = end;
        end = count < capacity ? count : capacity;
        __syncthreads();
    }
    if (threadIdx.x == 0) a.regionDone[r] = unconverged ? 0 : 1;
}

// One thread a tile: its active pixels for the pass of the given size (all of
// them in the uniform stage), each pixel's first sample index, and its planned
// count. Once every region's tree has converged, the chain stops instead.
extern "C" __global__ void chainMasks(ChainArgs a, U32 uniform, U32 size) {
    if (halted(a)) return;
    if (!uniform) {
        bool converged = true;
        for (U32 r = 0; r < a.regionCount; ++r) converged &= a.regionDone[r] != 0;
        if (converged) {
            if (blockIdx.x == 0 && threadIdx.x == 0) a.state->chainStop = 1;
            return;
        }
    }
    const U32 tile = blockIdx.x * blockDim.x + threadIdx.x;
    if (tile >= a.tiles) return;
    U64L mask = a.inImage[tile];
    if (!uniform) {
        const int tx = int(tile % a.tilesX) * 8, ty = int(tile / a.tilesX) * 8;
        mask &= sampleArea(a.nodes + a.nodeOffset[a.layout.regionOf(tx, ty)], tx, ty);
    }
    a.tileMask[tile] = mask;
    for (U32 p = 0; p < TilePixels; ++p)
        if (mask >> p & 1) {
            const U32 pixel = tilePixel(tile, p, a.width, a.height);
            a.base[pixel] = a.planned[pixel];
            a.planned[pixel] += size;
        }
}

// One block: the pass's active tiles, in the work grid's cell order, for its
// render (async_gpu.cu, mode 3). A pass with no active pixel ends the frame, as
// nothing can change after it.
extern "C" __global__ void chainCompact(ChainArgs a, U32 pass, U32 size) {
    if (halted(a)) return;
    __shared__ U32 scan[1024];
    const U32 tid = threadIdx.x, threads = blockDim.x;
    const U32 per = (a.tiles + threads - 1) / threads, first = tid * per;
    const U32 last = first + per < a.tiles ? first + per : a.tiles;
    U32 mine = 0;
    U64L samples = 0;
    for (U32 k = first; k < last; ++k) {
        const U64L m = a.tileMask[a.tileOrder[k]];
        if (m) {
            ++mine;
            samples += U64L(__popcll(m));
        }
    }
    scan[tid] = mine;
    __syncthreads();
    for (U32 offset = 1; offset < threads; offset <<= 1) {
        const U32 v = tid >= offset ? scan[tid - offset] : 0;
        __syncthreads();
        scan[tid] += v;
        __syncthreads();
    }
    U32 at = scan[tid] - mine;
    for (U32 k = first; k < last; ++k) {
        const U32 tile = a.tileOrder[k];
        const U64L m = a.tileMask[tile];
        if (m) {
            a.activeTiles[at] = tile;
            a.activeMasks[at] = m;
            ++at;
        }
    }
    if (samples) atomicAdd(&a.state->chainSamples, samples * size);
    if (tid == threads - 1) {
        const U32 total = scan[tid];
        ++a.state->chainPasses;
        if (total) {
            a.state->activeTiles = total;
            a.state->chainClaimed = 0;
            a.state->chainPass = pass;
        } else {
            a.state->chainStop = 1;
        }
    }
}
