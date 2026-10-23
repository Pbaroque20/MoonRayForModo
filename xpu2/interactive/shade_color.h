// Private XPU2 shading library, shared CPU/CUDA: colour spaces and ramps.
// Derived from MoonRay Apache-2.0 scene_rdl2 ColorSpace.isph and
// shading/ispc/RampControl.ispc, Copyright 2023-2024 DreamWorks Animation LLC.
// See MOONRAY_LICENSE.txt. A ramp is prepared (slopes, colour space) once, on
// the host, by rampInit; the devices evaluate it.
#pragma once
#include "shade_math.h"
namespace xpu2 { namespace interactive { namespace shade {

X2_HD inline int maxRgbChannel(Color c) {
    float m = c.x;
    int r = 0;
    if (c.y > m) {
        m = c.y;
        r = 1;
    }
    if (c.z > m) r = 2;
    return r;
}
X2_HD inline float rgbToHue(Color c, float chroma, int maxChannel) {
    if (isZero(chroma)) return 0.0f;
    float h = maxChannel == 0 ? (c.y - c.z) / chroma : maxChannel == 1 ? 2.0f + (c.z - c.x) / chroma : 4.0f + (c.x - c.y) / chroma;
    h = fmodf(h * 60.0f, 360.0f);
    if (h < 0.0f) h += 360.0f;
    return h / 360.0f;
}
X2_HD inline float rgbToHue(Color c) {
    const float mn = fminf(c.x, fminf(c.y, c.z)), mx = fmaxf(c.x, fmaxf(c.y, c.z)), chroma = mx - mn;
    if (isZero(chroma)) return 0.0f;
    float h;
    if (isEqual(mx, c.x)) h = (c.y - c.z) / chroma;
    else if (isEqual(mx, c.y)) h = 2.0f + (c.z - c.x) / chroma;
    else h = 4.0f + (c.x - c.y) / chroma;
    h = fmodf(h * 60.0f, 360.0f);
    if (h < 0.0f) h += 360.0f;
    return h / 360.0f;
}
X2_HD inline Color rgbToHsv(Color c) {
    const int mi = maxRgbChannel(c);
    const float mn = fminf(c.x, fminf(c.y, c.z)), mx = fmaxf(c.x, fmaxf(c.y, c.z)), chroma = mx - mn;
    float h = 0.0f, s = 0.0f;
    if (!isZero(mx)) {
        h = rgbToHue(c, chroma, mi);
        s = chroma / mx;
    }
    return {h, s, mx};
}
X2_HD inline Color rgbToHsl(Color c) {
    const int mi = maxRgbChannel(c);
    const float mn = fminf(c.x, fminf(c.y, c.z)), mx = fmaxf(c.x, fmaxf(c.y, c.z)), chroma = mx - mn;
    float h = 0.0f, s = 0.0f;
    const float l = (mx + mn) * 0.5f;
    if (!isZero(chroma)) {
        if (l > 0.5f) s = isEqual(l, 1.0f) ? 1.0f : fabsf(chroma * 0.5f / (1.0f - l));
        else s = l <= 0 ? chroma : chroma * 0.5f / l;
        h = rgbToHue(c, chroma, mi);
    }
    return {h, s, l};
}
X2_HD inline int hueSector(float& h) {
    h = fmodf(h, 1.0f);
    if (h < 0) h += 1.0f;
    h *= 360.0f;
    if (isEqual(h, 360.0f)) h = 0.0f;
    h /= 60.0f;
    return int(h);
}
X2_HD inline Color hsvToRgb(Color hsv) {
    float h = hsv.x;
    const float s = hsv.y, v = hsv.z;
    if (isZero(s)) return {v, v, v};
    const int sector = hueSector(h);
    const float f = h - float(sector), p = v * (1.0f - s), q = v * (1.0f - s * f), t = v * (1.0f - s * (1.0f - f));
    switch (sector) {
    case 0: return {v, t, p};
    case 1: return {q, v, p};
    case 2: return {p, v, t};
    case 3: return {p, q, v};
    case 4: return {t, p, v};
    case 5: return {v, p, q};
    default: return {p, p, p};
    }
}
X2_HD inline Color hslToRgb(Color hsl) {
    float h = hsl.x;
    const float s = hsl.y, l = hsl.z;
    if (isZero(s)) return {l, l, l};
    const int sector = hueSector(h);
    const float f = h - float(sector);
    float p, w, q, t;
    if (l < 0.5f) {
        p = l * (1.0f - s);
        w = l * (1.0f + s);
        q = l * (s * (1.0f - 2.0f * f) + 1.0f);
        t = l * (s * (2.0f * f - 1.0f) + 1.0f);
    } else {
        p = l * (1.0f + s) - s;
        w = l * (1.0f - s) + s;
        q = l * (1.0f + s * (2.0f * f - 1.0f)) + s * (1.0f - 2.0f * f);
        t = l * (1.0f + s * (1.0f - 2.0f * f)) + s * (2.0f * f - 1.0f);
    }
    switch (sector) {
    case 0: return {w, t, p};
    case 1: return {q, w, p};
    case 2: return {p, w, t};
    case 3: return {p, q, w};
    case 4: return {t, p, w};
    case 5: return {w, p, q};
    default: return {p, p, p};
    }
}
X2_HD inline Color hueToRgb(float hue) { return hsvToRgb({hue, 1.0f, 1.0f}); }

// RampControl
enum RampInterpolator : U32 { RampNone = 0, RampLinear, RampExponentialUp, RampExponentialDown, RampSmooth, RampCatmullRom, RampMonotoneCubic };
enum RampSpace : U32 { RampRgb = 0, RampHsv, RampHsl };
enum Ramp2D : U32 { RampV = 0, RampU, RampDiagonal, RampRadial, RampCircular, RampBox, RampUxV, RampFourCorner, RampInput };
constexpr U32 RampMaxPoints = 10;
struct FloatRamp {
    float inputs[RampMaxPoints], outputs[RampMaxPoints], slopes[RampMaxPoints];
    U32 interpolators[RampMaxPoints];
    U32 count = 0;
};
struct ColorRamp {
    float inputs[RampMaxPoints];
    Color outputs[RampMaxPoints], slopes[RampMaxPoints];
    U32 interpolators[RampMaxPoints];
    U32 count = 0, space = RampRgb, hueBlend = 1;
};
X2_HD inline float lineSlope(float i0, float o0, float i1, float o1) { return i0 == i1 ? 0.0f : (o1 - o0) / (i1 - i0); }
X2_HD inline float signOf(float v) { return v < 0.0f ? -1.0f : 1.0f; }
X2_HD inline void monotoneSlope(float i0, float o0, float i1, float o1, float i2, float o2, float i3, float o3, int end,
                                float& s1, float& s2) {
    const float d2 = (end != 2 && end != 3) ? lineSlope(i2, o2, i3, o3) : 0.0f;
    const float d1 = end != 3 ? lineSlope(i1, o1, i2, o2) : 0.0f;
    const float d0 = (end != 1 && end != 3) ? lineSlope(i0, o0, i1, o1) : 0.0f;
    if (isZero(d1)) {
        s1 = s2 = 0.0f;
        return;
    }
    if (end == 1) {
        s1 = d1;
        s2 = signOf(d1) == signOf(d2) ? (d2 + d1) / 2.0f : 0.0f;
    } else if (end == 2) {
        s1 = signOf(d0) == signOf(d1) ? (d0 + d1) / 2.0f : 0.0f;
        s2 = d1;
    } else {
        s1 = signOf(d0) == signOf(d1) ? (d0 + d1) / 2.0f : 0.0f;
        s2 = signOf(d1) == signOf(d2) ? (d2 + d1) / 2.0f : 0.0f;
    }
    const float alpha = s1 / d1, beta = s2 / d1;
    if (alpha < 0.0f || beta < 0.0f) return;
    if (alpha * alpha + beta * beta > 9.0f) {
        const float tau = 3.0f / sqrtf(alpha * alpha + beta * beta);
        s1 *= tau;
        s2 *= tau;
    }
}
// evaluateMonotoneSlopes, one channel: outputs read through get(i), slopes written through set(i, v).
template <class Get, class Set>
X2_HD inline void monotoneSlopes(const float* inputs, U32 n, const U32* interpolators, Get get, Set set) {
    bool cubic = false;
    for (U32 i = 0; i < n; ++i)
        if (interpolators[i] == RampMonotoneCubic) cubic = true;
    if (!cubic) return;
    int idx;
    for (idx = 0; idx < int(n) - 1; idx += 2) {
        int k0 = idx - 1, k1 = idx, k2 = idx + 1, k3 = idx + 2, end = 0;
        if (idx == 0) {
            k0 = k1;
            end = 1;
        }
        if (idx + 1 == int(n) - 1) {
            k3 = k2;
            end = end == 1 ? 3 : 2;
        }
        float s1, s2;
        monotoneSlope(inputs[k0], get(k0), inputs[k1], get(k1), inputs[k2], get(k2), inputs[k3], get(k3), end, s1, s2);
        set(k1, s1);
        set(k2, s2);
    }
    if (idx == int(n) - 1 && n >= 2) {
        const int last = int(n) - 1;
        set(last, lineSlope(inputs[last - 1], get(last - 1), inputs[last], get(last)));
    }
}
X2_HD inline bool rampHas(const U32* interpolators, U32 n, U32 mode) {
    for (U32 i = 0; i + 1 < n; ++i)
        if (interpolators[i] == mode) return true;
    return false;
}
// FloatRampControl_init: points sorted by the caller.
X2_HD inline void rampInit(FloatRamp& r, U32 n, const float* inputs, const float* outputs, const U32* interpolators) {
    n = n < RampMaxPoints ? n : RampMaxPoints;
    r.count = n;
    for (U32 i = 0; i < n; ++i) {
        r.inputs[i] = inputs[i];
        r.outputs[i] = outputs[i];
        r.interpolators[i] = interpolators[i];
        r.slopes[i] = 0.0f;
    }
    if (rampHas(r.interpolators, n, RampMonotoneCubic))
        monotoneSlopes(r.inputs, n, r.interpolators, [&](int i) { return r.outputs[i]; }, [&](int i, float v) { r.slopes[i] = v; });
}
X2_HD inline void rampInit(ColorRamp& r, U32 n, const float* inputs, const Color* outputs, const U32* interpolators, U32 space,
                           bool hueBlend = true) {
    n = n < RampMaxPoints ? n : RampMaxPoints;
    r.count = n;
    r.space = space;
    r.hueBlend = hueBlend ? 1 : 0;
    for (U32 i = 0; i < n; ++i) {
        r.inputs[i] = inputs[i];
        r.outputs[i] = outputs[i];
        r.interpolators[i] = interpolators[i];
        r.slopes[i] = rgb(0);
    }
    if (rampHas(r.interpolators, n, RampMonotoneCubic)) {
        monotoneSlopes(r.inputs, n, r.interpolators, [&](int i) { return r.outputs[i].x; }, [&](int i, float v) { r.slopes[i].x = v; });
        monotoneSlopes(r.inputs, n, r.interpolators, [&](int i) { return r.outputs[i].y; }, [&](int i, float v) { r.slopes[i].y = v; });
        monotoneSlopes(r.inputs, n, r.interpolators, [&](int i) { return r.outputs[i].z; }, [&](int i, float v) { r.slopes[i].z = v; });
    }
    if ((r.space == RampHsv || r.space == RampHsl) && rampHas(r.interpolators, n, RampCatmullRom)) r.space = RampRgb;
    for (U32 i = 0; i < n; ++i)
        if (r.space == RampHsv) r.outputs[i] = rgbToHsv(r.outputs[i]);
        else if (r.space == RampHsl) r.outputs[i] = rgbToHsl(r.outputs[i]);
}
X2_HD inline void rampSpan(U32 n, const float* inputs, float t, int& left, int& right) {
    if (n == 0) {
        left = right = -1;
        return;
    }
    left = 0;
    right = int(n) - 1;
    if (n == 1) return;
    if (t < inputs[left]) {
        left = -1;
        return;
    }
    if (t > inputs[right]) {
        right = -1;
        return;
    }
    while (right - left > 1) {
        const int mid = (left + right) / 2;
        if (inputs[mid] > t) right = mid;
        else left = mid;
    }
}
X2_HD inline float catmullRom(float t, const float p[4]) {
    // 0.5 * [1 t t^2 t^3] * M * p, M's rows as in RampControl.ispc (row-vector Mat4f)
    const float t2 = t * t, t3 = t2 * t;
    const float c0 = 0.5f * (1 * 0.0f + t * -1.0f + t2 * 2.0f + t3 * -1.0f);
    const float c1 = 0.5f * (1 * 2.0f + t * 0.0f + t2 * -5.0f + t3 * 3.0f);
    const float c2 = 0.5f * (1 * 0.0f + t * 1.0f + t2 * 4.0f + t3 * -3.0f);
    const float c3 = 0.5f * (1 * 0.0f + t * 0.0f + t2 * -1.0f + t3 * 1.0f);
    return c0 * p[0] + c1 * p[1] + c2 * p[2] + c3 * p[3];
}
X2_HD inline float cubicHermite(float t, float x1, float x2, float y1, float y2, float s1, float s2) {
    const float H = x2 - x1, t2 = t * t, t3 = t2 * t;
    return (2.0f * t3 - 3.0f * t2 + 1.0f) * y1 + H * (t3 - 2.0f * t2 + t) * s1 + (-2.0f * t3 + 3.0f * t2) * y2 + H * (t3 - t2) * s2;
}
X2_HD inline void splineIntervals(int interval, U32 n, float& t, int iv[4]) {
    iv[1] = interval;
    iv[0] = interval == 0 ? iv[1] : interval - 1;
    if (interval == int(n) - 2) {
        iv[2] = interval + 1;
        iv[3] = iv[2];
    } else if (interval == int(n) - 1) {
        iv[2] = iv[1];
        iv[3] = iv[2];
        t = 0.f;
    } else {
        iv[2] = interval + 1;
        iv[3] = interval + 2;
    }
}
X2_HD inline float rampWeight(U32 mode, float t) {
    switch (mode) {
    case RampNone: return 0.0f;
    case RampLinear: return t;
    case RampExponentialUp: return t * t;
    case RampExponentialDown: {
        const float w = 1.0f - t;
        return 1.0f - w * w;
    }
    case RampSmooth: return sinf(t * HalfPi);
    default: return 0.0f;
    }
}
X2_HD inline float rampEval(const FloatRamp& r, float t) {
    if (r.count == 0) return 0.0f;
    int left, right;
    rampSpan(r.count, r.inputs, t, left, right);
    if (left == -1) return r.outputs[0];
    if (right == -1) return r.outputs[r.count - 1];
    const float span = r.inputs[right] - r.inputs[left];
    if (isZero(span)) return r.outputs[left];
    t = (t - r.inputs[left]) / span;
    const U32 mode = r.interpolators[left];
    if (mode == RampCatmullRom || mode == RampMonotoneCubic) {
        int iv[4];
        splineIntervals(left, r.count, t, iv);
        const float p[4] = {r.outputs[iv[0]], r.outputs[iv[1]], r.outputs[iv[2]], r.outputs[iv[3]]};
        if (mode == RampCatmullRom) return catmullRom(t, p);
        return cubicHermite(t, r.inputs[iv[1]], r.inputs[iv[2]], p[1], p[2], r.slopes[iv[1]], r.slopes[iv[2]]);
    }
    const float w = rampWeight(mode, t);
    return r.outputs[left] + w * (r.outputs[right] - r.outputs[left]);
}
// eval1D: the ramp's own space, before conversion back to RGB.
X2_HD inline Color rampEvalRaw(const ColorRamp& r, float t) {
    if (r.count == 0) return rgb(0);
    int left, right;
    rampSpan(r.count, r.inputs, t, left, right);
    if (left == -1) return r.outputs[0];
    if (right == -1) return r.outputs[r.count - 1];
    const float span = r.inputs[right] - r.inputs[left];
    if (isZero(span)) return r.outputs[left];
    t = (t - r.inputs[left]) / span;
    const U32 mode = r.interpolators[left];
    if (mode == RampCatmullRom || mode == RampMonotoneCubic) {
        int iv[4];
        splineIntervals(left, r.count, t, iv);
        if (mode == RampCatmullRom) {
            const float px[4] = {r.outputs[iv[0]].x, r.outputs[iv[1]].x, r.outputs[iv[2]].x, r.outputs[iv[3]].x};
            const float py[4] = {r.outputs[iv[0]].y, r.outputs[iv[1]].y, r.outputs[iv[2]].y, r.outputs[iv[3]].y};
            const float pz[4] = {r.outputs[iv[0]].z, r.outputs[iv[1]].z, r.outputs[iv[2]].z, r.outputs[iv[3]].z};
            return {catmullRom(t, px), catmullRom(t, py), catmullRom(t, pz)};
        }
        const float x1 = r.inputs[iv[1]], x2 = r.inputs[iv[2]];
        const Color a = r.outputs[iv[1]], b = r.outputs[iv[2]], sa = r.slopes[iv[1]], sb = r.slopes[iv[2]];
        return {cubicHermite(t, x1, x2, a.x, b.x, sa.x, sb.x), cubicHermite(t, x1, x2, a.y, b.y, sa.y, sb.y),
                cubicHermite(t, x1, x2, a.z, b.z, sa.z, sb.z)};
    }
    const float w = rampWeight(mode, t);
    Color lo = r.outputs[left], hi = r.outputs[right];
    if (r.hueBlend && (r.space == RampHsv || r.space == RampHsl)) {
        if ((lo.x + 1.f) - hi.x < 0.5f) lo.x += 1.f;
        else if ((hi.x + 1.f) - lo.x < 0.5f) hi.x += 1.f;
    }
    return lo + w * (hi - lo);
}
X2_HD inline Color rampToRgb(const ColorRamp& r, Color c) {
    return r.space == RampHsv ? hsvToRgb(c) : r.space == RampHsl ? hslToRgb(c) : c;
}
X2_HD inline Color rampEval(const ColorRamp& r, float t) { return rampToRgb(r, rampEvalRaw(r, t)); }
template <class Eval>
X2_HD inline auto ramp2D(float u, float v, U32 type, float input, Eval eval) -> decltype(eval(0.0f)) {
    switch (type) {
    case RampV: return eval(v);
    case RampU: return eval(u);
    case RampDiagonal: return eval(0.5f * (u + v));
    case RampRadial: return eval(0.5f * (1.0f + atan2f(u - 0.5f, v - 0.5f) / Pi));
    case RampCircular: {
        u -= 0.5f;
        v -= 0.5f;
        float value = u * u + v * v;
        value = value > Epsilon ? sqrtf(2.0f * value) : 0.0f;
        return eval(value);
    }
    case RampBox: return eval(2.0f * fmaxf(fabsf(u - 0.5f), fabsf(v - 0.5f)));
    case RampUxV: return eval(2.0f * fabsf(v - 0.5f)) * eval(2.0f * fabsf(u - 0.5f));
    case RampInput:
    default: return eval(input);
    }
}
X2_HD inline float rampEval2D(const FloatRamp& r, float u, float v, U32 type, float input) {
    if (type == RampFourCorner && r.count >= 4)
        return (1 - u) * (1 - v) * r.outputs[0] + u * (1 - v) * r.outputs[1] + (1 - u) * v * r.outputs[2] + u * v * r.outputs[3];
    return ramp2D(u, v, type, input, [&](float t) { return rampEval(r, t); });
}
X2_HD inline Color rampEval2D(const ColorRamp& r, float u, float v, U32 type, float input) {
    Color c;
    if (type == RampFourCorner && r.count >= 4)
        c = (1 - u) * (1 - v) * r.outputs[0] + u * (1 - v) * r.outputs[1] + (1 - u) * v * r.outputs[2] + u * v * r.outputs[3];
    else c = ramp2D(u, v, type, input, [&](float t) { return rampEvalRaw(r, t); });
    return rampToRgb(r, c);
}
X2_HD inline Color evalColorRamp(const ColorRamp& r, float t) { return rampEval(r, t); }
}}}
