// Modo's procedural textures as patterns in three dimensions, written once for MoonRay's C++ and ISPC map code and
// for MoonLightIPR's CUDA kernel, so that all three give the same numbers. Each pattern takes a point in the texture
// locator's space and gives how much of the first colour there is, 0 to 1, before the layer's bias and gain.
//
// They are after Modo's patterns and their settings, not Modo's own code: a texture the plugin's tests compare with
// Modo's renders is tuned here. Plain C that ISPC also reads: no references, no structs, no arrays; ints and floats.

#ifndef MODO_PATTERNS_H
#define MODO_PATTERNS_H

#if defined(ISPC)
#define MP_FUNC static inline
#define MP_FLOOR(x) floor(x)
#define MP_SQRT(x) sqrt(x)
#define MP_ABS(x) abs(x)
#define MP_COS(x) cos(x)
#define MP_POW(x, y) pow(x, y)
#define MP_MIN(x, y) min(x, y)
#define MP_MAX(x, y) max(x, y)
#elif defined(__CUDACC__)
#define MP_FUNC static __device__ __forceinline__
#define MP_FLOOR(x) floorf(x)
#define MP_SQRT(x) sqrtf(x)
#define MP_ABS(x) fabsf(x)
#define MP_COS(x) cosf(x)
#define MP_POW(x, y) powf(x, y)
#define MP_MIN(x, y) fminf(x, y)
#define MP_MAX(x, y) fmaxf(x, y)
#else
#include <cmath>
#define MP_FUNC static inline
#define MP_FLOOR(x) std::floor(x)
#define MP_SQRT(x) std::sqrt(x)
#define MP_ABS(x) std::fabs(x)
#define MP_COS(x) std::cos(x)
#define MP_POW(x, y) std::pow(x, y)
#define MP_MIN(x, y) std::fmin(x, y)
#define MP_MAX(x, y) std::fmax(x, y)
#endif

// The patterns, and the choices of those that have them, as Modo numbers its own.
#define MP_NOISE 0
#define MP_CELLULAR 1
#define MP_CHECKER 2
#define MP_GRID 3
#define MP_DOTS 4
#define MP_WOOD 5
#define MP_WEAVE 6
#define MP_RIPPLES 7
#define MP_PATTERNS 8

#define MP_PI 3.14159265358979f

MP_FUNC float mp_clamp01(float x) { return MP_MIN(1.0f, MP_MAX(0.0f, x)); }
MP_FUNC float mp_fract(float x) { return x - MP_FLOOR(x); }
MP_FUNC float mp_lerp(float a, float b, float t) { return a + (b - a) * t; }
MP_FUNC float mp_smooth(float t) { t = mp_clamp01(t); return t * t * (3.0f - 2.0f * t); }

// 0 below an edge and 1 above it, easing between over soft either side.
MP_FUNC float mp_step(float value, float edge, float soft) {
    if (soft <= 1e-6f) return value >= edge ? 1.0f : 0.0f;
    return mp_smooth((value - edge + soft) / (2.0f * soft));
}

// A whole number from whole numbers, always the same for the same ones; and from it a number from 0 up to 1.
MP_FUNC unsigned int mp_hash(int x, int y, int z, int seed) {
    unsigned int h = ((unsigned int)x * 73856093u) ^ ((unsigned int)y * 19349663u) ^ ((unsigned int)z * 83492791u)
                     ^ ((unsigned int)seed * 2654435761u);
    h = h ^ (h >> 16);
    h = h * 0x7feb352du;
    h = h ^ (h >> 15);
    h = h * 0x846ca68bu;
    h = h ^ (h >> 16);
    return h;
}
MP_FUNC float mp_random(int x, int y, int z, int seed) { return (float)(mp_hash(x, y, z, seed) & 0xffffffu) / 16777216.0f; }

// Smooth gradient noise, about -1 to 1, as Perlin's improved noise.
MP_FUNC float mp_fade(float t) { return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f); }
MP_FUNC float mp_gradient(unsigned int h, float x, float y, float z) {
    int k = (int)(h & 15u);
    float u = k < 8 ? x : y;
    float v = k < 4 ? y : ((k == 12 || k == 14) ? x : z);
    return (((k & 1) != 0) ? -u : u) + (((k & 2) != 0) ? -v : v);
}
MP_FUNC float mp_noise(float x, float y, float z, int seed) {
    float fx = MP_FLOOR(x), fy = MP_FLOOR(y), fz = MP_FLOOR(z);
    int ix = (int)fx, iy = (int)fy, iz = (int)fz;
    x = x - fx; y = y - fy; z = z - fz;
    float u = mp_fade(x), v = mp_fade(y), w = mp_fade(z);
    float a = mp_lerp(mp_gradient(mp_hash(ix, iy, iz, seed), x, y, z), mp_gradient(mp_hash(ix + 1, iy, iz, seed), x - 1.0f, y, z), u);
    float b = mp_lerp(mp_gradient(mp_hash(ix, iy + 1, iz, seed), x, y - 1.0f, z), mp_gradient(mp_hash(ix + 1, iy + 1, iz, seed), x - 1.0f, y - 1.0f, z), u);
    float c = mp_lerp(mp_gradient(mp_hash(ix, iy, iz + 1, seed), x, y, z - 1.0f), mp_gradient(mp_hash(ix + 1, iy, iz + 1, seed), x - 1.0f, y, z - 1.0f), u);
    float d = mp_lerp(mp_gradient(mp_hash(ix, iy + 1, iz + 1, seed), x, y - 1.0f, z - 1.0f),
                      mp_gradient(mp_hash(ix + 1, iy + 1, iz + 1, seed), x - 1.0f, y - 1.0f, z - 1.0f), u);
    return mp_lerp(mp_lerp(a, b, v), mp_lerp(c, d, v), w);
}

// Noise over several frequencies: each ratio times finer and ampRatio times weaker. turbulent adds their sizes.
MP_FUNC float mp_fractal(float x, float y, float z, int octaves, float ratio, float ampRatio, int turbulent, int seed) {
    float sum = 0.0f, amplitude = 1.0f, weight = 0.0f, frequency = 1.0f;
    for (int i = 0; i < octaves; i++) {
        float n = mp_noise(x * frequency, y * frequency, z * frequency, seed + i * 7);
        sum = sum + amplitude * (turbulent != 0 ? MP_ABS(n) : n);
        weight = weight + amplitude;
        amplitude = amplitude * ampRatio;
        frequency = frequency * ratio;
    }
    return weight > 0.0f ? sum / weight : 0.0f;
}

// Modo's Noise: simple (type 0), fractal (1) or turbulence (2).
MP_FUNC float mp_noise_pattern(int type, float x, float y, float z, float freqs, float freqRatio, float ampRatio) {
    int octaves = type == 0 ? 1 : (int)MP_MAX(1.0f, MP_MIN(16.0f, freqs));
    float ratio = MP_MAX(1.0f, freqRatio), weaker = MP_MAX(0.0f, ampRatio);
    if (type == 2) return mp_clamp01(1.6f * mp_fractal(x, y, z, octaves, ratio, weaker, 1, 11));
    return mp_clamp01(0.5f + 0.5f * 1.4f * mp_fractal(x, y, z, octaves, ratio, weaker, 0, 11));
}

// One frequency of Modo's Cellular, a cell a unit across: a point in each cell, round (type 0) within the cell's
// width of its point, angular (1) further than the gap from the cell's edge, each cell darkened by chance by variation.
MP_FUNC float mp_cells(float x, float y, float z, int round, float width, float soft, float variation, int seed) {
    float cx = MP_FLOOR(x), cy = MP_FLOOR(y), cz = MP_FLOOR(z);
    float first = 9.0f, second = 9.0f;
    int nx = 0, ny = 0, nz = 0;
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                int a = (int)cx + i, b = (int)cy + j, c = (int)cz + k;
                float px = (float)a + 0.15f + 0.7f * mp_random(a, b, c, seed);
                float py = (float)b + 0.15f + 0.7f * mp_random(a, b, c, seed + 1);
                float pz = (float)c + 0.15f + 0.7f * mp_random(a, b, c, seed + 2);
                float d = MP_SQRT((x - px) * (x - px) + (y - py) * (y - py) + (z - pz) * (z - pz));
                if (d < first) { second = first; first = d; nx = a; ny = b; nz = c; }
                else if (d < second) second = d;
            }
        }
    }
    float inside = round != 0 ? mp_step(0.5f * width - first, 0.0f, soft) : mp_step(0.5f * (second - first), 0.5f * (1.0f - width), soft);
    return inside * (1.0f - mp_clamp01(variation) * mp_random(nx, ny, nz, seed + 13));
}
MP_FUNC float mp_cellular(int type, float x, float y, float z, float cellWidth, float transWidth, float freqs, float freqRatio,
                          float ampRatio, float variation) {
    float width = mp_clamp01(cellWidth), soft = 0.25f * MP_MAX(0.0f, transWidth);
    float total = 0.0f, weight = 0.0f, amplitude = 1.0f, frequency = 1.0f;
    int octaves = (int)MP_MAX(1.0f, MP_MIN(8.0f, freqs));
    for (int i = 0; i < octaves; i++) {
        total = total + amplitude * mp_cells(x * frequency, y * frequency, z * frequency, type == 0 ? 1 : 0, width, soft, variation, 7 * i);
        weight = weight + amplitude;
        amplitude = amplitude * MP_MAX(0.0f, ampRatio);
        frequency = frequency * MP_MAX(1.0f, freqRatio);
    }
    return weight > 0.0f ? total / weight : 0.0f;
}

// Modo's Checker, a square a unit across: squares across the locator's X and Y (type 0) or cubes (1); its colours
// meet over transWidth of a square.
MP_FUNC float mp_checker(int type, float x, float y, float z, float transWidth) {
    float fx = mp_fract(x), fy = mp_fract(y), fz = mp_fract(z);
    int parity = ((int)MP_FLOOR(x) + (int)MP_FLOOR(y) + (type == 1 ? (int)MP_FLOOR(z) : 0)) & 1;
    float edge = MP_MIN(MP_MIN(fx, 1.0f - fx), MP_MIN(fy, 1.0f - fy));
    if (type == 1) edge = MP_MIN(edge, MP_MIN(fz, 1.0f - fz));
    float soft = 0.5f * MP_MAX(0.0f, transWidth);
    float sure = soft > 1e-6f ? mp_smooth(edge / soft) : 1.0f;
    return 0.5f + (parity != 0 ? 0.5f : -0.5f) * sure;
}

// How far a point is from the lines of Modo's Grid (line 0, triangle 1, square 2, hexagon 3, cube 4), in cells.
MP_FUNC float mp_grid_distance(int type, float x, float y, float z) {
    float fx = mp_fract(x), fy = mp_fract(y), fz = mp_fract(z);
    if (type == 0) return MP_MIN(fx, 1.0f - fx);
    if (type == 2) return MP_MIN(MP_MIN(fx, 1.0f - fx), MP_MIN(fy, 1.0f - fy));
    if (type == 4) return MP_MIN(MP_MIN(MP_MIN(fx, 1.0f - fx), MP_MIN(fy, 1.0f - fy)), MP_MIN(fz, 1.0f - fz));
    // Rows on a triangular lattice, each half a cell over from the last.
    float ry = y * 2.0f;
    float row = MP_FLOOR(ry);
    float ty = ry - row, tx = mp_fract(x - 0.5f * mp_fract(row * 0.5f) * 2.0f);
    if (type == 1)
        return MP_MIN(MP_MIN(ty, 1.0f - ty) * 0.5f, MP_MIN(MP_ABS(mp_fract(tx + ty * 0.5f) - 0.5f), MP_ABS(mp_fract(tx - ty * 0.5f) - 0.5f)));
    float dx = MP_ABS(tx - 0.5f), dy = MP_ABS(ty - 0.5f);
    return MP_ABS(MP_MAX(dx, dx * 0.5f + dy * 0.75f) - 0.5f);
}
MP_FUNC float mp_grid(int type, float x, float y, float z, float lineWidth, float transWidth) {
    float half = 0.5f * mp_clamp01(lineWidth), soft = 0.5f * MP_MAX(0.0f, transWidth);
    return 1.0f - mp_step(mp_grid_distance(type, x, y, z), half, soft);
}

// Modo's Dots: on squares (type 0), a hexagonal lattice (1) or cubes (2), dotWidth of a cell across.
MP_FUNC float mp_dots(int type, float x, float y, float z, float dotWidth, float transWidth) {
    float d;
    if (type == 1) {
        float ry = y * 2.0f;
    float row = MP_FLOOR(ry);
        float ty = ry - row, tx = mp_fract(x - 0.5f * mp_fract(row * 0.5f) * 2.0f);
        d = MP_SQRT((tx - 0.5f) * (tx - 0.5f) + (ty - 0.5f) * (ty - 0.5f));
    } else {
        float dx = mp_fract(x) - 0.5f, dy = mp_fract(y) - 0.5f, dz = type == 2 ? mp_fract(z) - 0.5f : 0.0f;
        d = MP_SQRT(dx * dx + dy * dy + dz * dz);
    }
    float radius = 0.5f * mp_clamp01(dotWidth), soft = 0.5f * MP_MAX(0.0f, transWidth);
    return 1.0f - mp_step(d, radius, soft);
}

// Modo's Wood: rings round the locator's Y axis, ringScale apart, bent by a slow wander and roughened by a grain
// that runs along Y. Dark at the start of a ring, easing to light across it, as a year's growth does.
MP_FUNC float mp_wood(float x, float y, float z, float ringScale, float wave, float waveScale, float grain, float grainScale) {
    float scale = MP_MAX(0.001f, waveScale), fine = MP_MAX(0.001f, grainScale);
    float wander = mp_noise(x / scale, y / scale, z / scale, 3) * MP_MAX(0.0f, wave);
    float ring = mp_fract(MP_SQRT(x * x + z * z) / MP_MAX(0.001f, ringScale) + wander);
    float t = 1.0f - MP_POW(ring, 0.6f);
    t = t + mp_noise(x / fine, y / (fine * 8.0f), z / fine, 5) * MP_MAX(0.0f, grain) * 0.6f;
    return mp_clamp01(t);
}

// Modo's Weave: yarns a unit apart across the locator's X and Y, over and under by turns, highest along their middle
// and where they pass over.
MP_FUNC float mp_weave(float x, float y, float yarnWidth, float roundness) {
    float cx = MP_FLOOR(x), cy = MP_FLOOR(y);
    float fx = x - cx, fy = y - cy;
    float width = MP_MAX(0.05f, mp_clamp01(yarnWidth));
    int across = (((int)cx + (int)cy) & 1) == 0 ? 1 : 0;
    float along = across != 0 ? fx : fy, side = across != 0 ? fy : fx;
    float off = MP_ABS(side - 0.5f);
    if (off > 0.5f * width) return 0.0f;
    float profile = MP_COS(MP_PI * off / width), arch = MP_COS(MP_PI * (along - 0.5f));
    float round = mp_clamp01(roundness);
    return mp_clamp01((1.0f - round) + round * profile * (0.5f + 0.5f * arch));
}

// Modo's Ripples: rings spreading from sources scattered through each unit cube, their crests added up.
MP_FUNC float mp_ripples(float x, float y, float z, float sources, float wavelength, float phase) {
    int count = (int)MP_MAX(1.0f, MP_MIN(64.0f, sources));
    float length = MP_MAX(0.01f, wavelength), total = 0.0f;
    float fx = mp_fract(x), fy = mp_fract(y), fz = mp_fract(z);
    for (int i = 0; i < count; i++) {
        float dx = MP_ABS(fx - mp_random(i, 17, 0, 0)), dy = MP_ABS(fy - mp_random(i, 29, 0, 0)), dz = MP_ABS(fz - mp_random(i, 43, 0, 0));
        // The nearer way round, so that the rings meet themselves across the cube's faces.
        dx = MP_MIN(dx, 1.0f - dx); dy = MP_MIN(dy, 1.0f - dy); dz = MP_MIN(dz, 1.0f - dz);
        total = total + MP_COS(2.0f * MP_PI * (MP_SQRT(dx * dx + dy * dy + dz * dz) / length - phase));
    }
    return mp_clamp01(0.5f + 0.5f * total / MP_SQRT((float)count));
}

// A Modo texture layer's bias and gain, 0.5 leaving the value as it is.
MP_FUNC float mp_bias(float x, float b) {
    b = MP_MIN(0.99999f, MP_MAX(0.00001f, b));
    x = mp_clamp01(x);
    return x / ((1.0f / b - 2.0f) * (1.0f - x) + 1.0f);
}
MP_FUNC float mp_gain(float t, float g) {
    return t < 0.5f ? 0.5f * mp_bias(2.0f * t, 1.0f - g) : 1.0f - 0.5f * mp_bias(2.0f - 2.0f * t, 1.0f - g);
}

// A pattern at a point of the locator's space, with its bias and gain: how much of the first colour there is.
// a to f are the pattern's own settings, in the order the plugin gives them (moonray_modo/procedurals.py, MAP_SETTINGS).
MP_FUNC float mp_pattern(int pattern, int type, float x, float y, float z, float a, float b, float c, float d, float e, float f,
                         float biasAmount, float gainAmount) {
    float t = 0.0f;
    if (pattern == MP_NOISE) t = mp_noise_pattern(type, x, y, z, a, b, c);
    else if (pattern == MP_CELLULAR) t = mp_cellular(type, x, y, z, a, b, c, d, e, f);
    else if (pattern == MP_CHECKER) t = mp_checker(type, x, y, z, a);
    else if (pattern == MP_GRID) t = mp_grid(type, x, y, z, a, b);
    else if (pattern == MP_DOTS) t = mp_dots(type, x, y, z, a, b);
    else if (pattern == MP_WOOD) t = mp_wood(x, y, z, a, b, c, d, e);
    else if (pattern == MP_WEAVE) t = mp_weave(x, y, a, b);
    else if (pattern == MP_RIPPLES) t = mp_ripples(x, y, z, a, b, c);
    return mp_gain(mp_bias(t, biasAmount), gainAmount);
}

#endif
