// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar.
// The compositor on the graphics card: one thread a pixel, each working out its pixel of one step with the same
// code the processor runs (ops.h).
#include "ops.h"

extern "C" __global__ void compositeStep(composite::Step step, composite::Pictures pictures) {
    const int x = int(blockIdx.x * blockDim.x + threadIdx.x), y = int(blockIdx.y * blockDim.y + threadIdx.y);
    if (x >= pictures.width || y >= pictures.height) return;
    float value[3];
    composite::evaluate(step, pictures, x, y, value);
    float* out = pictures.slots[step.out] + (size_t(y) * pictures.width + x) * 3;
    out[0] = value[0]; out[1] = value[1]; out[2] = value[2];
}
