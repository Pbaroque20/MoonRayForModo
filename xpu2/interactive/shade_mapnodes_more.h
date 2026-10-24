// Private XPU2 shading library, shared CPU/CUDA: more of MoonRay's maps (moonshine dso/map and dso/normalmap,
// moonray dso/map): AxisAngleMap, TransformNormalMap, TransformSpaceMap, RgbToLabMap, RandomMap, MultiChannelToFloatMap,
// LayerMap and LayerMap_v2, HairMap, HairColumnMap, HairColorPresetsMap, ToonMap, CurvatureMap, WireframeMap,
// DirectionalMap, DeformationMap, ProjectTriplanarUdimMap, ExtraAovMap, ListMap, DebugMap, DistortNormalMap and
// RandomNormalMap, as XPU runs them (their ISPC). MoonRay shades in render space (the camera's) and XPU2 in world
// space: a map's colour result keeps MoonRay's numbers (render-space values in render space), a normal map's result is
// a world normal. Included by shade_mapnodes.h before its dispatch. Derived from MoonRay Apache-2.0, Copyright
// 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
namespace xpu2 { namespace interactive { namespace shade {

//----------------------------------------------------------------------------
// Render space and the others (Xform.ispc, through render space as MoonRay's are).
X2_HD inline V3 renderPoint(const State& st, V3 p) { return st.worldToRender ? xformPoint(st.worldToRender, p) : p; }
X2_HD inline V3 renderVector(const State& st, V3 v) { return st.worldToRender ? xformVector(st.worldToRender, v) : v; }
X2_HD inline V3 renderNormal(const State& st, V3 n) { return worldToRenderNormal(st.worldToRender, n); }
// An affine 3x4 (rows, xformPoint's) inverted.
X2_HD inline void invertAffine(const float* m, float* out) {
    const float a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], i = m[10];
    const float A = e * i - f * h, B = f * g - d * i, C = d * h - e * g;
    const float det = a * A + b * B + c * C;
    const float r = det != 0.0f ? 1.0f / det : 0.0f;
    const float inv[9] = {A * r, (c * h - b * i) * r, (b * f - c * e) * r, B * r, (a * i - c * g) * r,
                          (c * d - a * f) * r, C * r, (b * g - a * h) * r, (a * e - b * d) * r};
    for (int row = 0; row < 3; ++row) {
        out[4 * row] = inv[3 * row];
        out[4 * row + 1] = inv[3 * row + 1];
        out[4 * row + 2] = inv[3 * row + 2];
        out[4 * row + 3] = -(inv[3 * row] * m[3] + inv[3 * row + 1] * m[7] + inv[3 * row + 2] * m[11]);
    }
}
// A point, vector or normal through a 3x4 (normals by its inverse transpose).
enum SpaceValueType : U32 { SpacePointType = 0, SpaceVectorType = 1, SpaceNormalType = 2 };
X2_HD inline V3 xformAs(const float* m, U32 type, V3 v) {
    if (!m) return v;
    if (type == SpacePointType) return xformPoint(m, v);
    if (type == SpaceVectorType) return xformVector(m, v);
    return worldToRenderNormal(m, v);
}
// 4x4 (row vectors, p' = p M) helpers for screen space.
X2_HD inline V3 xform4H(const float* m, V3 p) {
    const float x = p.x * m[0] + p.y * m[4] + p.z * m[8] + m[12], y = p.x * m[1] + p.y * m[5] + p.z * m[9] + m[13],
                z = p.x * m[2] + p.y * m[6] + p.z * m[10] + m[14], w = p.x * m[3] + p.y * m[7] + p.z * m[11] + m[15];
    return V3{x / w, y / w, z / w};
}
X2_HD inline V3 xform4Vector(const float* m, V3 v) {
    return V3{v.x * m[0] + v.y * m[4] + v.z * m[8], v.x * m[1] + v.y * m[5] + v.z * m[9], v.x * m[2] + v.y * m[6] + v.z * m[10]};
}
// transformNormal(Mat4f m, n): m's 3x3 times n (MoonRay passes the inverse of the point transform).
X2_HD inline V3 xform4Normal(const float* m, V3 n) {
    return V3{m[0] * n.x + m[1] * n.y + m[2] * n.z, m[4] * n.x + m[5] * n.y + m[6] * n.z, m[8] * n.x + m[9] * n.y + m[10] * n.z};
}

// MoonRay's ISPC getIndex (RandomMap, RandomNormalMap): a table index from a float and a seed. A negative index (which
// MoonRay reads before its table) wraps here.
X2_HD inline int randomTableIndex(float input, int tabSize, int seed, int tabMask) {
    int idx;
    if (int(ceilf(input)) < (2147483647 - seed) / tabSize) {
        idx = (int(input * float(tabSize)) + seed) % tabMask;
    } else {
        const float ip = floorf(input), fp = input - ip;
        const int highP = int(ip) % tabMask;
        idx = ((highP + int(fp * float(tabSize)) % tabMask) % tabMask + seed) % tabMask;
    }
    return idx < 0 ? idx + tabMask : idx;
}

//----------------------------------------------------------------------------
// AxisAngleMap: the input vector from its space into the axis's, turned about the axis (Mat4f_rotate, row vectors), then
// into the output space. Spaces render, camera (the active one: render space), world, object (the hit geometry's).
X2_HD inline V3 axisSpaceNormal(const State& st, U32 from, U32 to, V3 n) {
    // to render: the source's normal transform; from render: the destination's
    V3 r = n;
    if (from == SpaceWorld) r = renderNormal(st, n);
    else if (from == SpaceObject) r = renderNormal(st, renderToWorldNormal(st.worldToObject, n));
    if (to == SpaceWorld) return renderToWorldNormal(st.worldToRender, r);
    if (to == SpaceObject) return worldToRenderNormal(st.worldToObject, renderToWorldNormal(st.worldToRender, r));
    return r;
}
X2_HD inline V3 rotateRowVector(V3 v, V3 axis, float angle) {
    const float s = sinf(angle), c = cosf(angle);
    const V3 a = normalize(axis);
    const float t = 1.0f - c;
    const V3 r0{a.x * a.x * t + c, a.x * a.y * t + a.z * s, a.x * a.z * t - a.y * s};
    const V3 r1{a.y * a.x * t - a.z * s, a.y * a.y * t + c, a.y * a.z * t + a.x * s};
    const V3 r2{a.z * a.x * t + a.y * s, a.z * a.y * t - a.x * s, a.z * a.z * t + c};
    return r0 * v.x + r1 * v.y + r2 * v.z;
}
X2_HD inline Color sampleAxisAngle(const MapParams& P, const State& st) {
    using Q = MapAxisAngleParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    V3 v = P.c(X2_OFF(Q, input_vector));
    const float angle = P.f(X2_OFF(Q, angle)) * (Pi / 180.0f);
    v = axisSpaceNormal(st, U32(q.input_space), U32(q.axis_space), v);
    v = rotateRowVector(v, P.c(X2_OFF(Q, rotation_axis)), angle);
    return axisSpaceNormal(st, U32(q.axis_space), U32(q.output_space), v);
}

// TransformNormalMap: tangent to render (decoded when asked) or render to tangent (encoded), at the input's length, in
// the frame of N and dPds (render space).
X2_HD inline Color sampleTransformNormal(const MapParams& P, const State& st) {
    using Q = MapTransformNormalParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    V3 in = P.c(X2_OFF(Q, input_normal));
    float len = length(in);
    const Frame f = frame(renderNormal(st, st.N), normalize(renderVector(st, st.dPds)));
    if (q.transform == 0.0f) {
        if (q.decode_input_normal != 0.0f) {
            in = 2.0f * in - rgb(1.0f);
            len = length(in);
            in = in / len;
        }
        return len * normalize(f.x * in.x + f.y * in.y + f.z * in.z);
    }
    const V3 out = length(in) * normalize(V3{dot(f.x, in), dot(f.y, in), dot(f.z, in)});
    return out * 0.5f + rgb(0.5f);
}

// RgbToLabMap: sRGB (D65) to XYZ to CIE L*a*b*.
X2_HD inline Color sampleRgbToLab(Color c) {
    const float x = 0.4124564f * c.x + 0.3575761f * c.y + 0.1804375f * c.z, y = 0.2126729f * c.x + 0.7151522f * c.y + 0.0721750f * c.z,
                z = 0.0193339f * c.x + 0.1191920f * c.y + 0.9503041f * c.z;
    const float kE = .008856f, kK = 903.3f;
    auto f = [&](float v) { return v > kE ? float(pow(double(v), 1.0 / 3)) : (kK * v + 16) / 116; };
    const float fx = f(x / 0.950456f), fy = f(y / 1.0f), fz = f(z / 1.089058f);
    return Color{116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)};
}

// RandomMap: per channel (or the red one for all), the table at the input's index with the seed, scaled to the range.
X2_HD inline Color sampleRandom(const MapParams& P) {
    using Q = MapRandomParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* table = P.p + sizeof(Q) / sizeof(float);  // 2048 colours
    const Color in = P.c(X2_OFF(Q, input));
    const int seed = int(q.seed);
    Color r;
    if (q.monochrome != 0.0f) {
        const float v = table[3 * randomTableIndex(in.x, 2048, seed, 2047)];
        r = rgb(v);
    } else {
        r = Color{table[3 * randomTableIndex(in.x, 2048, seed + 0, 2047)], table[3 * randomTableIndex(in.y, 2048, seed + 1, 2047) + 1],
                  table[3 * randomTableIndex(in.z, 2048, seed + 2, 2047) + 2]};
    }
    return r * (q.output_max - q.output_min) + rgb(q.output_min);
}

// MultiChannelToFloatMap: the colour's nearest of seven colour axes (or black), weighted by the next nearest; the
// result only for the chosen axis and within the tolerance.
X2_HD inline Color sampleMultiChannelToFloat(const MapParams& P) {
    using Q = MapMultiChannelToFloatParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    Color in = P.c(X2_OFF(Q, input));
    in = Color{clampf(in.x, 0.f, 1.f), clampf(in.y, 0.f, 1.f), clampf(in.z, 0.f, 1.f)};
    const float tolerance = clampf(P.f(X2_OFF(Q, tolerance)), 0.f, 1.f);
    enum { R, G, B, C, M, Y, W, K };
    int category = K;
    Color result = rgb(0.f);
    auto dotc = [](Color a, Color b) { return a.x * b.x + a.y * b.y + a.z * b.z; };
    if (!isEqualColor(in, rgb(0.f))) {
        const Color axes[7] = {{1, 0, 0}, {0, 1, 0}, {0, 0, 1}, {0, 1, 1}, {1, 0, 1}, {1, 1, 0}, {1, 1, 1}};
        const float div[7] = {1, 1, 1, 2, 2, 2, 3};
        Color proj[7];
        float dist[7];
        for (int i = 0; i < 7; ++i) {
            proj[i] = (dotc(in, axes[i]) / div[i]) * axes[i];
            const Color d = in - proj[i];
            dist[i] = dotc(d, d);
        }
        float mn = 1.f, second = 1.f;
        for (int i = 0; i < 7; ++i) {
            if (dist[i] <= mn) {
                second = mn;
                mn = dist[i];
            } else if (dist[i] < second) {
                second = dist[i];
            }
        }
        if (!isZero(mn + second)) {
            const float weight = second / (mn + second);
            const int channel[7] = {0, 1, 2, 1, 0, 0, 0};
            for (int i = 0; i < 7; ++i) {
                if (!isEqual(mn, dist[i])) continue;
                const Color wp = weight * proj[i];
                result = rgb(channel[i] == 0 ? wp.x : channel[i] == 1 ? wp.y : wp.z);
                category = i;
                break;
            }
        }
    }
    if ((1.f - result.x) > tolerance) return rgb(0.f);
    return int(q.mode) == category && category != K ? result : rgb(0.f);
}

// LayerMap and LayerMap_v2: input A composited over input B by the mask and mode (v1's multiply leaves out the mask).
X2_HD inline Color sampleLayerMap(const MapParams& P, bool v2) {
    using Q = MapLayerParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float mask = saturate(P.f(X2_OFF(Q, mask)));
    const int mode = int(q.mode);
    if (mode == 0 || isZero(mask)) return P.c(X2_OFF(Q, input_B));
    if (mode == 1 && isOne(mask)) return P.c(X2_OFF(Q, input_A));
    const Color a = P.c(X2_OFF(Q, input_A)) * mask, b = P.c(X2_OFF(Q, input_B));
    const float A[3] = {a.x, a.y, a.z}, Bc[3] = {b.x, b.y, b.z};
    float res[3];
    const float m = mask;
    switch (mode) {
    case 1: return b * (1.0f - m) + a;
    case 2: return b + a;
    case 3: return b - a;
    case 4: return v2 ? b * (1.f - m) + a * b * m : b * (1.f - m) + a * b;
    case 5: return a + b - a * b;
    case 6: return b * (b * m + (2.f * a) * (rgb(1.f) - b)) + b * (1.f - m);
    case 7:
        for (int i = 0; i < 3; ++i)
            res[i] = Bc[i] < 0.5f ? 2.f * A[i] * Bc[i] + Bc[i] * (1.f - m) : m * 1.f - 2.f * (1.f - Bc[i]) * (m - A[i]) + Bc[i] * (1.f - m);
        return Color{res[0], res[1], res[2]};
    case 8: return Color{fminf(a.x, b.x * m), fminf(a.y, b.y * m), fminf(a.z, b.z * m)} + b * (1.f - m);
    case 9: return Color{fmaxf(a.x, b.x * m), fmaxf(a.y, b.y * m), fmaxf(a.z, b.z * m)} + b * (1.f - m);
    case 10:
        for (int i = 0; i < 3; ++i) {
            if (A[i] + Bc[i] * m >= m) {
                res[i] = m + Bc[i] * (1.f - m);
            } else {
                float tmp = 1.f - A[i] / m;
                if (!isZero(tmp)) tmp = Bc[i] * m / tmp;
                res[i] = tmp + Bc[i] * (1.f - m);
            }
        }
        return Color{res[0], res[1], res[2]};
    case 11:
        for (int i = 0; i < 3; ++i) {
            if (A[i] + Bc[i] * m <= m) {
                res[i] = Bc[i] * (1.f - m);
            } else {
                const float tmp = !isZero(A[i]) ? m * (A[i] + Bc[i] * m - m) / A[i] : 0.f;
                res[i] = tmp + Bc[i] * (1.f - m);
            }
        }
        return Color{res[0], res[1], res[2]};
    case 12:
        for (int i = 0; i < 3; ++i)
            res[i] = 2.f * A[i] < m ? 2.f * A[i] * Bc[i] + Bc[i] * (1.f - m)
                                    : float(double(m) - 2.0 * double(1.f - Bc[i]) * double(m - A[i]) + double(Bc[i] * (1.f - m)));
        return Color{res[0], res[1], res[2]};
    case 13:
        for (int i = 0; i < 3; ++i) {
            if (2.f * A[i] < m) {
                res[i] = 2.f * Bc[i] * A[i] + Bc[i] * Bc[i] * (m - 2.f * A[i]) + Bc[i] * (1.f - m);
            } else {
                float tmp = Bc[i] * m;
                if (tmp < 0.f) tmp = 0.f;
                res[i] = sqrtf(tmp) * (2.f * A[i] - m) + (2.f * tmp) * (m - A[i]) + Bc[i] * (1.f - m);
            }
        }
        return Color{res[0], res[1], res[2]};
    case 14: return a + b - 2.f * Color{fminf(a.x, b.x * m), fminf(a.y, b.y * m), fminf(a.z, b.z * m)};
    case 15: return (a + b * m - 2.f * a * b) + b * (1.f - m);
    default: return rgb(0.f);
    }
}

//----------------------------------------------------------------------------
// The hair maps.
X2_HD inline Color sampleHairMap(const MapParams& P, const State& st) {
    using Q = MapHairParams;
    float s = st.s;
    s = biasf(s, 1.0f - P.f(X2_OFF(Q, bias)));
    s = gainf(s, P.f(X2_OFF(Q, gain)));
    return (P.c(X2_OFF(Q, base_color)) * (1.0f - s) + P.c(X2_OFF(Q, tip_color)) * s) * P.c(X2_OFF(Q, column_uv_color));
}
// HairColumnMap: the strand's scatter_tag (required) and the hit's s; black for a tag of -1.
X2_HD inline Color sampleHairColumn(const State& st) {
    float v[3] = {0, 0, 0};
    primValue(st, primKey("scatter_tag", PrimFloat), v);
    if (isEqual(v[0], -1.f)) return rgb(0.f);
    return Color{v[0], st.s, 0.0f};
}
X2_HD inline Color sampleHairColorPresets(int c) {
    switch (c) {
    case 0: return Color{0.0008f, 0.0008f, 0.0007f};
    case 1: return Color{0.1669f, 0.1562f, 0.1502f};
    case 2: return Color{0.829f, 0.640525f, 0.418645f};
    case 3: return Color{0.5f, 0.392323f, 0.250527f};
    case 4: return Color{0.287f, 0.18693f, 0.09499f};
    case 5: return Color{0.50543f, 0.17491f, 0.07663f};
    case 6: return Color{0.6196f, 0.10853f, 0.04877f};
    case 7: return Color{0.3577f, 0.0866f, 0.0696f};
    case 8: return Color{0.3804f, 0.1175f, 0.056614f};
    case 9: return Color{0.1115f, 0.056614f, 0.036655f};
    case 10: return Color{0.1449f, 0.07382f, 0.05112f};
    case 11: return Color{0.05261f, 0.03341f, 0.01774f};
    case 12: return Color{0.1175f, 0.08513f, 0.0469f};
    case 13: return Color{0.4159f, 0.2555f, 0.157f};
    case 14: return Color{0.07806f, 0.05459f, 0.05459f};
    default: return rgb(0.0f);
    }
}

//----------------------------------------------------------------------------
// The polygon maps: a mesh hit is a polygon of three polyvertices (MoonRay's TriMesh), a curve a spline or line.
// ToonMap: outlines where the eye direction crosses the horizon of the normals around the hit (at the scaled St
// footprint), creases where those normals part by more than the threshold.
X2_HD inline void neighborNormals(const State& st, V3 N, V3 dNds, V3 dNdt, float scale, V3 (&n)[8]) {
    const float dsdx = st.dsdx * scale, dsdy = st.dsdy * scale, dtdx = st.dtdx * scale, dtdy = st.dtdy * scale;
    const V3 dndx = dsdx * dNds + dtdx * dNdt, dndy = dsdy * dNds + dtdy * dNdt;
    n[0] = normalize(N - dndx - dndy);
    n[1] = normalize(N + dndx - dndy);
    n[2] = normalize(N + dndx + dndy);
    n[3] = normalize(N - dndx + dndy);
    n[4] = normalize(N - dndx);
    n[5] = normalize(N - dndy);
    n[6] = normalize(N + dndx);
    n[7] = normalize(N + dndy);
}
X2_HD inline Color sampleToon(const MapParams& P, const State& st) {
    using Q = MapToonParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const Color fill = P.c(X2_OFF(Q, fill_color));
    if (st.curve) return fill;
    const Color outline = P.c(X2_OFF(Q, outline_color)), crease = P.c(X2_OFF(Q, crease_color));
    const float outlineThreshold = P.f(X2_OFF(Q, outline_threshold));
    const float creaseThreshold = cosf(P.f(X2_OFF(Q, crease_threshold)) * Pi / 180.f);
    const float outlineScale = P.f(X2_OFF(Q, outline_scale)), creaseScale = P.f(X2_OFF(Q, crease_scale));
    const V3 N = renderNormal(st, st.N), dNds = renderNormal(st, st.dNds), dNdt = renderNormal(st, st.dNdt);
    V3 n[8];
    auto isOutline = [&]() {
        const V3 e = normalize(renderPoint(st, st.P));
        return dot(e, n[0]) * dot(e, n[2]) <= outlineThreshold || dot(e, n[1]) * dot(e, n[3]) <= outlineThreshold ||
               dot(e, n[4]) * dot(e, n[6]) <= outlineThreshold || dot(e, n[5]) * dot(e, n[7]) <= outlineThreshold;
    };
    auto isCrease = [&]() {
        return dot(n[0], n[2]) <= creaseThreshold || dot(n[1], n[3]) <= creaseThreshold || dot(n[4], n[6]) <= creaseThreshold ||
               dot(n[5], n[7]) <= creaseThreshold;
    };
    switch (int(q.mode)) {
    case 0:
        neighborNormals(st, N, dNds, dNdt, outlineScale, n);
        return isOutline() ? outline : fill;
    case 1:
        neighborNormals(st, N, dNds, dNdt, creaseScale, n);
        return isCrease() ? crease : fill;
    default:
        neighborNormals(st, N, dNds, dNdt, outlineScale, n);
        if (isOutline()) return outline;
        neighborNormals(st, N, dNds, dNdt, creaseScale, n);
        return isCrease() ? crease : fill;
    }
}
// CurvatureMap: how the St footprint's quad grows when its corners move along their normals.
X2_HD inline Color sampleCurvature(const MapParams& P, const State& st) {
    using Q = MapCurvatureParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    if (st.curve) return rgb(1.0f);
    const V3 Pr = renderPoint(st, st.P), N = renderNormal(st, st.N);
    const V3 dpds = float(0.5 * double(st.dsdx)) * renderVector(st, st.dPds), dpdt = float(0.5 * double(st.dtdy)) * renderVector(st, st.dPdt);
    const V3 p[4] = {Pr - dpds - dpdt, Pr + dpds - dpdt, Pr + dpds + dpdt, Pr - dpds + dpdt};
    const V3 dnds = float(0.5 * double(st.dsdx)) * renderNormal(st, st.dNds), dndt = float(0.5 * double(st.dtdy)) * renderNormal(st, st.dNdt);
    const V3 n[4] = {normalize(N - dnds - dndt), normalize(N + dnds - dndt), normalize(N + dnds + dndt), normalize(N - dnds + dndt)};
    auto area = [](const V3* v) { return length(cross(v[1] - v[0], v[3] - v[0])); };
    V3 ext[4];
    for (int i = 0; i < 4; ++i) ext[i] = p[i] + n[i];
    const float preA = area(p), postA = area(ext);
    const float ratio = preA > Epsilon ? postA / preA : 0.0f;
    float convex = clampf((ratio - 1.0f) * q.scale, 0.0f, 1.0f), concave = clampf((1.0f - ratio) * q.scale, 0.0f, 1.0f);
    if (q.power != 1.0f) {
        convex = powf(convex, q.power);
        concave = powf(concave, q.power);
    }
    if (q.invert != 0.0f) {
        concave = 1.0f - concave;
        convex = 1.0f - convex;
    }
    switch (int(q.mode)) {
    case 0: return rgb(convex);
    case 1: return rgb(concave);
    case 2: return rgb(((concave - convex) * 0.5f) + 0.5f);
    default: return Color{concave, convex, ((concave - convex) * 0.5f) + 0.5f};
    }
}
// WireframeMap: the line colour within the line's thickness of the polygon's edges (or on a curve), else the fill.
X2_HD inline Color sampleWireframe(const MapParams& P, const State& st) {
    using Q = MapWireframeParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const Color fill = q.fill_color, line = q.line_color;
    if (st.curve) return line;
    const float thickness = q.line_width * 0.5f;
    const V3 dpdx = renderVector(st, statedPdx(st)), dpdy = renderVector(st, statedPdy(st));
    const V3 Pr = renderPoint(st, st.P);
    const V3 I = normalize(Pr);
    const float pwXSq = lengthSqr(dpdx - dot(I, dpdx) * I), pwYSq = lengthSqr(dpdy - dot(I, dpdy) * I);
    const float pw = (sqrtf(pwXSq) + sqrtf(pwYSq)) * .5f;
    float t = thickness + thickness * .5f;
    if (q.raster != 0.0f) t = pw * q.line_width;
    const float tSq = t * t;
    const V3 v[3] = {renderPoint(st, st.pa), renderPoint(st, st.pb), renderPoint(st, st.pc)};
    for (int i1 = 0; i1 < 3; ++i1) {
        const int i0 = i1 == 0 ? 2 : i1 - 1;
        const V3 edge = v[i1] - v[i0], dir = Pr - v[i0];
        if (lengthSqr(cross(edge, dir)) < tSq * lengthSqr(edge)) return line;
    }
    return fill;
}

//----------------------------------------------------------------------------
// DeformationMap: the stretch of the surface's St partials against ref_P's (required), or the warning (or fatal)
// colour where either pair is degenerate.
X2_HD inline Color sampleDeformation(const MapParams& P, const State& st) {
    using Q = MapDeformationParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* prep = P.p + sizeof(Q) / sizeof(float);  // the fatal colour
    const Color fatal{prep[0], prep[1], prep[2]};
    const V3 cs = renderVector(st, st.dPds), ct = renderVector(st, st.dPdt);
    V3 curZ = cross(cs, ct);
    const float lc = length(curZ);
    if (isZero(lc)) return q.use_warning_color != 0.0f ? P.c(X2_OFF(Q, warning_color)) : fatal;
    curZ = curZ / lc;
    const V3 curX = normalize(cs), curY = normalize(cross(curZ, curX));
    float ds[3] = {0, 0, 0}, dt[3] = {0, 0, 0};
    primPartials(st, primKey("ref_P", PrimVec3f), ds, dt);
    const V3 rs{ds[0], ds[1], ds[2]}, rt{dt[0], dt[1], dt[2]};
    V3 refZ = cross(rs, rt);
    const float lr = length(refZ);
    if (isZero(lr)) return q.use_warning_color != 0.0f ? P.c(X2_OFF(Q, warning_color)) : fatal;
    refZ = refZ / lr;
    const V3 refX = normalize(rs), refY = normalize(cross(refZ, refX));
    const float defS = fabsf(dot(cs, curX) / dot(rs, refX)), defT = fabsf(dot(ct, curY) / dot(rt, refY));
    const float defAvg = length(cross(cs, ct)) / length(cross(rs, rt));
    switch (int(q.output_mode)) {
    case 0: return Color{defS, defT, defAvg};
    case 1: return rgb(defS);
    case 2: return rgb(defT);
    default: return rgb(defAvg);
    }
}

// SHADER_DATA_getRefN: ref_N, else the normal of ref_P's partials (across a curve, with the view direction); flipped
// when leaving the surface. False when neither gives one.
X2_HD inline bool referenceNormal(const State& st, V3& out) {
    float v[3];
    out = V3{0, 0, 0};
    if (primValue(st, primKey("ref_N", PrimVec3f), v)) {
        out = V3{v[0], v[1], v[2]};
    } else if (primProvided(st, primKey("ref_P", PrimVec3f))) {
        float ds[3] = {0, 0, 0}, dt[3] = {0, 0, 0};
        primPartials(st, primKey("ref_P", PrimVec3f), ds, dt);
        V3 a{ds[0], ds[1], ds[2]}, b{dt[0], dt[1], dt[2]};
        if (isZero(lengthSqr(a))) return false;
        a = normalize(a);
        if (isZero(lengthSqr(b))) b = cross(a, cross(a, normalize(renderVector(st, st.wo))));
        const V3 n = cross(a, normalize(b));
        if (isZero(lengthSqr(n))) return false;
        out = n;
    } else {
        return false;
    }
    if (!st.entering) out = -out;
    return true;
}

// DirectionalMap: how the normal (a normal map's unadapted, ref_N, or N) faces a direction (the object's axis, toward
// its origin, the viewer, or a world direction), as a cosine or linear falloff, biased and smoothstepped, between two
// colours. Its object: its own, else the hit geometry. All in render space.
X2_HD inline Color sampleDirectional(const MapParams& P, const State& st, const MapNodeHeader& h) {
    using Q = MapDirectionalParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* prep = P.p + sizeof(Q) / sizeof(float);  // world-to-object (12), the input normal map's register
    const float* object = h.object ? prep : st.worldToObject;
    float objectInverse[12];
    const float* toWorld = nullptr;
    if (object) {
        invertAffine(object, objectInverse);
        toWorld = objectInverse;
    }
    const int normalReg = int(prep[12]);
    V3 prime{0, 0, 0};
    switch (int(q.prime_direction)) {
    case 2: {  // the object's axis
        const V3 axes[6] = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {0, 0, 1}, {0, 0, -1}};
        const int a = int(q.object_axis);
        prime = normalize(renderVector(st, xformAs(toWorld, SpaceVectorType, axes[a < 0 || a > 5 ? 0 : a])));
        break;
    }
    case 3: {  // toward the object's origin
        V3 local;
        if (q.use_reference_space != 0.0f) {
            float v[3] = {0, 0, 0};
            primValue(st, primKey("ref_P", PrimVec3f), v);
            local = V3{v[0], v[1], v[2]};
        } else {
            local = xformAs(object, SpacePointType, st.P);
        }
        prime = renderVector(st, xformAs(toWorld, SpaceVectorType, -local));
        if (lengthSqr(prime) > 0.0f) prime = normalize(prime);
        break;
    }
    case 0: prime = renderVector(st, st.wo); break;  // the observer
    default:
        prime = renderVector(st, P.c(X2_OFF(Q, custom_direction)));
        if (lengthSqr(prime) > 0.0f) prime = normalize(prime);
        break;
    }
    V3 N;
    if (q.use_reference_space != 0.0f) {
        V3 refN;
        referenceNormal(st, refN);
        N = renderNormal(st, xformAs(toWorld, SpaceNormalType, refN));
    } else if (normalReg >= 0) {
        // evalNormal's unadapted normal: the map's, normalized and dialled toward N (N for a zero dial or value)
        const V3 value = P.regs[normalReg];
        const float dial = q.input_normal_dial;
        V3 unadapted = st.N;
        if (!isZero(dial) && finite3(value) && !(isZero(value.x) && isZero(value.y) && isZero(value.z))) {
            unadapted = normalize(value);
            if (dial != 1.0f) unadapted = normalize(st.N + (unadapted - st.N) * saturate(dial));
        }
        N = renderNormal(st, unadapted);
    } else {
        N = renderNormal(st, st.N);
    }
    float cosTheta = dot(N, prime);
    if (int(q.clamping_behavior) == 1) cosTheta = fabsf(cosTheta);
    cosTheta = saturate(cosTheta);
    if (int(q.polarity) == 0) cosTheta = float(1.0 - double(cosTheta));
    float falloff = int(q.falloff_type) == 0 ? cosTheta : 1.0f - dwAcos(cosTheta) / (Pi * 0.5f);
    falloff = biasf(falloff, saturate(P.f(X2_OFF(Q, bias))));
    if (q.use_smoothstep != 0.0f) falloff = noiseSmoothStep(falloff, P.f(X2_OFF(Q, smoothstep_start)), P.f(X2_OFF(Q, smoothstep_end)));
    return lerp(P.c(X2_OFF(Q, color_a)), P.c(X2_OFF(Q, color_b)), falloff);
}

//----------------------------------------------------------------------------
// TransformSpaceMap: a point, vector or normal from one space to another (render, camera, world, screen, object,
// tangent and the instance spaces, which without instancing leave it as it is). Prepared on the host: render-to-world
// and back (3x4 each), render to camera and back (the map's camera, else the active one: identity), render to screen
// and back (4x4 each), and the map's object's world-to-object (12; zero without one).
struct TransformSpacePrep {
    float r2w[12], w2r[12], r2c[12], c2r[12], r2s[16], s2r[16], w2o[12];
};
X2_HD inline V3 tsmToRender(const State& st, const TransformSpacePrep& x, const MapNodeHeader& h, U32 space, U32 type, V3 v) {
    switch (space) {
    case 0: return v;
    case 1: return xformAs(x.c2r, type, v);
    case 2: return xformAs(x.w2r, type, v);
    case 3:
        if (type == SpacePointType) return xform4H(x.s2r, v);
        if (type == SpaceVectorType) return xform4Vector(x.s2r, v);
        return xform4Normal(x.r2s, v);
    case 4: {
        const float* w2o = h.object ? x.w2o : st.worldToObject;
        float o2w[12];
        if (w2o) invertAffine(w2o, o2w);
        return xformAs(x.w2r, type, w2o ? xformAs(o2w, type, v) : v);
    }
    default: return v;
    }
}
X2_HD inline V3 tsmFromRender(const State& st, const TransformSpacePrep& x, const MapNodeHeader& h, U32 space, U32 type, V3 v) {
    switch (space) {
    case 0: return v;
    case 1: return xformAs(x.r2c, type, v);
    case 2: return xformAs(x.r2w, type, v);
    case 3:
        if (type == SpacePointType) return xform4H(x.r2s, v);
        if (type == SpaceVectorType) return xform4Vector(x.r2s, v);
        return xform4Normal(x.s2r, v);
    case 4: {
        const float* w2o = h.object ? x.w2o : st.worldToObject;
        const V3 w = xformAs(x.r2w, type, v);
        return w2o ? xformAs(w2o, type, w) : w;
    }
    default: return v;
    }
}
X2_HD inline Color sampleTransformSpace(const MapParams& P, const State& st, const MapNodeHeader& h) {
    using Q = MapTransformSpaceParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const TransformSpacePrep& x = *reinterpret_cast<const TransformSpacePrep*>(P.p + sizeof(Q) / sizeof(float));
    const V3 in = P.c(X2_OFF(Q, input));
    const U32 type = U32(q.input_type), from = U32(q.from_space), to = U32(q.to_space);
    const U32 Tangent = 5, InstanceObject = 6, InstanceOffset = 7;
    if (from < Tangent && to < Tangent) return tsmFromRender(st, x, h, to, type, tsmToRender(st, x, h, from, type, in));
    // localToRender: the frame of N (Ng without ref_N, as MoonRay's), and dPds (the dPds attribute when given).
    auto localToRender = [&](V3 v) {
        const V3 n = primProvided(st, primKey("ref_N", PrimVec3f)) ? renderNormal(st, st.N) : renderNormal(st, st.Ng);
        float a[3];
        V3 dPds = renderVector(st, st.dPds);
        if (primValue(st, primKey("dPds", PrimVec3f), a)) dPds = V3{a[0], a[1], a[2]};
        const Frame f = frame(normalize(n), normalize(dPds));
        return localToGlobal(f, v);
    };
    if (from == Tangent && to == 0) return localToRender(in);
    V3 world;
    if (from == Tangent) world = tsmFromRender(st, x, h, 2, type, localToRender(in));
    else if (from == InstanceObject || from >= InstanceOffset || from == 2) world = in;
    else world = tsmFromRender(st, x, h, 2, type, tsmToRender(st, x, h, from, type, in));
    if (to == Tangent) {
        // worldToRefTangent: into the frame of ref_N and ref_P's s partial (the ref_dPds attribute when given)
        float a[3], ds[3] = {0, 0, 0}, dt[3];
        V3 dRefPds;
        if (primValue(st, primKey("ref_dPds", PrimVec3f), a)) {
            dRefPds = V3{a[0], a[1], a[2]};
        } else {
            primPartials(st, primKey("ref_P", PrimVec3f), ds, dt);
            dRefPds = V3{ds[0], ds[1], ds[2]};
        }
        V3 refN;
        referenceNormal(st, refN);
        const Frame f = frame(normalize(refN), normalize(dRefPds));
        return globalToLocal(f, world);
    }
    if (to == InstanceObject) return in;  // as MoonRay's: the input, not its world value
    if (to == 2 || to >= InstanceOffset) return world;
    return tsmFromRender(st, x, h, to, type, tsmToRender(st, x, h, 2, type, world));
}

//----------------------------------------------------------------------------
// ProjectTriplanarUdimMap: UVs (UDIM 1001 to 1003 for the X, Y and Z faces) of P on the projector's axis its normal is
// most along, each face's 2D transform applied. Prepared: the projector's world-to-object and normal transform (as
// the projection maps'), then the three faces' Xform3f (12 each: vx, vy, vz, p).
X2_HD inline float remapToZeroOne(float value) {
    const float r = fmodf(value, 1.0f);
    return r < 0 ? r + 1.0f : r;
}
X2_HD inline V3 xform3fPoint(const float* x, V3 p) {
    return V3{p.x * x[0] + p.y * x[3] + p.z * x[6] + x[9], p.x * x[1] + p.y * x[4] + p.z * x[7] + x[10],
              p.x * x[2] + p.y * x[5] + p.z * x[8] + x[11]};
}
X2_HD inline Color sampleTriplanarUdim(const MapParams& P, const State& st, const MapNodeHeader& h) {
    using Q = MapProjectTriplanarUdimParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* prep = P.p + sizeof(Q) / sizeof(float);
    if (!h.object) return rgb(0.0f);  // no projector
    const float* toObject = prep;
    const float* normalToObject = prep + 12;
    V3 pos, normal;
    if (q.use_reference_space != 0.0f) {
        float v[3] = {0, 0, 0};
        primValue(st, primKey("ref_P", PrimVec3f), v);
        pos = xformPoint(toObject, V3{v[0], v[1], v[2]});
        V3 refN;
        if (!referenceNormal(st, refN)) return rgb(0.0f);
        normal = xformVector(normalToObject, refN);
        if (!st.entering) normal = -normal;
    } else {
        pos = xformPoint(toObject, st.P);
        normal = xformVector(normalToObject, st.N);
    }
    normal = normalize(normal);
    const V3 an{fabsf(normal.x), fabsf(normal.y), fabsf(normal.z)};
    int axis = 0;
    if (an.y > an.x) axis = 1;
    if (an.z > an.y && an.z > an.x) axis = 2;
    const bool correct = q.use_correct_uv != 0.0f;
    V3 uv{0, 0, 0};
    const float* xf = prep + 24 + 12 * axis;
    if (axis == 2) {
        uv = V3{pos.x + 0.5f, pos.y + 0.5f, 0.0f};
        if (correct) uv.x = 1.0f - uv.x;
    } else if (axis == 1) {
        uv = V3{pos.x + 0.5f, pos.z + 0.5f, 0.0f};
        if (correct) uv.y = 1.0f - uv.y;
    } else {
        uv = V3{pos.z + 0.5f, pos.y + 0.5f, 0.0f};
        if (correct) uv.x = 1.0f - uv.x;
    }
    uv = xform3fPoint(xf, uv);
    uv.x = remapToZeroOne(uv.x);
    uv.y = remapToZeroOne(uv.y);
    if (axis == 2) uv.x += 2.0f - Epsilon;
    else if (axis == 1) uv.x += 1.0f - Epsilon;
    return uv;
}

//----------------------------------------------------------------------------
// DebugMap: a state value (render space) or a primitive attribute, optionally checkered.
X2_HD inline Color debugChecker(V3 v, bool checker, int dims) {
    Color s{v.x, v.y, dims == 2 ? 0.0f : v.z};
    if (checker) {
        const int a = int(v.x * 16.0f) % 2, b = int(v.y * 16.0f) % 2, c = dims == 2 ? 0 : int(v.z * 16.0f) % 2;
        if (((a + b) + c) % 2 == 0) s = s * 0.5f;
    }
    return s;
}
X2_HD inline Color sampleDebug(const MapParams& P, const State& st, const MapNodeHeader& h) {
    using Q = MapDebugParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* prep = P.p + sizeof(Q) / sizeof(float);  // the primitive attribute's key, the input normal's binding (1: bound)
    const bool checker = q.checkerboard != 0.0f;
    switch (int(q.map_type)) {
    case 2: {  // the input normal (evalNormal of a bound value, else N)
        V3 n = st.N;
        const float dial = q.input_normal_dial;
        if (!isZero(dial) && prep[1] != 0.0f) {
            V3 value = P.c(X2_OFF(Q, input_normal));
            bool ok = finite3(value) && !(isZero(value.x) && isZero(value.y) && isZero(value.z));
            if (ok && int(q.input_normal_space) == 0) {
                value = 2.0f * value - rgb(1.0f);
                if (value.z < 0.f) ok = false;
                else value = localToGlobal(frame(st.N, normalize(st.dPds)), value);
            } else if (ok) {
                value = renderToWorldNormal(st.worldToRender, value);
            }
            if (ok) {
                V3 r = normalize(value);
                if (dial != 1.0f) r = normalize(st.N + (r - st.N) * saturate(dial));
                n = adaptNormal(st, r);
            }
        }
        return debugChecker(renderNormal(st, n), checker, 3);
    }
    case 1: return debugChecker(V3{st.s, st.t, 0.0f}, checker, 2);
    case 0: return debugChecker(renderPoint(st, st.P), checker, 3);
    case 3: return debugChecker(renderNormal(st, st.Ng), checker, 3);
    case 4: return debugChecker(renderVector(st, st.dPds), checker, 3);
    case 5: return debugChecker(renderVector(st, st.dPdt), checker, 3);
    case 6: {
        const U32 key = *reinterpret_cast<const U32*>(&prep[0]);
        float v[3] = {0, 0, 0};
        primValue(st, key, v);
        const int type = int(q.primitive_attribute_type);
        if (type == 0) return rgb(v[0]);
        return debugChecker(V3{v[0], v[1], v[2]}, checker, type == 1 ? 2 : 3);
    }
    default: return rgb(0.0f);
    }
}

//----------------------------------------------------------------------------
// The normal maps. DistortNormalMap: the input normal map's normal (else N) turned about dPds and dPdt (or the input
// vectors, render space) by two simplex noises of the position (in render space unless St, input coordinates or ref_P:
// MoonRay passes it no transform), kept above the horizon of the normal. Prepared: the input normal map's register,
// the two noises' table offsets, then the tables.
X2_HD inline V3 rotateAbout(V3 v, V3 axis, float theta) {
    const float st = sinf(theta), ct = cosf(theta);
    return ct * v + st * cross(axis, v) + dot(axis, v) * (1.f - ct) * axis;
}
X2_HD inline Color sampleDistortNormal(const MapParams& P, const State& st) {
    using Q = MapDistortNormalParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* prep = P.p + sizeof(Q) / sizeof(float);
    const int normalReg = int(prep[0]);
    V3 n = normalReg >= 0 ? V3(P.regs[normalReg]) : st.N;
    V3 u = st.dPds, v = st.dPdt;
    if (q.use_input_vectors != 0.0f) {
        u = renderToWorldVector(st.worldToRender, P.c(X2_OFF(Q, input_U)));
        v = renderToWorldVector(st.worldToRender, P.c(X2_OFF(Q, input_V)));
    }
    if ((isZero(u.x) && isZero(u.y) && isZero(u.z)) || (isZero(v.x) && isZero(v.y) && isZero(v.z))) return n;
    u = normalize(u);
    v = normalize(v);
    const int space = int(q.noise_space);
    V3 pos;
    if (space == int(SpaceTexture)) {
        pos = V3{st.s, st.t, 0.f};
    } else if (space == int(SpaceReference)) {
        float r[3] = {0, 0, 0};
        primValue(st, primKey("ref_P", PrimVec3f), r);
        pos = V3{r[0], r[1], r[2]};
    } else if (space == 7) {
        pos = P.c(X2_OFF(Q, input_texture_coordinates));
    } else {
        pos = renderPoint(st, st.P);
    }
    NoiseTable tu, tv;
    tu.perm = P.p + U32(prep[1]);
    tv.perm = P.p + U32(prep[2]);
    float dummy[3];
    const V3 fu = q.frequency_U, fv = q.frequency_V;
    const float pu[3] = {fu.x * pos.x, fu.y * pos.y, fu.z * pos.z}, pv[3] = {fv.x * pos.x, fv.y * pos.y, fv.z * pos.z};
    float thetaU = simplex3D(tu, pu, 0.0f, dummy), thetaV = simplex3D(tv, pv, 0.0f, dummy);
    thetaU = fmaxf(-1.f, fminf(1.f, thetaU * q.amplitude_U)) * 1.57079632f;
    thetaV = fmaxf(-1.f, fminf(1.f, thetaV * q.amplitude_V)) * 1.57079632f;
    V3 result = rotateAbout(n, u, thetaU);
    result = rotateAbout(result, v, thetaV);
    const float ndr = dot(result, n);
    if (ndr < Epsilon) result = normalize(result + (Epsilon - ndr) * n);
    return result;
}
// RandomNormalMap: a normal about N (in the frame of N and dPds) from two table values at the input's red.
X2_HD inline Color sampleRandomNormal(const MapParams& P, const State& st) {
    using Q = MapRandomNormalParams;
    const Q& q = *reinterpret_cast<const Q*>(P.p);
    const float* table = P.p + sizeof(Q) / sizeof(float);
    const Color in = P.c(X2_OFF(Q, input));
    const int seed = int(q.seed);
    const float u1 = table[randomTableIndex(in.x, 2048, seed, 2047)], u2 = table[randomTableIndex(in.x * 2.5f, 2048, seed, 2047)];
    const float phi = TwoPi * u2;
    const V3 normal = normalize(V3{cosf(phi) * u1, sinf(phi) * u1, 1.f});
    return localToGlobal(frame(st.N, normalize(st.dPds)), normal);
}
}}}
