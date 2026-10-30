// Private experimental: MoonRay's Perlin and simplex noise (lib/common/noise/ispc
// Noise.ispc, Perlin.ispc, Simplex.ispc) for NoiseMap_v2. The tables (a
// permutation of 0..2047 and, for Perlin, unit gradients) are built on the host
// as Noise and Perlin build them (noise_admission in map_admission.h). Derived
// from MoonRay Apache-2.0, Copyright 2023-2024 DreamWorks Animation LLC. See
// MOONRAY_LICENSE.txt.
#pragma once
#include "shade_math.h"
#include "shade_tables.h"
// shade_tables.h undefines its table macro: this header's own.
#if defined(__CUDACC__)
#define X2_NOISE_TABLE static __device__ const
#else
#define X2_NOISE_TABLE inline constexpr
#endif
namespace xpu2 { namespace interactive { namespace shade {

constexpr int NoiseTableSize = 2048;  // NOISE_MAP_TABLE_SIZE and Noise's default
// One noise's tables in the map pool: the permutation (ints as their bits), then x, y, z (and w) gradients.
struct NoiseTable {
    const float* perm = nullptr;
    const float* g = nullptr;  // gradients x at g[i], y at g[i + 2048], z at g[i + 4096], w at g[i + 6144]
};
X2_HD inline int noisePerm(const NoiseTable& n, int i) { return reinterpret_cast<const int*>(n.perm)[i & (NoiseTableSize - 1)]; }
X2_HD inline int noiseIndex3D(const NoiseTable& n, int ix, int iy, int iz) { return noisePerm(n, ix + noisePerm(n, iy + noisePerm(n, iz))); }
X2_HD inline int noiseIndex4D(const NoiseTable& n, int ix, int iy, int iz, int iw) {
    return noisePerm(n, ix + noisePerm(n, iy + noisePerm(n, iz + noisePerm(n, iw))));
}

//----------------------------------------------------------------------------
// Perlin (Perlin.ispc).
X2_HD inline float noiseScurve(float t) { return t * t * (3 - 2 * t); }
X2_HD inline float perlinGlattice3D(const NoiseTable& n, int ix, int iy, int iz, float fx, float fy, float fz) {
    const int i = noiseIndex3D(n, ix, iy, iz);
    return n.g[i] * fx + n.g[i + NoiseTableSize] * fy + n.g[i + 2 * NoiseTableSize] * fz;
}
X2_HD inline float perlin3D(const NoiseTable& n, const float pos[3]) {
    const int ix = int(floorf(pos[0])), iy = int(floorf(pos[1])), iz = int(floorf(pos[2]));
    const float fx0 = pos[0] - float(ix), fy0 = pos[1] - float(iy), fz0 = pos[2] - float(iz);
    const float fx1 = fx0 - 1.f, fy1 = fy0 - 1.f, fz1 = fz0 - 1.f;
    const float wx = noiseScurve(fx0), wy = noiseScurve(fy0), wz = noiseScurve(fz0);
    float vx0 = perlinGlattice3D(n, ix, iy, iz, fx0, fy0, fz0);
    float vx1 = perlinGlattice3D(n, ix + 1, iy, iz, fx1, fy0, fz0);
    float vy0 = lerpf(vx0, vx1, wx);
    vx0 = perlinGlattice3D(n, ix, iy + 1, iz, fx0, fy1, fz0);
    vx1 = perlinGlattice3D(n, ix + 1, iy + 1, iz, fx1, fy1, fz0);
    float vy1 = lerpf(vx0, vx1, wx);
    const float vz0 = lerpf(vy0, vy1, wy);
    vx0 = perlinGlattice3D(n, ix, iy, iz + 1, fx0, fy0, fz1);
    vx1 = perlinGlattice3D(n, ix + 1, iy, iz + 1, fx1, fy0, fz1);
    vy0 = lerpf(vx0, vx1, wx);
    vx0 = perlinGlattice3D(n, ix, iy + 1, iz + 1, fx0, fy1, fz1);
    vx1 = perlinGlattice3D(n, ix + 1, iy + 1, iz + 1, fx1, fy1, fz1);
    vy1 = lerpf(vx0, vx1, wx);
    const float vz1 = lerpf(vy0, vy1, wy);
    return lerpf(vz0, vz1, wz);
}
X2_HD inline float perlinGlattice4D(const NoiseTable& n, const int i4[4], const float f[4]) {
    const int i = noiseIndex4D(n, i4[0], i4[1], i4[2], i4[3]);
    return n.g[i] * f[0] + n.g[i + NoiseTableSize] * f[1] + n.g[i + 2 * NoiseTableSize] * f[2] + n.g[i + 3 * NoiseTableSize] * f[3];
}
X2_HD inline float perlin4D(const NoiseTable& n, const float pos[4]) {
    int i0[4];
    float f0[4], w[4];
    for (int k = 0; k < 4; ++k) {
        i0[k] = int(floorf(pos[k]));
        f0[k] = pos[k] - float(i0[k]);
        w[k] = noiseScurve(f0[k]);
    }
    // The 16 corners in Perlin.ispc's order: x fastest, then y, z and w; each lerp as there.
    float vw[2];
    for (int dw = 0; dw < 2; ++dw) {
        float vz[2];
        for (int dz = 0; dz < 2; ++dz) {
            float vy[2];
            for (int dy = 0; dy < 2; ++dy) {
                float vx[2];
                for (int dx = 0; dx < 2; ++dx) {
                    const int c[4] = {i0[0] + dx, i0[1] + dy, i0[2] + dz, i0[3] + dw};
                    const float f[4] = {f0[0] - float(dx), f0[1] - float(dy), f0[2] - float(dz), f0[3] - float(dw)};
                    vx[dx] = perlinGlattice4D(n, c, f);
                }
                vy[dy] = lerpf(vx[0], vx[1], w[0]);
            }
            vz[dz] = lerpf(vy[0], vy[1], w[1]);
        }
        vw[dw] = lerpf(vz[0], vz[1], w[2]);
    }
    return lerpf(vw[0], vw[1], w[3]);
}
// NOISE_perlinFractal3D/4D: ceil(maxLevel) octaves, the last weighted by its fraction.
X2_HD inline float perlinFractal(const NoiseTable& n, const float pos[4], bool fourD, float maxLevel, float persistence, float lacunarity) {
    float p[4] = {pos[0], pos[1], pos[2], fourD ? pos[3] : 0.0f};
    float noise = 0.f, scale = 1.f;
    const int numLevels = int(ceilf(maxLevel));
    for (int i = 0; i < numLevels; ++i) {
        if (i + 1 == numLevels) scale = scale * (1.f - (float(numLevels) - maxLevel));
        noise = noise + (fourD ? perlin4D(n, p) : perlin3D(n, p)) * scale;
        scale *= persistence;
        for (int k = 0; k < 4; ++k) p[k] = p[k] * lacunarity;
    }
    return noise;
}

//----------------------------------------------------------------------------
// Simplex (Simplex.ispc, Constants.h).
constexpr float SimplexF3 = 0.333333333f, SimplexG3 = 0.166666667f, SimplexF4 = 0.309016994375f, SimplexG4 = 0.138196601125f;
#define X2_GV 0.81649658f
#define X2_NGV -0.81649658f
X2_NOISE_TABLE float SimplexGradients3DU[16][3] = {
    {1.0f, 0.0f, 1.0f}, {0.0f, 1.0f, 1.0f}, {-1.0f, 0.0f, 1.0f}, {0.0f, -1.0f, 1.0f}, {1.0f, 0.0f, -1.0f}, {0.0f, 1.0f, -1.0f},
    {-1.0f, 0.0f, -1.0f}, {0.0f, -1.0f, -1.0f}, {X2_GV, X2_GV, X2_GV}, {X2_NGV, X2_GV, X2_NGV}, {X2_NGV, X2_NGV, X2_GV},
    {X2_GV, X2_NGV, X2_NGV}, {X2_NGV, X2_GV, X2_GV}, {X2_GV, X2_NGV, X2_GV}, {X2_GV, X2_NGV, X2_NGV}, {X2_NGV, X2_GV, X2_NGV}};
X2_NOISE_TABLE float SimplexGradients3DV[16][3] = {
    {X2_NGV, X2_GV, X2_GV}, {X2_NGV, X2_NGV, X2_GV}, {X2_GV, X2_NGV, X2_GV}, {X2_GV, X2_GV, X2_GV}, {X2_NGV, X2_NGV, X2_NGV},
    {X2_GV, X2_NGV, X2_NGV}, {X2_GV, X2_GV, X2_NGV}, {X2_NGV, X2_GV, X2_NGV}, {1.0f, -1.0f, 0.0f}, {1.0f, 1.0f, 0.0f},
    {-1.0f, 1.0f, 0.0f}, {-1.0f, -1.0f, 0.0f}, {1.0f, 0.0f, 1.0f}, {-1.0f, 0.0f, 1.0f}, {0.0f, 1.0f, -1.0f}, {0.0f, -1.0f, -1.0f}};
X2_NOISE_TABLE float SimplexGradients4DU[32][4] = {
    {0, 1, 1, 1},   {0, 1, 1, -1},   {0, 1, -1, 1},   {0, 1, -1, -1},   {0, -1, 1, 1},   {0, -1, 1, -1},   {0, -1, -1, 1},
    {0, -1, -1, -1}, {1, 0, 1, 1},   {1, 0, 1, -1},   {1, 0, -1, 1},   {1, 0, -1, -1},  {-1, 0, 1, 1},   {-1, 0, 1, -1},
    {-1, 0, -1, 1}, {-1, 0, -1, -1}, {1, 1, 0, 1},    {1, 1, 0, -1},   {1, -1, 0, 1},   {1, -1, 0, -1},  {-1, 1, 0, 1},
    {-1, 1, 0, -1}, {-1, -1, 0, 1},  {-1, -1, 0, -1}, {1, 1, 1, 0},    {1, 1, -1, 0},   {1, -1, 1, 0},   {1, -1, -1, 0},
    {-1, 1, 1, 0},  {-1, 1, -1, 0},  {-1, -1, 1, 0},  {-1, -1, -1, 0}};
X2_NOISE_TABLE float SimplexGradients4DV[32][4] = {
    {X2_NGV, X2_NGV, X2_GV, 1}, {X2_NGV, X2_NGV, X2_GV, -1}, {X2_GV, X2_NGV, X2_NGV, 1}, {X2_GV, X2_NGV, X2_NGV, -1},
    {X2_GV, X2_GV, X2_GV, 1},   {X2_GV, X2_GV, X2_GV, -1},   {X2_NGV, X2_GV, X2_NGV, 1}, {X2_NGV, X2_GV, X2_NGV, -1},
    {X2_NGV, X2_GV, X2_GV, 1},  {X2_NGV, X2_GV, X2_GV, -1},  {X2_NGV, X2_NGV, X2_NGV, 1}, {X2_NGV, X2_NGV, X2_NGV, -1},
    {X2_GV, X2_NGV, X2_GV, 1},  {X2_GV, X2_NGV, X2_GV, -1},  {X2_GV, X2_GV, X2_NGV, 1},  {X2_GV, X2_GV, X2_NGV, -1},
    {X2_NGV, X2_GV, X2_NGV, 1}, {X2_NGV, X2_GV, X2_NGV, -1}, {X2_GV, X2_GV, X2_GV, 1},   {X2_GV, X2_GV, X2_GV, -1},
    {X2_NGV, X2_NGV, X2_GV, 1}, {X2_NGV, X2_NGV, X2_GV, -1}, {X2_GV, X2_NGV, X2_NGV, 1}, {X2_GV, X2_NGV, X2_NGV, -1},
    {1, 0, -1, 0},              {1, 0, 1, 0},                {-1, 0, 1, 0},              {1, 0, 1, 0},
    {-1, 0, -1, 0},             {1, 0, -1, 0},               {-1, 0, -1, 0},             {-1, 0, 1, 0}};
#undef X2_GV
#undef X2_NGV

// NOISE_simplex3D: the noise, and its derivatives (for the flow advection of the fractal).
X2_HD inline float simplex3D(const NoiseTable& n, const float pos[3], float angle, float deriv[3]) {
    float ns[4], t0[4], t2[4], t4[4], gDot[4], gRot[4][3], d[4][3];
    deriv[0] = deriv[1] = deriv[2] = 0.0f;
    const float sin_t = sinf(angle), cos_t = cosf(angle);
    const float s = (pos[0] + pos[1] + pos[2]) * SimplexF3;
    const int i0 = int(floorf(pos[0] + s)), j0 = int(floorf(pos[1] + s)), k0 = int(floorf(pos[2] + s));
    const float t = float(i0 + j0 + k0) * SimplexG3;
    d[0][0] = pos[0] - (float(i0) - t);
    d[0][1] = pos[1] - (float(j0) - t);
    d[0][2] = pos[2] - (float(k0) - t);
    int i1, j1, k1, i2, j2, k2;
    if (d[0][0] >= d[0][1]) {
        if (d[0][1] >= d[0][2]) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
        else if (d[0][0] >= d[0][2]) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1; }
        else { i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1; }
    } else {
        if (d[0][1] < d[0][2]) { i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1; }
        else if (d[0][0] < d[0][2]) { i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1; }
        else { i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
    }
    const int o1[3] = {i1, j1, k1}, o2[3] = {i2, j2, k2};
    for (int c = 0; c < 3; ++c) {
        d[1][c] = d[0][c] - float(o1[c]) + SimplexG3;
        d[2][c] = d[0][c] - float(o2[c]) + 2.0f * SimplexG3;
        d[3][c] = d[0][c] - 1.0f + 3.0f * SimplexG3;
    }
    const int ii = i0 % 256, jj = j0 % 256, kk = k0 % 256;
    const int hash[4] = {noiseIndex3D(n, ii, jj, kk), noiseIndex3D(n, ii + i1, jj + j1, kk + k1), noiseIndex3D(n, ii + i2, jj + j2, kk + k2),
                         noiseIndex3D(n, ii + 1, jj + 1, kk + 1)};
    for (int p = 0; p < 4; p++) {
        t0[p] = 0.5f - (d[p][0] * d[p][0] + d[p][1] * d[p][1] + d[p][2] * d[p][2]);
        t2[p] = t0[p] * t0[p];
        t4[p] = t2[p] * t2[p];
        const int h = hash[p] & 15;
        for (int c = 0; c < 3; ++c) gRot[p][c] = cos_t * SimplexGradients3DU[h][c] + sin_t * SimplexGradients3DV[h][c];
        if (t0[p] < 0.0f) {
            ns[p] = t0[p] = t2[p] = t4[p] = gDot[p] = 0.0f;
        } else {
            gDot[p] = gRot[p][0] * d[p][0] + gRot[p][1] * d[p][1] + gRot[p][2] * d[p][2];
            ns[p] = t4[p] * gDot[p];
        }
        const float dTmp = t2[p] * t0[p] * gDot[p];
        for (int c = 0; c < 3; ++c) deriv[c] = deriv[c] + dTmp * d[p][c];
    }
    const float noise = 28.0f * (ns[0] + ns[1] + ns[2] + ns[3]);
    for (int c = 0; c < 3; ++c) {
        deriv[c] = deriv[c] * -8.0f;
        deriv[c] = deriv[c] + t4[0] * gRot[0][c] + t4[1] * gRot[1][c] + t4[2] * gRot[2][c] + t4[3] * gRot[3][c];
        deriv[c] = deriv[c] * 28.0f;
    }
    return noise;
}
X2_HD inline float simplex4D(const NoiseTable& n, const float pos[4], float angle, float deriv[4]) {
    float ns[5], t0[5], t2[5], t4[5], gDot[5], gRot[5][4], d[5][4];
    for (int c = 0; c < 4; ++c) deriv[c] = 0.0f;
    const float sin_t = sinf(angle), cos_t = cosf(angle);
    const float s = (pos[0] + pos[1] + pos[2] + pos[3]) * SimplexF4;
    int i0[4];
    for (int c = 0; c < 4; ++c) i0[c] = int(floorf(pos[c] + s));
    const float t = float(i0[0] + i0[1] + i0[2] + i0[3]) * SimplexG4;
    for (int c = 0; c < 4; ++c) d[0][c] = pos[c] - (float(i0[c]) - t);
    int rank[4] = {0, 0, 0, 0};
    for (int a = 0; a < 4; ++a)
        for (int b = a + 1; b < 4; ++b) {
            if (d[0][a] > d[0][b]) ++rank[a];
            else ++rank[b];
        }
    int o[3][4];
    for (int c = 0; c < 4; ++c) {
        o[0][c] = rank[c] >= 3 ? 1 : 0;
        o[1][c] = rank[c] >= 2 ? 1 : 0;
        o[2][c] = rank[c] >= 1 ? 1 : 0;
    }
    for (int c = 0; c < 4; ++c) {
        d[1][c] = d[0][c] - float(o[0][c]) + SimplexG4;
        d[2][c] = d[0][c] - float(o[1][c]) + 2.0f * SimplexG4;
        d[3][c] = d[0][c] - float(o[2][c]) + 3.0f * SimplexG4;
        d[4][c] = d[0][c] - 1.0f + 4.0f * SimplexG4;
    }
    const int ii = i0[0] % 256, jj = i0[1] % 256, kk = i0[2] % 256, ll = i0[3] % 256;
    int hash[5];
    hash[0] = noiseIndex4D(n, ii, jj, kk, ll) % 32;
    for (int q = 0; q < 3; ++q) hash[q + 1] = noiseIndex4D(n, ii + o[q][0], jj + o[q][1], kk + o[q][2], ll + o[q][3]) % 32;
    hash[4] = noiseIndex4D(n, ii + 1, jj + 1, kk + 1, ll + 1) % 32;
    for (int p = 0; p < 5; p++) {
        t0[p] = 0.5f - (d[p][0] * d[p][0] + d[p][1] * d[p][1] + d[p][2] * d[p][2] + d[p][3] * d[p][3]);
        t2[p] = t0[p] * t0[p];
        t4[p] = t2[p] * t2[p];
        const int h = hash[p] & 31;
        for (int c = 0; c < 4; ++c) gRot[p][c] = cos_t * SimplexGradients4DU[h][c] + sin_t * SimplexGradients4DV[h][c];
        gRot[p][3] = SimplexGradients4DU[h][3];
        if (t0[p] < 0.0f) {
            ns[p] = t0[p] = t2[p] = t4[p] = gDot[p] = 0.0f;
        } else {
            gDot[p] = gRot[p][0] * d[p][0] + gRot[p][1] * d[p][1] + gRot[p][2] * d[p][2] + gRot[p][3] * d[p][3];
            ns[p] = t4[p] * gDot[p];
        }
        const float dTmp = t2[p] * t0[p] * gDot[p];
        for (int c = 0; c < 4; ++c) deriv[c] = deriv[c] + dTmp * d[p][c];
    }
    const float noise = 27.0f * (ns[0] + ns[1] + ns[2] + ns[3] + ns[4]);
    for (int c = 0; c < 4; ++c) {
        deriv[c] = deriv[c] * -8.0f;
        deriv[c] = deriv[c] + t4[0] * gRot[0][c] + t4[1] * gRot[1][c] + t4[2] * gRot[2][c] + t4[3] * gRot[3][c] + t4[4] * gRot[4][c];
        deriv[c] = deriv[c] * 27.0f;
    }
    return noise;
}
// NOISE_simplexFractal3D/4D: octaves with the flow angle and advection by the previous octaves' derivatives.
X2_HD inline float simplexFractal(const NoiseTable& n, const float pos[4], bool fourD, float angle, float advection, float maxLevel,
                                  float persistence, float lacunarity) {
    const int dims = fourD ? 4 : 3;
    float p[4] = {pos[0], pos[1], pos[2], fourD ? pos[3] : 0.0f}, advect[4] = {0, 0, 0, 0}, deriv[4] = {0, 0, 0, 0};
    float weight = 1.f, noise = 0.f;
    const int numLevels = int(ceilf(maxLevel));
    for (int i = 0; i < numLevels; ++i) {
        if (i + 1 == numLevels) weight *= 1.f - (float(numLevels) - maxLevel);
        noise += (fourD ? simplex4D(n, p, angle, deriv) : simplex3D(n, p, angle, deriv)) * weight;
        weight *= persistence;
        for (int c = 0; c < dims; ++c) p[c] = p[c] * lacunarity + advect[c];
        angle *= lacunarity;
        for (int c = 0; c < dims; ++c) advect[c] = i == 0 ? -advection * deriv[c] : advect[c] - advection * deriv[c] * weight;
    }
    return noise;
}

//----------------------------------------------------------------------------
// Worley (Worley.ispc), as NoiseWorleyMap uses it: one feature point a cell (V3) or a Poisson count
// (V1, V2), the nearest four kept sorted (sortByDistance), fractal levels accumulated.
enum WorleyDistance : int { WorleyLinear = 0, WorleyLinearSquared, WorleyManhattan, WorleyChebyshev, WorleyQuadratic, WorleyMinkowski };
struct WorleyTables {
    NoiseTable perm;  // the permutation (perm only)
    const float *x = nullptr, *y = nullptr, *z = nullptr;  // the feature points, 2048 each
    const float *probLow = nullptr, *probHigh = nullptr;   // [m] for m 1..9
};
struct WorleyPoint {
    V3 diff, gradient, position;
    float dist;
    int id;
};
X2_HD inline void worleyDistanceOf(float& distance, V3 diff, int method, float mn) {
    switch (method) {
    case WorleyLinearSquared: distance = sqrtf(distance); break;
    case WorleyManhattan: distance = fabsf(diff.x) + fabsf(diff.y) + fabsf(diff.z); break;
    case WorleyChebyshev: distance = fmaxf(fmaxf(fabsf(diff.x), fabsf(diff.y)), fabsf(diff.z)); break;
    case WorleyQuadratic: {
        const float a = diff.x, b = diff.y, c = diff.z;
        distance = a * a + a * b + a * c + b * c + b * b + c * c;
        break;
    }
    case WorleyMinkowski:
        distance = powf(powf(fabsf(diff.x), mn) + powf(fabsf(diff.y), mn) + powf(fabsf(diff.z), mn), 1.0f / mn);
        break;
    default: break;
    }
}
X2_HD inline void worleySort(WorleyPoint wp[4], float distance, V3 diff, V3 gradient, V3 position, int id) {
    if (!(distance < wp[3].dist)) return;
    int k = 3;
    while (k > 0 && distance < wp[k - 1].dist) {
        wp[k] = wp[k - 1];
        --k;
    }
    wp[k].dist = distance;
    wp[k].diff = diff;
    wp[k].gradient = gradient;
    wp[k].position = position;
    wp[k].id = id;
}
X2_HD inline int worleyPointCount(const WorleyTables& w, int hash) {
    int low = 1, high = 9, m = 1;
    const float prob = w.x[noisePerm(w.perm, hash + 5)];
    while (low <= high) {
        m = (low + high) / 2;
        if (prob < w.probLow[m]) high = m - 1;
        else if (prob >= w.probHigh[m]) low = m + 1;
        else break;
    }
    return m;
}
X2_HD inline void worleyCheckCell(const WorleyTables& w, bool v3, int ix, int iy, int iz, V3 pos, WorleyPoint wp[4], float jitter,
                                  int method, float mn) {
    int hash = noiseIndex3D(w.perm, ix, iy, iz);
    const int count = v3 ? 1 : worleyPointCount(w, hash);
    for (int i = 0; i < count; i++) {
        const V3 position{float(ix) + 0.5f + (w.x[hash] - 0.5f) * jitter, float(iy) + 0.5f + (w.y[hash] - 0.5f) * jitter,
                          float(iz) + 0.5f + (w.z[hash] - 0.5f) * jitter};
        const V3 diff = pos - position, gradient = position - pos;
        float distance = dot(diff, diff);
        if (v3) worleyDistanceOf(distance, diff, method, mn);
        worleySort(wp, distance, diff, gradient, position, hash);
        hash = (hash + 1) & (NoiseTableSize - 1);
    }
}
// The neighbour cells in worley3D's order: faces, xy, yz and xz edges, corners.
X2_NOISE_TABLE signed char WorleyOffsets[26][3] = {
        {-1, 0, 0},  {1, 0, 0},   {0, -1, 0},   {0, 1, 0},   {0, 0, -1},  {0, 0, 1},                                  // faces
        {-1, -1, 0}, {-1, 1, 0},  {1, -1, 0},   {1, 1, 0},                                                            // xy edges
        {0, -1, -1}, {0, -1, 1},  {0, 1, -1},   {0, 1, 1},                                                            // yz edges
        {-1, 0, -1}, {-1, 0, 1},  {1, 0, -1},   {1, 0, 1},                                                            // xz edges
        {-1, -1, -1}, {-1, -1, 1}, {-1, 1, -1}, {-1, 1, 1}, {1, -1, -1}, {1, -1, 1}, {1, 1, -1}, {1, 1, 1}};      // corners
// worley3D: the centre cell, then its neighbours (faces, edges, corners, in Worley.ispc's order) that
// could hold a nearer point than the fourth.
X2_HD inline void worley3D(const WorleyTables& w, bool v3, V3 pos, WorleyPoint wp[4], float jitter, int method, float mn) {
    const int ix = int(floorf(pos.x)), iy = int(floorf(pos.y)), iz = int(floorf(pos.z));
    const float fx = pos.x - ix, fy = pos.y - iy, fz = pos.z - iz;
    const float near2[3] = {fx * fx, fy * fy, fz * fz};
    const float far2[3] = {(1.0f - fx) * (1.0f - fx), (1.0f - fy) * (1.0f - fy), (1.0f - fz) * (1.0f - fz)};
    worleyCheckCell(w, v3, ix, iy, iz, pos, wp, jitter, method, mn);
    for (int k = 0; k < 26; ++k) {
        bool check = true;
        for (int a = 0; a < 3; ++a)
            if (WorleyOffsets[k][a]) check = check && (WorleyOffsets[k][a] < 0 ? near2[a] : far2[a]) < wp[3].dist;
        if (check) worleyCheckCell(w, v3, ix + WorleyOffsets[k][0], iy + WorleyOffsets[k][1], iz + WorleyOffsets[k][2], pos, wp, jitter, method, mn);
    }
}
// NOISE_worleySearchPointsFractal: the first four points' distances and gradients over the levels.
X2_HD inline void worleyFractal(const WorleyTables& w, bool v3, float jitter, float mn, float maxLevel, int method, V3 position,
                                WorleyPoint out[4]) {
    WorleyPoint wp[4];
    for (int i = 0; i < 4; ++i) {
        out[i].id = 0;
        out[i].dist = 0.0f;
        out[i].gradient = out[i].position = out[i].diff = V3{0, 0, 0};
        wp[i].id = 0;
        wp[i].dist = 3.402823466e+38f;
        wp[i].gradient = wp[i].position = wp[i].diff = V3{0, 0, 0};
    }
    auto level = [&](int lvl, float amplitude) {
        worley3D(w, v3, position, wp, jitter, method, mn);
        if (!v3 && method != WorleyLinear)
            for (int i = 0; i < 4; ++i) worleyDistanceOf(wp[i].dist, wp[i].diff, method, mn);
        for (int j = 0; j < 4; ++j) {
            out[j].dist += wp[j].dist * amplitude;
            out[j].gradient = out[j].gradient + normalize(wp[j].gradient) * amplitude;
            if (lvl == 0) {
                out[j].position = wp[j].position;
                out[j].id = wp[j].id;
            }
        }
    };
    const int numLevels = int(floorf(maxLevel));
    float amplitude = 1.0f;
    for (int lvl = 0; lvl < numLevels; lvl++) {
        level(lvl, amplitude);
        amplitude /= 2.0f;
        position = position * 2.0f;
        for (int i = 0; i < 4; ++i) wp[i].dist = 3.402823466e+38f;
    }
    const float lastLevel = maxLevel - float(numLevels);
    if (!isZero(lastLevel)) {
        level(numLevels, amplitude);
        const float averages[4] = {0.36887115126f, 0.49110174090f, 0.57151765397f, 0.63471361297f};
        for (int i = 0; i < 4; ++i) out[i].dist += averages[i] * amplitude * (1.0f - lastLevel);
    }
}
X2_HD inline Color worleyCellColor(const WorleyTables& w, int cellId) {
    const int hash = noisePerm(w.perm, cellId);
    return Color{w.x[hash], w.y[hash], w.z[hash]};
}

// gain (scene_rdl2 Math.isph): the classic PDI definition, over biasf.
X2_HD inline float gainf(float val, float g) {
    if (g == 0.5f) return val;
    if (val < 0.5f) return biasf(2.0f * val, 1.0f - g) * 0.5f;
    return 1.0f - biasf(2.0f - 2.0f * val, 1.0f - g) * 0.5f;
}
// INTERPOLATION_smoothStep (moonshine common/interpolation).
X2_HD inline float noiseSmoothStep(float x, float edge0, float edge1) {
    const float t = saturate((x - edge0) / fmaxf(edge1 - edge0, Epsilon));
    return t * t * (3 - 2 * t);
}
}}}
