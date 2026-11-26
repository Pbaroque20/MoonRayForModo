#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// MoonRay's glitter, the host's part: the tables a material's flakes are found and turned by, and the numbers that do
// not change over its surface (DeviceGlitter), as MoonRay's Glitter object makes them. Written to follow OpenMoonRay
// (Apache License 2.0): scene_rdl2 util/Random.h, lib/common/noise Noise.cc and Worley.cc, moonshine lib/material/glitter
// Glitter.cc and Glitter.ispc; the average colour tables are MoonRay's own (glitter_tables.h).
#include "device/shared.h"
#include "glitter_tables.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <numeric>
#include <vector>

namespace moonlightipr {
namespace glitter {

// MoonRay's random numbers (scene_rdl2::util::Random, a PCG generator): a UniformRandomBitGenerator, so that std::shuffle
// deals the noise's permutation as MoonRay's does (the same standard library, the toolchain's).
class Random {
public:
    using result_type = std::uint32_t;
    static constexpr result_type min() { return 0u; }
    static constexpr result_type max() { return 0xffffffffu; }
    explicit Random(std::uint64_t state, std::uint64_t stream = 1u) {
        mState = 0u;
        mStream = (stream << 1u) | 1u;
        next();
        mState += state;
        next();
    }
    result_type operator()() { return next(); }
    float nextFloat() {
        const std::uint32_t bits = (127u << 23u) | (next() >> 9u);
        float f;
        std::memcpy(&f, &bits, sizeof(f));
        return f - 1.0f;
    }

private:
    std::uint32_t next() {
        std::uint64_t input = mState = mState * 0x5851f42d4c957f2dULL + mStream;
        const std::uint32_t rot = std::uint32_t(input >> 59u) & 31u;
        input ^= input >> 18u;
        const std::uint32_t result = std::uint32_t(input >> 27u);
        return (result >> rot) | (result << ((32u - rot) & 31u));
    }
    std::uint64_t mState, mStream;
};

// A material's tables (DeviceGlitter::tables): Noise's permutation and Worley's static feature points, as the first
// noise with static tables deals them from MoonRay's shared generator (glitter is their only user); the flakes'
// normals for its randomness (getGgxNormal); the colour random table (its seed + 100); Poisson's point-count bounds.
inline std::vector<float> tables(int seed, float randomness) {
    const int n = int(GLITTER_TABLE_SIZE);
    Random noise(0xbeadceef);
    std::vector<int> permutation(n);
    std::iota(permutation.begin(), permutation.end(), 0);
    std::shuffle(permutation.begin(), permutation.end(), noise);
    std::vector<float> t(GLITTER_TABLE_FLOATS, 0.0f);
    std::memcpy(t.data() + GLITTER_PERM, permutation.data(), sizeof(int) * n);
    std::vector<float> rx(n), ry(n);
    for (int i = 0; i < n; ++i) {
        t[GLITTER_POINTS_X + i] = noise.nextFloat();
        t[GLITTER_POINTS_Y + i] = noise.nextFloat();
        t[GLITTER_POINTS_Z + i] = noise.nextFloat();
        rx[i] = noise.nextFloat();
        ry[i] = noise.nextFloat();
    }
    const float r = randomness * randomness;
    for (int i = 0; i < n; ++i) {
        const float theta = std::atan(r * std::sqrt(rx[i]) / std::sqrt(1.0f - rx[i]));
        const float phi = 6.28318530717958647692f * ry[i];
        // Unit already; the kernel takes them as they are (MoonRay normalizes them again as it reads them).
        float x = std::cos(phi) * std::sin(theta), y = std::sin(phi) * std::sin(theta), z = std::cos(theta);
        const float length = std::sqrt(x * x + y * y + z * z);
        t[GLITTER_NORMALS_X + i] = x / length;
        t[GLITTER_NORMALS_Y + i] = y / length;
        t[GLITTER_NORMALS_Z + i] = z / length;
    }
    Random colours(std::uint64_t(std::int64_t(seed) + 100));
    for (unsigned i = 0; i < GLITTER_RANDOM_SIZE; ++i) t[GLITTER_RANDOM + i] = colours.nextFloat();
    // Worley's Poisson bounds: for m points, from the sum of the chances below m to that plus the chance of m.
    float* low = t.data() + GLITTER_PROB_LOW;
    float* high = t.data() + GLITTER_PROB_HIGH;
    int factorial = 1;
    for (int m = 1; m <= 9; ++m) {
        factorial *= m;
        const float chance = 1.0f / (std::pow(3.0f, float(-m)) * std::exp(3.0f) * float(factorial));
        low[m] = m == 1 ? 0.0f : high[m - 1];
        high[m] = low[m] + chance;
    }
    high[9] = std::numeric_limits<float>::max();
    low[0] = high[0] = 0.0f;
    return t;
}

// scene_rdl2's rgbToHsv and hsvToRgb, and MoonRay's INTERPOLATION_lerpHSV (whose value is A's, as MoonRay's is).
inline bool isZero(float x) { return std::fabs(x) <= 1e-6f; }
inline void hsv(const float c[3], float out[3]) {
    const int top = c[2] > std::max(c[0], c[1]) ? 2 : c[1] > c[0] ? 1 : 0;
    const float least = std::min(c[0], std::min(c[1], c[2])), most = std::max(c[0], std::max(c[1], c[2])), chroma = most - least;
    float h = 0.0f, s = 0.0f;
    if (!isZero(most)) {
        if (!isZero(chroma)) {
            h = top == 0 ? (c[1] - c[2]) / chroma : top == 1 ? 2.0f + (c[2] - c[0]) / chroma : 4.0f + (c[0] - c[1]) / chroma;
            h = std::fmod(h * 60.0f, 360.0f);
            if (h < 0.0f) h += 360.0f;
            h /= 360.0f;
        }
        s = chroma / most;
    }
    out[0] = h;
    out[1] = s;
    out[2] = most;
}
inline void rgb(const float c[3], float out[3]) {
    float h = c[0];
    const float s = c[1], v = c[2];
    if (isZero(s)) {
        out[0] = out[1] = out[2] = v;
        return;
    }
    h = std::fmod(h, 1.0f);
    if (h < 0.0f) h += 1.0f;
    h *= 360.0f;
    if (std::fabs(h - 360.0f) <= std::max(std::fabs(h), 1.0f) * 1e-6f) h = 0.0f;
    h /= 60.0f;
    const int sector = int(h);
    const float f = h - float(sector), p = v * (1.0f - s), q = v * (1.0f - s * f), t = v * (1.0f - s * (1.0f - f));
    const float table[6][3] = {{v, t, p}, {q, v, p}, {p, v, t}, {p, q, v}, {t, p, v}, {v, p, q}};
    for (int i = 0; i < 3; ++i) out[i] = sector >= 0 && sector < 6 ? table[sector][i] : p;
}
inline void lerpHsv(float t, const float a[3], const float b[3], float out[3]) {
    if (t <= 0.0f) { std::copy(a, a + 3, out); return; }
    if (t >= 1.0f) { std::copy(b, b + 3, out); return; }
    float aHue = a[0], bHue = b[0], dist = bHue - aHue, hue;
    if (aHue > bHue) {
        bHue = a[0];
        aHue = b[0];
        dist = -dist;
        t = 1.0f - t;
    }
    if (dist > 0.5f) {
        aHue += 1.0f;
        hue = std::fmod(aHue + t * (bHue - aHue), 1.0f);
    } else {
        hue = aHue + t * dist;
    }
    out[0] = hue;
    out[1] = a[1] + t * (b[1] - a[1]);
    out[2] = a[2] + t * (b[2] - b[2]);
}

// computeCoverageFactor: the share of a footprint the flakes cover on average, fitted over their size.
inline float coverage(float flakeSize) {
    flakeSize = std::min(flakeSize, 1.1277f);
    const float squared = flakeSize * flakeSize;
    const float result = flakeSize < 0.4f ? -0.0382308f * flakeSize + 1.230008f * squared
                                          : 0.030076f - 0.6612578f * flakeSize + 3.313868f * squared - 1.7856762f * flakeSize * squared;
    return std::clamp(result, 0.0f, 1.0f);
}

// The flakes' average colour (computeAverageBaseColor, then computeAverageFlakeColor with the coverage).
inline void average(const DeviceGlitter& g, float out[3]) {
    float base[3];
    if (isZero(g.frequency[0])) std::copy(g.color + 3, g.color + 6, base);
    else if (isZero(g.frequency[1])) std::copy(g.color, g.color + 3, base);
    else {
        const float a = g.size[0] * g.size[0], b = g.size[1] * g.size[1];
        const float first = a / (a + b) * g.frequency[0], second = b / (a + b) * g.frequency[1];
        float ha[3], hb[3], mixed[3];
        hsv(g.color, ha);
        hsv(g.color + 3, hb);
        lerpHsv(second / (first + second), ha, hb, mixed);
        rgb(mixed, base);
    }
    if (isZero(g.variation[0]) && isZero(g.variation[1]) && isZero(g.variation[2])) {
        std::copy(base, base + 3, out);
        return;
    }
    float h[3];
    hsv(base, h);
    float hueT = std::fmod(h[0], 0.3333f) / 0.3333f;
    hueT = 2.0f * (hueT > 0.5f ? 1.0f - hueT : hueT);
    const float hueIndex = hueT * 15.0f, varIndex = g.variation[0] * 99.0f;
    const int hueLo = int(hueIndex), hueHi = int(std::min(15.0f, std::floor(hueIndex) + 1.0f));
    const int varLo = int(varIndex), varHi = int(std::min(99.0f, std::floor(varIndex) + 1.0f));
    const float hueF = hueIndex - float(hueLo), varF = varIndex - float(varLo);
    auto at = [](const float (&table)[16][100], int hue, int var) { return table[std::clamp(hue, 0, 15)][std::clamp(var, 0, 99)]; };
    auto lerp = [](float a, float b, float t) { return a + (b - a) * t; };
    const auto& S = GLITTER_hueVariationSaturationTable;
    const auto& V = GLITTER_hueVariationValueTable;
    const float saturation = h[1] * lerp(lerp(at(S, hueLo, varLo), at(S, hueLo, varHi), varF), lerp(at(S, hueHi, varLo), at(S, hueHi, varHi), varF), hueF);
    float value = h[2] * lerp(lerp(at(V, hueLo, varLo), at(V, hueLo, varHi), varF), lerp(at(V, hueHi, varLo), at(V, hueHi, varHi), varF), hueF);
    value = lerp(h[2] * g.coverage, value, h[1]);
    const float mixed[3] = {h[0], saturation, value};
    rgb(mixed, out);
}

}  // namespace glitter
}  // namespace moonlightipr
