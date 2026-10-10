#pragma once
// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Raphael Tobar. MoonLightIPR is not affiliated with DreamWorks Animation; see moonlightipr/NOTICE.md.
// Minimal float3 arithmetic for device code; NVRTC supplies the type but no operators.
#define ML_INLINE static __forceinline__ __device__
#define ML_PI 3.14159265358979323846f

ML_INLINE float3 vec(const float* v) { return make_float3(v[0], v[1], v[2]); }
ML_INLINE float3 vec(float v) { return make_float3(v, v, v); }
ML_INLINE float3 operator+(float3 a, float3 b) { return make_float3(a.x + b.x, a.y + b.y, a.z + b.z); }
ML_INLINE float3 operator-(float3 a, float3 b) { return make_float3(a.x - b.x, a.y - b.y, a.z - b.z); }
ML_INLINE float3 operator-(float3 a) { return make_float3(-a.x, -a.y, -a.z); }
ML_INLINE float3 operator*(float3 a, float3 b) { return make_float3(a.x * b.x, a.y * b.y, a.z * b.z); }
ML_INLINE float3 operator*(float3 a, float s) { return make_float3(a.x * s, a.y * s, a.z * s); }
ML_INLINE float3 operator*(float s, float3 a) { return a * s; }
ML_INLINE float3 operator/(float3 a, float s) { return a * (1.0f / s); }
ML_INLINE float3& operator+=(float3& a, float3 b) { a = a + b; return a; }
ML_INLINE float3& operator*=(float3& a, float3 b) { a = a * b; return a; }
ML_INLINE float dot(float3 a, float3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
ML_INLINE float3 cross(float3 a, float3 b) {
    return make_float3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
}
ML_INLINE float length(float3 a) { return sqrtf(dot(a, a)); }
ML_INLINE float3 normalize(float3 a) { return a * (1.0f / sqrtf(dot(a, a))); }
ML_INLINE float3 lerp(float3 a, float3 b, float t) { return a + (b - a) * t; }
ML_INLINE float clamp(float v, float lo, float hi) { return fminf(fmaxf(v, lo), hi); }
ML_INLINE float luminance(float3 c) { return 0.2126f * c.x + 0.7152f * c.y + 0.0722f * c.z; }
ML_INLINE float maxComponent(float3 c) { return fmaxf(c.x, fmaxf(c.y, c.z)); }
ML_INLINE bool finite(float3 c) { return isfinite(c.x) && isfinite(c.y) && isfinite(c.z); }

// Orthonormal basis around a unit normal (Duff et al. 2017).
struct Frame {
    float3 t, b, n;
    __forceinline__ __device__ explicit Frame(float3 normal) : n(normal) {
        const float sign = copysignf(1.0f, n.z);
        const float a = -1.0f / (sign + n.z);
        const float c = n.x * n.y * a;
        t = make_float3(1.0f + sign * n.x * n.x * a, sign * c, -sign * n.x);
        b = make_float3(c, sign + n.y * n.y * a, -n.y);
    }
    // With a given tangent, which need not be exactly perpendicular to the normal.
    __forceinline__ __device__ Frame(float3 normal, float3 tangent) : n(normal) {
        t = normalize(tangent - n * dot(tangent, n));
        b = cross(n, t);
    }
    __forceinline__ __device__ float3 toLocal(float3 v) const { return make_float3(dot(v, t), dot(v, b), dot(v, n)); }
    __forceinline__ __device__ float3 toWorld(float3 v) const { return t * v.x + b * v.y + n * v.z; }
};

// Tiny Encryption Algorithm hash for a per-pixel, per-sample seed, then a 24-bit LCG stream.
ML_INLINE unsigned tea(unsigned v0, unsigned v1) {
    unsigned sum = 0;
    for (int i = 0; i < 16; ++i) {
        sum += 0x9e3779b9;
        v0 += ((v1 << 4) + 0xa341316c) ^ (v1 + sum) ^ ((v1 >> 5) + 0xc8013ea4);
        v1 += ((v0 << 4) + 0xad90777d) ^ (v0 + sum) ^ ((v0 >> 5) + 0x7e95761e);
    }
    return v0;
}
ML_INLINE float rnd(unsigned& state) {
    state = state * 1664525u + 1013904223u;
    return float(state & 0x00ffffff) / float(0x01000000);
}
