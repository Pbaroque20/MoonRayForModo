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
#define MP_HEAVY static inline
#define MP_FLOOR(x) floor(x)
#define MP_SQRT(x) sqrt(x)
#define MP_ABS(x) abs(x)
#define MP_COS(x) cos(x)
#define MP_POW(x, y) pow(x, y)
#define MP_MIN(x, y) min(x, y)
#define MP_MAX(x, y) max(x, y)
#elif defined(__CUDACC__)
#define MP_FUNC static __device__ __forceinline__
// Called rather than copied into every caller: copied, the patterns made each MoonLightIPR kernel nine times its size,
// which the graphics driver then took minutes to compile before the first picture.
#define MP_HEAVY static __device__ __noinline__
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
#define MP_HEAVY static inline
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
MP_HEAVY float mp_noise(float x, float y, float z, int seed) {
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
MP_HEAVY float mp_fractal(float x, float y, float z, int octaves, float ratio, float ampRatio, int turbulent, int seed) {
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
MP_HEAVY float mp_noise_pattern(int type, float x, float y, float z, float freqs, float freqRatio, float ampRatio) {
    int octaves = type == 0 ? 1 : (int)MP_MAX(1.0f, MP_MIN(16.0f, freqs));
    float ratio = MP_MAX(1.0f, freqRatio), weaker = MP_MAX(0.0f, ampRatio);
    if (type == 2) return mp_clamp01(1.6f * mp_fractal(x, y, z, octaves, ratio, weaker, 1, 11));
    return mp_clamp01(0.5f + 0.5f * 1.4f * mp_fractal(x, y, z, octaves, ratio, weaker, 0, 11));
}

// One frequency of Modo's Cellular, a cell a unit across: a point in each cell, round (type 0) within the cell's
// width of its point, angular (1) further than the gap from the cell's edge, each cell darkened by chance by variation.
MP_HEAVY float mp_cells(float x, float y, float z, int round, float width, float soft, float variation, int seed) {
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
MP_HEAVY float mp_cellular(int type, float x, float y, float z, float cellWidth, float transWidth, float freqs, float freqRatio,
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
MP_HEAVY float mp_grid(int type, float x, float y, float z, float lineWidth, float transWidth) {
    float half = 0.5f * mp_clamp01(lineWidth), soft = 0.5f * MP_MAX(0.0f, transWidth);
    return 1.0f - mp_step(mp_grid_distance(type, x, y, z), half, soft);
}

// Modo's Dots: on squares (type 0), a hexagonal lattice (1) or cubes (2), dotWidth of a cell across.
MP_HEAVY float mp_dots(int type, float x, float y, float z, float dotWidth, float transWidth) {
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
MP_HEAVY float mp_wood(float x, float y, float z, float ringScale, float wave, float waveScale, float grain, float grainScale) {
    float scale = MP_MAX(0.001f, waveScale), fine = MP_MAX(0.001f, grainScale);
    float wander = mp_noise(x / scale, y / scale, z / scale, 3) * MP_MAX(0.0f, wave);
    float ring = mp_fract(MP_SQRT(x * x + z * z) / MP_MAX(0.001f, ringScale) + wander);
    float t = 1.0f - MP_POW(ring, 0.6f);
    t = t + mp_noise(x / fine, y / (fine * 8.0f), z / fine, 5) * MP_MAX(0.0f, grain) * 0.6f;
    return mp_clamp01(t);
}

// Modo's Weave: yarns a unit apart across the locator's X and Y, over and under by turns, highest along their middle
// and where they pass over.
MP_HEAVY float mp_weave(float x, float y, float yarnWidth, float roundness) {
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
MP_HEAVY float mp_ripples(float x, float y, float z, float sources, float wavelength, float phase) {
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

// ---- Enhance: Modo's patterns ----------------------------------------------------------------------------------
// Their Noise Type: Perlin 0, EnhancedPerlin 1, Gradient 2, Value 3, GradientValue 4, Impulse 5, Lattice 6, Bubble 7.

// Smooth value noise, about -1 to 1: a random number at each whole point, eased between.
MP_HEAVY float mp_value_noise(float x, float y, float z, int seed) {
    float fx = MP_FLOOR(x), fy = MP_FLOOR(y), fz = MP_FLOOR(z);
    int ix = (int)fx, iy = (int)fy, iz = (int)fz;
    float u = mp_smooth(x - fx), v = mp_smooth(y - fy), w = mp_smooth(z - fz);
    float a = mp_lerp(mp_random(ix, iy, iz, seed), mp_random(ix + 1, iy, iz, seed), u);
    float b = mp_lerp(mp_random(ix, iy + 1, iz, seed), mp_random(ix + 1, iy + 1, iz, seed), u);
    float c = mp_lerp(mp_random(ix, iy, iz + 1, seed), mp_random(ix + 1, iy, iz + 1, seed), u);
    float d = mp_lerp(mp_random(ix, iy + 1, iz + 1, seed), mp_random(ix + 1, iy + 1, iz + 1, seed), u);
    return 2.0f * mp_lerp(mp_lerp(a, b, v), mp_lerp(c, d, v), w) - 1.0f;
}

// Sparse convolution: a few impulses of random strength scattered through each cell, each a smooth bump.
MP_HEAVY float mp_impulse_noise(float x, float y, float z, int seed) {
    float cx = MP_FLOOR(x), cy = MP_FLOOR(y), cz = MP_FLOOR(z), total = 0.0f;
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                int a = (int)cx + i, b = (int)cy + j, c = (int)cz + k;
                float dx = x - ((float)a + mp_random(a, b, c, seed));
                float dy = y - ((float)b + mp_random(a, b, c, seed + 1));
                float dz = z - ((float)c + mp_random(a, b, c, seed + 2));
                float d = dx * dx + dy * dy + dz * dz;
                if (d < 1.0f) total = total + (2.0f * mp_random(a, b, c, seed + 3) - 1.0f) * (1.0f - d) * (1.0f - d);
            }
        }
    }
    return MP_MAX(-1.0f, MP_MIN(1.0f, total));
}

// Bubbles: high at the middle of each cell's point, falling to the cells' edges.
MP_HEAVY float mp_bubble_noise(float x, float y, float z, int seed) {
    float cx = MP_FLOOR(x), cy = MP_FLOOR(y), cz = MP_FLOOR(z), first = 9.0f;
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                int a = (int)cx + i, b = (int)cy + j, c = (int)cz + k;
                float dx = x - ((float)a + mp_random(a, b, c, seed)), dy = y - ((float)b + mp_random(a, b, c, seed + 1));
                float dz = z - ((float)c + mp_random(a, b, c, seed + 2));
                first = MP_MIN(first, dx * dx + dy * dy + dz * dz);
            }
        }
    }
    return 1.0f - 2.0f * mp_clamp01(MP_SQRT(first));
}

// One of Enhance: Modo's noise bases, about -1 to 1.
MP_HEAVY float mp_basis(int type, float x, float y, float z, int seed) {
    if (type == 3 || type == 6) return mp_value_noise(x, y, z, seed);
    if (type == 4) return 0.5f * (mp_noise(x, y, z, seed) + mp_value_noise(x, y, z, seed + 101));
    if (type == 5) return mp_impulse_noise(x, y, z, seed);
    if (type == 7) return mp_bubble_noise(x, y, z, seed);
    if (type == 1) return 1.15f * mp_noise(x * 1.07f, y * 1.07f, z * 1.07f, seed + 31);
    return mp_noise(x, y, z, seed);
}

// Fractal sums, as Musgrave writes them: octaves of the basis, each lacunarity times finer and lacunarity to the -h
// weaker. absolute adds the bases' sizes. Returned about -1 to 1 (0 to 1 with absolute).
MP_HEAVY float mp_fbm(int type, float x, float y, float z, int seed, float octaves, float lacunarity, float h, int absolute) {
    float sum = 0.0f, weight = 0.0f, frequency = 1.0f;
    float lac = MP_MAX(1.01f, lacunarity);
    int count = (int)MP_MAX(1.0f, MP_MIN(12.0f, octaves));
    for (int i = 0; i < count; i++) {
        float amplitude = MP_POW(frequency, -h);
        float n = mp_basis(type, x * frequency, y * frequency, z * frequency, seed + 13 * i);
        sum = sum + amplitude * (absolute != 0 ? MP_ABS(n) : n);
        weight = weight + amplitude;
        frequency = frequency * lac;
    }
    return weight > 0.0f ? sum / weight : 0.0f;
}
MP_FUNC float mp_unit(float signedValue) { return mp_clamp01(0.5f + 0.5f * signedValue); }
// A value brought from lower .. upper to 0 .. 1, as Enhance: Modo's Lower and Upper do.
MP_FUNC float mp_range(float v, float lower, float upper) {
    float span = upper - lower;
    if (MP_ABS(span) < 1e-6f) return v >= lower ? 1.0f : 0.0f;
    return mp_clamp01((v - lower) / span);
}

typedef struct {
    float v[24];    // a pattern's settings from v[0], in the order procedurals.py gives them; v[22] bias, v[23] gain
} MP_Settings;

// Enhance: Modo's Noise patterns, 100 on, in the order of their names. Each reads its settings as listed beside it
// (procedurals.ENHANCE has the same lists), its Noise Type being type.
MP_HEAVY float mp_enhance_noise(int pattern, int type, float x, float y, float z, MP_Settings s) {
    int seed = (int)s.v[0];
    float t = 0.0f;
    if (pattern == 100) {
        // Agate: seed, absolute, lower, upper. Bands round the z axis, troubled by turbulence.
        float turb = mp_fbm(type, x, y, z, seed, 6.0f, 2.0f, 0.5f, 1);
        t = mp_range(0.5f + 0.5f * MP_COS(2.0f * MP_PI * (z * 1.5f + 3.0f * turb)), s.v[2], s.v[3]);
        if (s.v[1] != 0.0f) t = MP_ABS(2.0f * t - 1.0f);
    } else if (pattern == 101 || pattern == 121) {
        // Bozo and fBm: seed, octaves, frequency, increment, absolute, lower, upper.
        float f = mp_fbm(type, x, y, z, seed, s.v[1], s.v[2], s.v[3], s.v[4] != 0.0f ? 1 : 0);
        t = mp_range(s.v[4] != 0.0f ? f : mp_unit(f), s.v[5], s.v[6]);
    } else if (pattern == 102) {
        // Cruddy: seed, frequency, magnitude, lower, upper. Noise moved about by noise.
        float m = MP_MAX(0.0f, s.v[2]), f = MP_MAX(0.01f, s.v[1]);
        float w = mp_basis(type, x * f, y * f, z * f, seed + 7) * m;
        t = mp_range(mp_unit(mp_fbm(type, x * f + w, y * f - w, z * f + w, seed, 4.0f, 2.0f, 0.5f, 0)), s.v[3], s.v[4]);
    } else if (pattern == 103 || pattern == 104) {
        // Dented and Etched: seed, octaves, dentedness or corrosion, lower, upper. Pits of the sizes of the octaves.
        float d = mp_fbm(type, x, y, z, seed, s.v[1], 2.0f, 1.0f, 1);
        float power = MP_MAX(0.1f, s.v[2]) * (pattern == 104 ? 1.5f : 1.0f);
        t = mp_range(1.0f - MP_POW(mp_clamp01(d * 1.6f), power), s.v[3], s.v[4]);
    } else if (pattern == 105) {
        // FlowBozo (type is its Flow Type): seed, octaves, advection, time, absolute, lower, upper. Each octave
        // carried along by the coarser ones as time goes on.
        float sum = 0.0f, weight = 0.0f, frequency = 1.0f, ax = 0.0f, ay = 0.0f, az = 0.0f;
        int count = (int)MP_MAX(1.0f, MP_MIN(12.0f, s.v[1]));
        for (int i = 0; i < count; i++) {
            float amplitude = 1.0f / frequency;
            float n = mp_noise(x * frequency + ax + s.v[3], y * frequency + ay, z * frequency + az - s.v[3], seed + 13 * i);
            if (type == 1) n = n * MP_ABS(n);
            if (type == 2) n = -n;
            sum = sum + amplitude * (s.v[4] != 0.0f ? MP_ABS(n) : n);
            weight = weight + amplitude;
            ax = ax + s.v[2] * amplitude * n; ay = ay - s.v[2] * amplitude * n; az = az + 0.5f * s.v[2] * amplitude * n;
            frequency = frequency * 2.0f;
        }
        float f = weight > 0.0f ? sum / weight : 0.0f;
        t = mp_range(s.v[4] != 0.0f ? f : mp_unit(f), s.v[5], s.v[6]);
    } else if (pattern == 106) {
        // Granite: seed, octaves, frequency, fold, lower, upper. Gritz's: |0.5 - noise| over the octaves.
        float sum = 0.0f, frequency = 1.0f;
        int count = (int)MP_MAX(1.0f, MP_MIN(12.0f, s.v[1]));
        for (int i = 0; i < count; i++) {
            sum = sum + MP_ABS(0.5f - mp_unit(mp_basis(type, x * frequency * 4.0f, y * frequency * 4.0f, z * frequency * 4.0f, seed + 13 * i))) / frequency;
            frequency = frequency * MP_MAX(1.01f, s.v[2]);
        }
        if (s.v[3] != 0.0f) sum = MP_ABS(2.0f * mp_fract(sum) - 1.0f);
        t = mp_range(mp_clamp01(sum), s.v[4], s.v[5]);
    } else if (pattern == 107 || pattern == 113) {
        // Hybrid: seed, octaves, frequency, increment, offset, heterogeneous, lower, upper. PuffyClouds: seed,
        // octaves, frequency, increment, coverage, heterogeneous, lower, upper. Musgrave's hybrid multifractal.
        float lac = MP_MAX(1.01f, s.v[2]), offset = pattern == 107 ? s.v[4] : 0.7f, frequency = 1.0f;
        float result = mp_basis(type, x, y, z, seed) + offset;
        float weight = result;
        int count = (int)MP_MAX(1.0f, MP_MIN(12.0f, s.v[1]));
        for (int i = 1; i < count; i++) {
            frequency = frequency * lac;
            weight = MP_MIN(1.0f, weight);
            float signal = (mp_basis(type, x * frequency, y * frequency, z * frequency, seed + 13 * i) + offset) * MP_POW(frequency, -s.v[3]);
            result = result + (s.v[5] != 0.0f ? 1.0f : weight) * signal;
            weight = weight * signal;
        }
        float v = mp_clamp01(result / (1.0f + offset + 0.5f * (float)(count - 1)));
        if (pattern == 113) v = mp_clamp01((v - (1.0f - mp_clamp01(s.v[4]))) / MP_MAX(0.05f, mp_clamp01(s.v[4])));
        t = mp_range(v, s.v[6], s.v[7]);
    } else if (pattern == 108) {
        // Lump: seed, octaves, frequency, lower, upper. Rounded lumps: the sizes of the octaves.
        t = mp_range(mp_clamp01(1.5f * mp_fbm(type, x, y, z, seed, s.v[1], s.v[2], 0.6f, 1)), s.v[3], s.v[4]);
    } else if (pattern == 109 || pattern == 110) {
        // MarbleNoise: seed, octaves, frequency, increment, lower, upper. MarbleVein: those and sharpness before
        // lower and upper. Bands across x, bent by turbulence; the veins are where the bands turn.
        float turb = mp_fbm(type, x, y, z, seed, s.v[1], s.v[2], s.v[3], 1);
        float band = 0.5f + 0.5f * MP_COS(MP_PI * (x * 2.0f + 6.0f * turb));
        if (pattern == 110) {
            float sharp = MP_MIN(0.98f, MP_MAX(0.0f, s.v[4]));
            band = MP_POW(1.0f - MP_ABS(2.0f * band - 1.0f), 1.0f / (1.0f - sharp));
            t = mp_range(band, s.v[5], s.v[6]);
        } else t = mp_range(band, s.v[4], s.v[5]);
    } else if (pattern == 111) {
        // MultiFractal: seed, octaves, frequency, increment, offset, lower, upper. Musgrave's multiplicative cascade.
        float value = 1.0f, frequency = 1.0f;
        int count = (int)MP_MAX(1.0f, MP_MIN(12.0f, s.v[1]));
        for (int i = 0; i < count; i++) {
            value = value * (s.v[4] + mp_basis(type, x * frequency, y * frequency, z * frequency, seed + 13 * i) * MP_POW(frequency, -s.v[3]));
            frequency = frequency * MP_MAX(1.01f, s.v[2]);
        }
        t = mp_range(mp_clamp01(value), s.v[5], s.v[6]);
    } else if (pattern == 112) {
        // Pebbles: seed, min freq, max freq, steps, magnitude, frequency, lower, upper. Stones of sizes between
        // the two frequencies, rounded and jostled by noise.
        float jostle = mp_basis(type, x * s.v[5], y * s.v[5], z * s.v[5], seed + 3) * 0.3f * MP_MAX(0.0f, s.v[4]);
        float low = MP_MAX(0.01f, s.v[1]);
        float high = MP_MAX(low, s.v[2]), best = 0.0f;
        int steps = (int)MP_MAX(1.0f, MP_MIN(6.0f, s.v[3]));
        for (int i = 0; i < steps; i++) {
            float f = steps > 1 ? low + (high - low) * (float)i / (float)(steps - 1) : low;
            float edge = 0.5f + 0.5f * mp_bubble_noise((x + jostle) * f, (y - jostle) * f, (z + jostle) * f, seed + 17 * i);
            best = MP_MAX(best, MP_POW(mp_clamp01(edge), 0.5f));
        }
        t = mp_range(best, s.v[6], s.v[7]);
    } else if (pattern == 114) {
        // Ridged: seed, octaves, frequency, increment, offset, threshold, lower, upper. Musgrave's ridged multifractal.
        float frequency = 1.0f, signal = s.v[4] - MP_ABS(mp_basis(type, x, y, z, seed));
        signal = signal * signal;
        float result = signal;
        int count = (int)MP_MAX(1.0f, MP_MIN(12.0f, s.v[1]));
        for (int i = 1; i < count; i++) {
            frequency = frequency * MP_MAX(1.01f, s.v[2]);
            float weight = mp_clamp01(signal * s.v[5]);
            signal = s.v[4] - MP_ABS(mp_basis(type, x * frequency, y * frequency, z * frequency, seed + 13 * i));
            signal = signal * signal * weight;
            result = result + signal * MP_POW(frequency, -s.v[3]);
        }
        t = mp_range(mp_clamp01(result / MP_MAX(0.1f, s.v[4] * s.v[4] * 1.5f)), s.v[6], s.v[7]);
    } else if (pattern == 115) {
        // Scar: seed, octaves, frequency, increment, lower, upper. Thin lines where the noise crosses its middle.
        float f = mp_fbm(type, x, y, z, seed, s.v[1], MP_MAX(1.01f, s.v[2]) * 1.0f + 1.0f, s.v[3], 0);
        t = mp_range(MP_POW(1.0f - mp_clamp01(MP_ABS(f) * 4.0f), 6.0f), s.v[4], s.v[5]);
    } else if (pattern == 116) {
        // Scruffed: seed, length, coverage, axis (X 0, Y 1, Z 2), lower, upper. Scratches drawn out along the axis.
        float stretch = 1.0f / MP_MAX(1.0f, s.v[1]);
        int axis = (int)s.v[3];
        float sx = axis == 0 ? x * stretch : x * 8.0f, sy = axis == 1 ? y * stretch : y * 8.0f, sz = axis == 2 ? z * stretch : z * 8.0f;
        float n = mp_unit(mp_fbm(type, sx, sy, sz, seed, 3.0f, 2.0f, 0.5f, 0));
        t = mp_range(mp_step(n, 1.0f - 0.5f * mp_clamp01(s.v[2]), 0.02f), s.v[4], s.v[5]);
    } else if (pattern == 117) {
        // Strata: seed, octaves, frequency, increment, width, magnitude, axis, lower, upper. Layers across the axis,
        // bent by noise, width of each band filled.
        int axis = (int)s.v[6];
        float along = axis == 0 ? x : (axis == 1 ? y : z);
        float bend = mp_fbm(type, x, y, z, seed, s.v[1], s.v[2], s.v[3], 0) * s.v[5];
        float layer = mp_fract(along * 4.0f + bend);
        t = mp_range(mp_step(mp_clamp01(s.v[4]), layer, 0.05f), s.v[7], s.v[8]);
    } else if (pattern == 118) {
        // Stucco: seed, octaves, frequency, increment, power, lower, upper. Sharp plaster bumps.
        float f = mp_unit(mp_fbm(type, x * 4.0f, y * 4.0f, z * 4.0f, seed, s.v[1], s.v[2], s.v[3], 0));
        t = mp_range(MP_POW(f, MP_MAX(0.1f, s.v[4]) * 0.25f), s.v[5], s.v[6]);
    } else if (pattern == 119 || pattern == 120) {
        // VectorBozo: seed, octaves, frequency, magnitude, fractalize, lower, upper. WrappedfBm: seed, octaves,
        // frequency, magnitude, lower, upper. Noise looked up where noise moves the point.
        float m = MP_MAX(0.0f, s.v[3]);
        int fractal = pattern == 120 || s.v[4] != 0.0f ? 1 : 0;
        float wx = mp_fbm(type, x + 5.2f, y + 1.3f, z, seed + 1, fractal != 0 ? s.v[1] : 1.0f, MP_MAX(1.01f, s.v[2]), 0.5f, 0) * m;
        float wy = mp_fbm(type, x, y + 9.2f, z + 2.8f, seed + 2, fractal != 0 ? s.v[1] : 1.0f, MP_MAX(1.01f, s.v[2]), 0.5f, 0) * m;
        float wz = mp_fbm(type, x + 3.7f, y, z + 7.1f, seed + 3, fractal != 0 ? s.v[1] : 1.0f, MP_MAX(1.01f, s.v[2]), 0.5f, 0) * m;
        float f = mp_fbm(type, x + wx, y + wy, z + wz, seed, pattern == 120 ? s.v[1] : 1.0f, MP_MAX(1.01f, s.v[2]), 0.5f, 0);
        t = mp_range(mp_unit(f), pattern == 120 ? s.v[4] : s.v[5], pattern == 120 ? s.v[5] : s.v[6]);
    }
    return t;
}

// Cells: a point scattered in each unit cube, jitter of the cube from its middle. what is 0 to 3 for the distance to
// the nearest to the fourth nearest point, 4 for the second less the first (0 on the cells' edges), 5 for the nearest
// cell's own random number.
MP_HEAVY float mp_worley(float x, float y, float z, int seed, float jitter, int what) {
    float cx = MP_FLOOR(x), cy = MP_FLOOR(y), cz = MP_FLOOR(z);
    float d1 = 9.0f, d2 = 9.0f, d3 = 9.0f, d4 = 9.0f;
    int nx = 0, ny = 0, nz = 0;
    float spread = mp_clamp01(jitter);
    for (int k = -1; k <= 1; k++) {
        for (int j = -1; j <= 1; j++) {
            for (int i = -1; i <= 1; i++) {
                int a = (int)cx + i, b = (int)cy + j, c = (int)cz + k;
                float px = (float)a + 0.5f + spread * (mp_random(a, b, c, seed) - 0.5f);
                float py = (float)b + 0.5f + spread * (mp_random(a, b, c, seed + 1) - 0.5f);
                float pz = (float)c + 0.5f + spread * (mp_random(a, b, c, seed + 2) - 0.5f);
                float d = MP_SQRT((x - px) * (x - px) + (y - py) * (y - py) + (z - pz) * (z - pz));
                if (d < d1) { d4 = d3; d3 = d2; d2 = d1; d1 = d; nx = a; ny = b; nz = c; }
                else if (d < d2) { d4 = d3; d3 = d2; d2 = d; }
                else if (d < d3) { d4 = d3; d3 = d; }
                else if (d < d4) d4 = d;
            }
        }
    }
    if (what == 0) return d1;
    if (what == 1) return d2;
    if (what == 2) return d3;
    if (what == 3) return d4;
    if (what == 4) return d2 - d1;
    return mp_random(nx, ny, nz, seed + 5);
}

// Cells over several frequencies, each lacunarity times finer and lacunarity to the -h weaker.
MP_HEAVY float mp_worley_fractal(float x, float y, float z, int seed, float jitter, int what, float octaves, float lacunarity, float h) {
    float sum = 0.0f, weight = 0.0f, frequency = 1.0f;
    int count = (int)MP_MAX(1.0f, MP_MIN(8.0f, octaves));
    for (int i = 0; i < count; i++) {
        float amplitude = MP_POW(frequency, -h);
        sum = sum + amplitude * mp_worley(x * frequency, y * frequency, z * frequency, seed + 19 * i, jitter, what);
        weight = weight + amplitude;
        frequency = frequency * MP_MAX(1.01f, lacunarity);
    }
    return weight > 0.0f ? sum / weight : 0.0f;
}

// Enhance: Modo's Organic patterns, 130 on, in the order of their names; the settings each reads are beside it
// (procedurals.ENHANCE). type is its Noise Type, Cell Order (F1 0 to F4 3) or Shape, as it has.
MP_HEAVY float mp_enhance_organic(int pattern, int type, float x, float y, float z, MP_Settings s) {
    int seed = (int)s.v[0];
    float t = 0.0f;
    if (pattern == 130) {
        // ArtDeco: seed, octaves, frequency, increment, power, lower, upper, regions. Cells in sweeping bands.
        float f = s.v[7] != 0.0f ? mp_worley(x, y, z, seed, 1.0f, 5) : mp_worley_fractal(x, y, z, seed, 1.0f, 0, MP_MAX(1.0f, s.v[1]), s.v[2], s.v[3]);
        t = mp_range(MP_POW(mp_clamp01(f), MP_MAX(0.05f, s.v[4])), s.v[5], s.v[6]);
    } else if (pattern == 131) {
        // Blister: levels, lower, upper. Raised bubbles of several sizes.
        float best = 0.0f, scale = 1.0f;
        int count = (int)MP_MAX(1.0f, MP_MIN(6.0f, s.v[0]));
        for (int i = 0; i < count; i++) {
            best = MP_MAX(best, 0.5f + 0.5f * mp_bubble_noise(x * scale, y * scale, z * scale, 41 + 7 * i));
            scale = scale * 2.0f;
        }
        t = mp_range(best, s.v[1], s.v[2]);
    } else if (pattern == 132) {
        // Branches: branches, width, seed, octaves, magnitude, scale, detail, full 3D, lower, upper. Branching lines
        // where the noise crosses its middle, as many as branches.
        int bseed = (int)s.v[2];
        float sc = MP_MAX(0.01f, s.v[5]);
        float bz = s.v[7] != 0.0f ? z * sc : 0.0f;
        float n = mp_fbm(type, x * sc * MP_MAX(1.0f, s.v[0]) * 0.5f, y * sc * MP_MAX(1.0f, s.v[0]) * 0.5f, bz, bseed, s.v[3], 2.0f, 1.0f - 0.5f * mp_clamp01(s.v[6]), 0);
        n = n + s.v[4] * 0.2f * mp_basis(type, x * sc * 4.0f, y * sc * 4.0f, bz * 4.0f, bseed + 9);
        t = mp_range(1.0f - mp_clamp01(MP_ABS(n) / MP_MAX(0.005f, s.v[1] * 0.25f)), s.v[8], s.v[9]);
    } else if (pattern == 133) {
        // Caustic: seed, octaves, frequency, increment, lower, upper. Bright light gathered into a net.
        float wx = mp_fbm(type, x, y, z, seed + 1, s.v[1], s.v[2], s.v[3], 0) * 0.4f;
        float e = mp_worley(x * 2.0f + wx, y * 2.0f - wx, z * 2.0f + wx, seed, 1.0f, 4);
        t = mp_range(MP_POW(1.0f - mp_clamp01(e * 3.0f), 4.0f), s.v[4], s.v[5]);
    } else if (pattern == 134 || pattern == 135 || pattern == 137) {
        // Cellular: seed, octaves, frequency, increment, fractalize, lower, upper, regions. Cheesy: seed, octaves,
        // frequency, increment, lower, upper, regions. Crackle: as Cellular. type is the Cell Order.
        int fractal = pattern == 135 ? 1 : (s.v[4] != 0.0f ? 1 : 0);
        float octaves = fractal != 0 ? s.v[1] : 1.0f;
        int last = pattern == 135 ? 6 : 7;
        float lower = pattern == 135 ? s.v[4] : s.v[5], upper = pattern == 135 ? s.v[5] : s.v[6];
        float v;
        if (s.v[last] != 0.0f) v = mp_worley(x, y, z, seed, 1.0f, 5);
        else if (pattern == 137) v = mp_clamp01(mp_worley_fractal(x, y, z, seed, 1.0f, 4, octaves, s.v[2], s.v[3]) * 2.0f);
        else if (pattern == 135) v = mp_step(mp_worley_fractal(x, y, z, seed, 1.0f, type, octaves, s.v[2], s.v[3]), 0.35f, 0.04f);
        else v = mp_clamp01(mp_worley_fractal(x, y, z, seed, 1.0f, type, octaves, s.v[2], s.v[3]));
        t = mp_range(v, lower, upper);
    } else if (pattern == 136) {
        // Concrete: seed, lower, upper. A cloudy grey with fine specks of grit.
        float cloud = mp_unit(mp_fbm(type, x * 2.0f, y * 2.0f, z * 2.0f, seed, 5.0f, 2.0f, 0.6f, 0));
        float grit = mp_step(mp_random((int)MP_FLOOR(x * 60.0f), (int)MP_FLOOR(y * 60.0f), (int)MP_FLOOR(z * 60.0f), seed + 3), 0.85f, 0.0f);
        t = mp_range(mp_clamp01(0.8f * cloud + 0.2f * grit), s.v[1], s.v[2]);
    } else if (pattern == 138) {
        // Dirt: seed, frequency 1, magnitude 1, frequency 2, magnitude 2, lower, upper. Grime at two sizes.
        float a = mp_fbm(type, x * s.v[1], y * s.v[1], z * s.v[1], seed, 4.0f, 2.0f, 0.5f, 0) * s.v[2];
        float b = mp_fbm(type, x * s.v[3], y * s.v[3], z * s.v[3], seed + 7, 3.0f, 2.0f, 0.5f, 0) * s.v[4];
        t = mp_range(mp_clamp01(0.5f + 0.5f * a + 0.25f * b), s.v[5], s.v[6]);
    } else if (pattern == 139) {
        // Disturbed: seed, distance, frequency, angle, lower, upper. Noise pushed aside and turned by noise.
        float push = mp_basis(type, x * s.v[2], y * s.v[2], z * s.v[2], seed + 5) * s.v[1] * 0.25f;
        float turn = s.v[3] * MP_PI * mp_basis(type, x, y, z, seed + 6);
        float rx = x * MP_COS(turn) - y * (MP_COS(turn - 0.5f * MP_PI));
        float ry = x * (MP_COS(turn - 0.5f * MP_PI)) + y * MP_COS(turn);
        t = mp_range(mp_unit(mp_basis(type, (rx + push) * s.v[2], (ry - push) * s.v[2], z * s.v[2], seed)), s.v[4], s.v[5]);
    } else if (pattern == 140 || pattern == 144) {
        // EasyWood: seed, octaves, magnitude, scale, detail, lower, upper. HardWood: seed, graininess, ringiness,
        // lower, upper. Rings round the locator's Y axis, wandering with noise.
        float ringScale = pattern == 140 ? MP_MAX(0.01f, s.v[3]) : MP_MAX(0.1f, s.v[2]);
        float wander = pattern == 140 ? s.v[2] * 0.3f * mp_fbm(type, x * s.v[4], y * s.v[4] * 0.2f, z * s.v[4], seed, s.v[1], 2.0f, 0.5f, 0)
                                      : 0.3f * mp_fbm(type, x, y * 0.2f, z, seed, 3.0f, 2.0f, 0.5f, 0);
        float r = MP_SQRT(x * x + z * z) * ringScale + wander;
        float grain = pattern == 144 ? s.v[1] * mp_basis(type, x * 40.0f, y * 2.0f, z * 40.0f, seed + 3) : 0.0f;
        float ring = pattern == 140 ? mp_fract(r) : 0.5f + 0.5f * MP_COS(2.0f * MP_PI * r);
        float lower = pattern == 140 ? s.v[5] : s.v[3], upper = pattern == 140 ? s.v[6] : s.v[4];
        t = mp_range(mp_clamp01(ring + grain), lower, upper);
    } else if (pattern == 141) {
        // Electric: seed, octaves, frequency, increment, width, lower, upper. Bright forks where the noise crosses 0.
        float n = mp_fbm(type, x, y, z, seed, MP_MAX(1.0f, s.v[1]), s.v[2], s.v[3], 0);
        t = mp_range(mp_clamp01(1.0f - MP_ABS(n) / MP_MAX(0.005f, s.v[4] * 0.25f)), s.v[5], s.v[6]);
    } else if (pattern == 142 || pattern == 143) {
        // Fire: seed, flame height, magnitude, fragmentation, detail, speed, time, lower, upper. FireWall: seed,
        // octaves, frequency, increment, height, lower, upper. Flames rising up the locator's Y axis, licked by
        // noise that moves up with time.
        float rise = pattern == 142 ? s.v[5] * s.v[6] : 0.0f;
        float flicker;
        float height;
        if (pattern == 142) {
            float f = MP_MAX(0.01f, s.v[3] * 0.1f);
            flicker = s.v[2] * mp_fbm(type, x * f, (y - rise) * f, z * f, seed, MP_MAX(1.0f, s.v[4] * 2.0f), 2.0f, 0.5f, 1);
            height = MP_MAX(0.01f, s.v[1]);
        } else {
            flicker = mp_fbm(type, x, y, z, seed, s.v[1], s.v[2], s.v[3], 1);
            height = MP_MAX(0.01f, s.v[4]);
        }
        float v = mp_clamp01(1.0f - y / height + flicker - 0.3f);
        float lower = pattern == 142 ? s.v[7] : s.v[5], upper = pattern == 142 ? s.v[8] : s.v[6];
        t = mp_range(v, lower, upper);
    } else if (pattern == 145 || pattern == 150) {
        // Membrane and Wires: seed, octaves, frequency, increment, jitter, grout, bevel, lower, upper. Cells parted
        // by grout and rounded by a bevel; Wires is the grout itself.
        float e = 0.5f * mp_worley_fractal(x, y, z, seed, s.v[4], 4, s.v[1], s.v[2], s.v[3]);
        float grout = MP_MAX(0.0f, s.v[5]) * 0.5f;
        float v = mp_smooth((e - grout) / MP_MAX(0.001f, s.v[6] * 0.5f));
        if (e < grout) v = 0.0f;
        if (pattern == 150) v = 1.0f - v;
        t = mp_range(v, s.v[7], s.v[8]);
    } else if (pattern == 146) {
        // Minky: seed, octaves, frequency, increment, power, lower, upper, regions. A soft pile, cell by cell.
        float f = s.v[7] != 0.0f ? mp_worley(x, y, z, seed, 1.0f, 5) : 1.0f - mp_clamp01(mp_worley_fractal(x, y, z, seed, 1.0f, type, s.v[1], s.v[2], s.v[3]));
        t = mp_range(MP_POW(mp_clamp01(f), MP_MAX(0.05f, s.v[4])), s.v[5], s.v[6]);
    } else if (pattern == 147) {
        // Scatter (type: Spheres 0, Cubes 1, Diamonds 2): seed, distribution, spread, scale, smooth, lower, upper.
        // A shape in some of the cells, as many as distribution says, moved about by spread.
        float cx = MP_FLOOR(x), cy = MP_FLOOR(y), cz = MP_FLOOR(z), best = 0.0f;
        float radius = 0.5f * MP_MAX(0.0f, s.v[3]);
        float soft = MP_MAX(0.001f, s.v[4] * radius);
        for (int k = -1; k <= 1; k++) {
            for (int j = -1; j <= 1; j++) {
                for (int i = -1; i <= 1; i++) {
                    int a = (int)cx + i, b = (int)cy + j, c = (int)cz + k;
                    if (mp_random(a, b, c, seed + 7) > mp_clamp01(s.v[1])) continue;
                    float dx = MP_ABS(x - ((float)a + 0.5f + s.v[2] * (mp_random(a, b, c, seed) - 0.5f)));
                    float dy = MP_ABS(y - ((float)b + 0.5f + s.v[2] * (mp_random(a, b, c, seed + 1) - 0.5f)));
                    float dz = MP_ABS(z - ((float)c + 0.5f + s.v[2] * (mp_random(a, b, c, seed + 2) - 0.5f)));
                    float d = type == 1 ? MP_MAX(MP_MAX(dx, dy), dz) : (type == 2 ? (dx + dy + dz) * 0.7f : MP_SQRT(dx * dx + dy * dy + dz * dz));
                    best = MP_MAX(best, 1.0f - mp_smooth((d - radius + soft) / soft));
                }
            }
        }
        t = mp_range(best, s.v[5], s.v[6]);
    } else if (pattern == 148) {
        // SinBlob: seed, lower, upper. Waves bending through each other into soft blobs.
        float o = (float)(seed % 97) * 0.13f;
        float a = MP_COS(3.0f * x + o + 2.0f * MP_COS(2.0f * y - o));
        float b = MP_COS(3.0f * y - o + 2.0f * MP_COS(2.0f * z + o));
        float c = MP_COS(3.0f * z + o + 2.0f * MP_COS(2.0f * x));
        t = mp_range(mp_clamp01(0.5f + (a + b + c) / 6.0f), s.v[1], s.v[2]);
    } else if (pattern == 149) {
        // Veins: seed, octaves, veininess, lower, upper. Thin veins where the noise crosses its middle.
        float n = mp_fbm(type, x, y, z, seed, s.v[1], 2.0f, 0.5f, 0);
        t = mp_range(MP_POW(1.0f - mp_clamp01(MP_ABS(n) * 2.0f), MP_MAX(0.5f, s.v[2] * 8.0f)), s.v[3], s.v[4]);
    } else if (pattern == 151) {
        // WormVein: seed, lo, hi, lower, upper. Worm-like bands where the noise lies between lo and hi.
        float n = mp_unit(mp_fbm(type, x, y, z, seed, 4.0f, 2.0f, 0.5f, 0));
        float lo = MP_MIN(s.v[1], s.v[2]), hi = MP_MAX(s.v[1], s.v[2]);
        t = mp_range(mp_step(n, lo, 0.01f) * (1.0f - mp_step(n, hi, 0.01f)), s.v[3], s.v[4]);
    }
    return t;
}

// A pattern at a point of the locator's space, with its bias and gain: how much of the first colour there is.
// Modo's own patterns read s.v[0] to s.v[5] (procedurals.MAP_SETTINGS); Enhance: Modo's (100 on) read theirs.
MP_HEAVY float mp_pattern(int pattern, int type, float x, float y, float z, MP_Settings s) {
    float t = 0.0f;
    if (pattern == MP_NOISE) t = mp_noise_pattern(type, x, y, z, s.v[0], s.v[1], s.v[2]);
    else if (pattern == MP_CELLULAR) t = mp_cellular(type, x, y, z, s.v[0], s.v[1], s.v[2], s.v[3], s.v[4], s.v[5]);
    else if (pattern == MP_CHECKER) t = mp_checker(type, x, y, z, s.v[0]);
    else if (pattern == MP_GRID) t = mp_grid(type, x, y, z, s.v[0], s.v[1]);
    else if (pattern == MP_DOTS) t = mp_dots(type, x, y, z, s.v[0], s.v[1]);
    else if (pattern == MP_WOOD) t = mp_wood(x, y, z, s.v[0], s.v[1], s.v[2], s.v[3], s.v[4]);
    else if (pattern == MP_WEAVE) t = mp_weave(x, y, s.v[0], s.v[1]);
    else if (pattern == MP_RIPPLES) t = mp_ripples(x, y, z, s.v[0], s.v[1], s.v[2]);
    else if (pattern >= 100 && pattern < 130) t = mp_enhance_noise(pattern, type, x, y, z, s);
    else if (pattern >= 130 && pattern < 160) t = mp_enhance_organic(pattern, type, x, y, z, s);
    return mp_gain(mp_bias(t, s.v[22]), s.v[23]);
}

#endif
