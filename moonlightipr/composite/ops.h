#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar.
// The compositor's nodes, written once: compiled by NVRTC for the graphics card and by the C++ compiler for the
// processor, so that the two give the same picture. Every node is worked out a pixel at a time from the pictures it
// takes, so either can do any part of the picture in any order.
//
// The arithmetic follows what the image tool the compositor used before (oiiotool) does, measured with
// tools/measure_oiiotool_ops.py: a blur is a Gaussian of a standard deviation a quarter of its width, sampled at the
// pixel centres, cut off at the kernel's edge and made to add up to one; outside the picture the edge pixels go on; the
// Laplacian is the 4-neighbour one; saturation is about Rec.709 luminance; a fill runs from the first pixel to the last.
// Pictures are three floats a pixel, rows from the top.

#if defined(__CUDACC_RTC__) || defined(__CUDACC__)
#define CMP __device__ __host__ inline
#else
#define CMP inline
#include <cmath>
#endif

namespace composite {

// The kinds of step. A node of the graph is one step or, for the blurs, several.
enum Kind : int {
    COPY = 0,           // a: the picture as it is
    FIX = 1,            // a: what is not a finite number made black (as a buffer is read)
    MERGE = 2,          // a beneath, b laid over, m the mask (or none): a + (merged - a) * mix * mask; i0 the mode
    GRADE = 3,          // a: times gain (f0..f2); then, with f3 != 1, under black black and to the power 1/f3; f4 saturation
    LEVELS = 4,         // a: (a - f0) * f1 (one over the span), under black black, to the power f2, times f3, plus f4
    CONTRAST = 5,       // a: (a - f1) * f0 + f1
    INVERT = 6,         // a: 1 - a
    CLAMP = 7,          // a: at least f0, at most f1
    TONEMAP = 8,        // a: times f0, under black black, then x / (x + 1)
    MATH = 9,           // a: i0 the operation with f0
    BLUR_X = 10,        // a: a row's blur with the kernel of i0 taps (weights in the kernel table at i1)
    BLUR_Y = 11,        // a: a column's
    SHARPEN = 12,       // a the picture, b its blur: a + f0 * (a - b)
    MEDIAN = 13,        // a: the middle value in a square i0 pixels across, channel by channel
    DILATE = 14,        // a: the most in a square i0 across
    ERODE = 15,         // a: the least
    EDGES = 16,         // a: |Laplacian| * f0
    GRAIN = 17,         // a: plus one Gaussian number per pixel, of standard deviation f0, from seed i0, the same in every channel
    VIGNETTE = 18,      // a: times (amount * hump^falloff + 1 - amount), hump 16 u(1-u) v(1-v); f0 amount, f1 falloff
    FLIP = 19,          // a: i0 1 left to right, 2 top to bottom, 3 both
    LUMA_MATTE = 20,    // a: Rec.709 brightness, (y - f0) * f1 (one over the span), kept between 0 and 1, the same in every channel; i0 1 to invert
    CHANNEL = 21,       // a: i0 0 brightness, 1 red, 2 green, 3 blue, as grey
    CONSTANT = 22,      // nothing: (f0, f1, f2)
    RAMP = 23,          // nothing: from (f0..f2) to (f3..f5), i0 0 left to right, 1 top to bottom
    GLOW_ADD = 24,      // a the picture, b the blurred bright part: a + b * f0
    BRIGHT = 25,        // a: under black black after taking f0 away (a glow's bright part)
    BLACK = 26          // nothing: black
};

// Merge modes, in the compositor's order.
enum Mode : int { NORMAL = 0, ADD, MULTIPLY, SCREEN, LIGHTEN, DARKEN, DIFFERENCE };
// Math operations, in the compositor's order.
enum Operation : int { OP_ADD = 0, OP_SUBTRACT, OP_MULTIPLY, OP_DIVIDE, OP_POWER, OP_LEAST, OP_MOST };

struct Step {
    int kind;
    int a, b, m, out;       // pictures by number; -1 for none
    int i0, i1;
    float f[6];
};

struct Pictures {
    float* const* slots;    // the pictures, by number
    const float* kernels;   // the blur kernels, one after another
    int width, height;
};

CMP int clampi(int v, int low, int high) { return v < low ? low : v > high ? high : v; }
CMP float maxf(float a, float b) { return a > b ? a : b; }
CMP float minf(float a, float b) { return a < b ? a : b; }
CMP const float* at(const Pictures& p, int slot, int x, int y) {
    // Outside the picture the edge goes on.
    return p.slots[slot] + (size_t(clampi(y, 0, p.height - 1)) * p.width + clampi(x, 0, p.width - 1)) * 3;
}
CMP float luma(const float* c) { return 0.2126f * c[0] + 0.7152f * c[1] + 0.0722f * c[2]; }
// A number that is neither infinite nor not a number, worked out the same way on either side.
CMP bool finite(float v) { return v == v && fabsf(v) <= 3.402823466e+38f; }

// A Gaussian number from a pixel and a seed: two 32-bit hashes of them, by Box and Muller.
CMP unsigned hashed(unsigned v) {
    v ^= v >> 16; v *= 0x7feb352dU; v ^= v >> 15; v *= 0x846ca68bU; v ^= v >> 16;
    return v;
}
CMP float gaussianNoise(int x, int y, int seed) {
    const unsigned k = hashed(unsigned(x) * 73856093U ^ hashed(unsigned(y) * 19349663U ^ hashed(unsigned(seed) * 83492791U)));
    const float u1 = (float((k >> 8) & 0xFFFFFFU) + 1.0f) / 16777217.0f;
    const float u2 = float(hashed(k) >> 8) / 16777216.0f;
    return sqrtf(-2.0f * logf(u1)) * cosf(6.28318530718f * u2);
}

// One output pixel of one step: its three values.
CMP void evaluate(const Step& s, const Pictures& p, int x, int y, float* out) {
    const float* a = s.a >= 0 ? at(p, s.a, x, y) : nullptr;
    switch (s.kind) {
    case COPY:
        for (int c = 0; c < 3; ++c) out[c] = a[c];
        return;
    case FIX:
        for (int c = 0; c < 3; ++c) out[c] = finite(a[c]) ? a[c] : 0.0f;
        return;
    case MERGE: {
        const float* b = at(p, s.b, x, y);
        const float mask = s.m >= 0 ? at(p, s.m, x, y)[0] : 1.0f;
        for (int c = 0; c < 3; ++c) {
            const float under = a[c], over = b[c];
            float merged = over;
            switch (s.i0) {
            case ADD: merged = under + over; break;
            case MULTIPLY: merged = under * over; break;
            case SCREEN: merged = 1.0f - (1.0f - under) * (1.0f - over); break;
            case LIGHTEN: merged = maxf(under, over); break;
            case DARKEN: merged = minf(under, over); break;
            case DIFFERENCE: merged = fabsf(under - over); break;
            default: break;
            }
            out[c] = (merged - under) * mask * s.f[0] + under;
        }
        return;
    }
    case GRADE: {
        float v[3];
        for (int c = 0; c < 3; ++c) {
            v[c] = a[c] * s.f[c];
            if (s.f[3] != 1.0f) v[c] = powf(maxf(v[c], 0.0f), 1.0f / s.f[3]);
        }
        if (s.f[4] != 1.0f) {
            const float y0 = luma(v);
            for (int c = 0; c < 3; ++c) v[c] = y0 + s.f[4] * (v[c] - y0);
        }
        for (int c = 0; c < 3; ++c) out[c] = v[c];
        return;
    }
    case LEVELS:
        for (int c = 0; c < 3; ++c) out[c] = powf(maxf((a[c] - s.f[0]) * s.f[1], 0.0f), s.f[2]) * s.f[3] + s.f[4];
        return;
    case CONTRAST:
        for (int c = 0; c < 3; ++c) out[c] = (a[c] - s.f[1]) * s.f[0] + s.f[1];
        return;
    case INVERT:
        for (int c = 0; c < 3; ++c) out[c] = 1.0f - a[c];
        return;
    case CLAMP:
        for (int c = 0; c < 3; ++c) out[c] = minf(maxf(a[c], s.f[0]), s.f[1]);
        return;
    case TONEMAP:
        for (int c = 0; c < 3; ++c) { const float v = maxf(a[c] * s.f[0], 0.0f); out[c] = v / (v + 1.0f); }
        return;
    case MATH:
        for (int c = 0; c < 3; ++c) {
            const float v = a[c];
            switch (s.i0) {
            case OP_ADD: out[c] = v + s.f[0]; break;
            case OP_SUBTRACT: out[c] = v - s.f[0]; break;
            case OP_MULTIPLY: out[c] = v * s.f[0]; break;
            case OP_DIVIDE: out[c] = v * s.f[0]; break;     // f0 is already one over the number, or 0
            case OP_POWER: out[c] = powf(maxf(v, 0.0f), s.f[0]); break;
            case OP_LEAST: out[c] = minf(v, s.f[0]); break;
            default: out[c] = maxf(v, s.f[0]); break;
            }
        }
        return;
    case BLUR_X:
    case BLUR_Y: {
        const float* w = p.kernels + s.i1;
        const int half = s.i0 / 2;
        float sum[3] = {0.0f, 0.0f, 0.0f};
        for (int k = -half; k <= half; ++k) {
            const float* v = s.kind == BLUR_X ? at(p, s.a, x + k, y) : at(p, s.a, x, y + k);
            for (int c = 0; c < 3; ++c) sum[c] += w[k + half] * v[c];
        }
        for (int c = 0; c < 3; ++c) out[c] = sum[c];
        return;
    }
    case SHARPEN: {
        const float* b = at(p, s.b, x, y);
        for (int c = 0; c < 3; ++c) out[c] = a[c] + s.f[0] * (a[c] - b[c]);
        return;
    }
    case MEDIAN: {
        // Only the pixels inside the picture, and of an even number of them the upper middle one, as the image tool
        // takes them (tools/measure_oiiotool_ops.py, and every edge pixel of a render compared).
        const int half = s.i0 / 2;
        float held[169];
        for (int c = 0; c < 3; ++c) {
            int n = 0;
            for (int j = -half; j <= half; ++j)
                for (int i = -half; i <= half; ++i)
                    if (x + i >= 0 && x + i < p.width && y + j >= 0 && y + j < p.height) held[n++] = at(p, s.a, x + i, y + j)[c];
            const int count = n, middle = count / 2;
            for (int i = 0; i <= middle; ++i) {
                int least = i;
                for (int k = i + 1; k < count; ++k) if (held[k] < held[least]) least = k;
                const float t = held[i]; held[i] = held[least]; held[least] = t;
            }
            out[c] = held[middle];
        }
        return;
    }
    case DILATE:
    case ERODE: {
        const int half = s.i0 / 2;
        for (int c = 0; c < 3; ++c) {
            float v = a[c];
            for (int j = -half; j <= half; ++j)
                for (int i = -half; i <= half; ++i) {
                    const float u = at(p, s.a, x + i, y + j)[c];
                    v = s.kind == DILATE ? maxf(v, u) : minf(v, u);
                }
            out[c] = v;
        }
        return;
    }
    case EDGES: {
        const float* l = at(p, s.a, x - 1, y); const float* r = at(p, s.a, x + 1, y);
        const float* u = at(p, s.a, x, y - 1); const float* d = at(p, s.a, x, y + 1);
        for (int c = 0; c < 3; ++c) out[c] = fabsf(l[c] + r[c] + u[c] + d[c] - 4.0f * a[c]) * s.f[0];
        return;
    }
    case GRAIN: {
        const float n = gaussianNoise(x, y, s.i0) * s.f[0];
        for (int c = 0; c < 3; ++c) out[c] = a[c] + n;
        return;
    }
    case VIGNETTE: {
        const float u = p.width > 1 ? float(x) / float(p.width - 1) : 0.0f;
        const float v = p.height > 1 ? float(y) / float(p.height - 1) : 0.0f;
        const float hump = maxf((4.0f * u * (1.0f - u)) * (4.0f * v * (1.0f - v)), 0.0f);
        const float scale = powf(hump, s.f[1]) * s.f[0] + (1.0f - s.f[0]);
        for (int c = 0; c < 3; ++c) out[c] = a[c] * scale;
        return;
    }
    case FLIP: {
        const int fx = (s.i0 & 1) ? p.width - 1 - x : x, fy = (s.i0 & 2) ? p.height - 1 - y : y;
        const float* v = at(p, s.a, fx, fy);
        for (int c = 0; c < 3; ++c) out[c] = v[c];
        return;
    }
    case LUMA_MATTE: {
        float v = minf(maxf((luma(a) - s.f[0]) * s.f[1], 0.0f), 1.0f);
        if (s.i0) v = 1.0f - v;
        out[0] = out[1] = out[2] = v;
        return;
    }
    case CHANNEL: {
        const float v = s.i0 == 0 ? luma(a) : a[s.i0 - 1];
        out[0] = out[1] = out[2] = v;
        return;
    }
    case CONSTANT:
        for (int c = 0; c < 3; ++c) out[c] = s.f[c];
        return;
    case RAMP: {
        const float t = s.i0 == 0 ? (p.width > 1 ? float(x) / float(p.width - 1) : 0.0f)
                                  : (p.height > 1 ? float(y) / float(p.height - 1) : 0.0f);
        for (int c = 0; c < 3; ++c) out[c] = s.f[c] + (s.f[c + 3] - s.f[c]) * t;
        return;
    }
    case GLOW_ADD: {
        const float* b = at(p, s.b, x, y);
        for (int c = 0; c < 3; ++c) out[c] = a[c] + b[c] * s.f[0];
        return;
    }
    case BRIGHT:
        for (int c = 0; c < 3; ++c) out[c] = maxf(a[c] - s.f[0], 0.0f);
        return;
    default:
        out[0] = out[1] = out[2] = 0.0f;
        return;
    }
}

}  // namespace composite
