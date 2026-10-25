// Private XPU2 shading library, shared CPU/CUDA: the shading state a material
// sees at a hit (MoonRay shading::State / Intersection, the parts XPU2's
// geometry provides), and Intersection_adaptNormal. Derived from MoonRay
// Apache-2.0 (geom/IntersectionInit.cc, shading/ispc/Intersection.ispc),
// Copyright 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "shade_lobes.h"
namespace xpu2 { namespace interactive { namespace shade {

// A mesh's primitive attribute (geom/PrimitiveUserData): its key (a hash of its name and type),
// its values a component count each, its rate (UserData's: constant 1, uniform 3, vertex 4, varying 5,
// face varying 6) and where its values start in the mesh's attribute data.
enum PrimType : U32 { PrimFloat = 0, PrimVec2f = 1, PrimVec3f = 2, PrimRgb = 3, PrimInt = 4 };
enum PrimRate : U32 { PrimConstant = 1, PrimUniform = 3, PrimVertex = 4, PrimVarying = 5, PrimFaceVarying = 6 };
struct PrimAttr {
    U32 key, components, rate, offset;
};
// FNV-1a of the attribute's name, then its type: TypedAttributeKey<T>(name) as one word.
X2_HD inline U32 primKey(const char* name, U32 type) {
    U32 h = 2166136261u;
    for (const char* c = name; *c; ++c) h = (h ^ U32(static_cast<unsigned char>(*c))) * 16777619u;
    return (h ^ (type + 1u)) * 16777619u;
}

// Intersection::PathType
enum PathType : U32 { PathPrimary = 0, PathIndirectMirror, PathIndirectGlossy, PathIndirectDiffuse };

// A ray's differentials (mcrt_common RayDifferential): its auxiliary rays' origins and directions as
// offsets from its own origin and direction.
struct RayDiff {
    V3 dOx{0, 0, 0}, dOy{0, 0, 0}, dDx{0, 0, 0}, dDy{0, 0, 0};
    U32 valid = 0;
};
struct State {
    // N and Ng face the viewer (initIntersectionPhase1 flips both when the ray
    // leaves the surface); dPds and dPdt are never flipped.
    V3 P, Ng, N, dPds, dPdt, wo;
    float s = 0, t = 0;                      // St, the surface texture coordinates
    float dsdx = 0, dsdy = 0, dtdx = 0, dtdy = 0;
    V3 dPdx{0, 0, 0}, dPdy{0, 0, 0};         // ray differentials at P
    V3 dNdx{0, 0, 0}, dNdy{0, 0, 0};
    // computeIntersectCurvature: the shading normal's St partials from the triangle's vertex normals (zero without
    // normals and on curves; MoonRay does not flip them with N); and the hit triangle's corners (its polyvertices).
    V3 dNds{0, 0, 0}, dNdt{0, 0, 0};
    V3 pa{0, 0, 0}, pb{0, 0, 0}, pc{0, 0, 0}, pd{0, 0, 0};
    U32 polyCount = 3;  // the polyvertices: a QuadMesh face's four (pa to pd), else a triangle's three
    // The hit's motion (StandardAttributes::sMotion, Mesh::computeMotion): its velocity in world units a shutter
    // interval, zero for anything still.
    V3 motion{0, 0, 0};
    // MOONRAY_MODO_TOON_TERMINATOR: on a toon material's mesh, the smooth surface above the flat face at P
    // (Intersection::mModoSmoothOffset); zero elsewhere.
    V3 modoSmoothOffset{0, 0, 0};
    RayDiff incoming;        // the ray's differentials (set before shading; a camera ray's are its own)
    bool diffValid = false;  // whether dPdx and dPdy came from differentials
    float minRoughness[2] = {0, 0};
    float mediumIor = 1.0f;
    U32 geom = 0, prim = 0, pathType = PathPrimary;
    U32 rayLobe = 0;  // the type of the lobe whose sample the ray is (0 for a camera ray): RaySwitchMaterial's choice
    // Intersection::transferAndComputeDerivatives' textureDiffScale: the texture derivatives' factor (texture_blur).
    float textureDiffScale = 1.0f;
    // The pixel's own sample count under a pixel sample map (0: the frame's), which scales a camera ray's differentials.
    U32 pixelSamples = 0;
    float u = 0, v = 0;                      // barycentrics of the hit triangle
    bool entering = true, causticPath = false, subsurfaceAllowed = true, useAdaptNormal = true;
    bool displacement = false;  // a displacement shader's state (Intersection::initDisplacement)
    // Shading spaces (3x4 row-major, null for identity): MoonRay's render space is the camera's space
    // at the first motion step; object space is the hit geometry's.
    const float* worldToRender = nullptr;
    const float* worldToObject = nullptr;
    // The hit triangle's vertices and the mesh's primitive attributes. On a curve (curve: its curves::Basis, zero
    // on a mesh) prim is the span, u its parameter, ia its first control point, chain its curve and varying the
    // span's first varying value (CubicSpline's chain + span).
    U32 ia = 0, ib = 0, ic = 0;
    U32 curve = 0, chain = 0, varying = 0;
    const PrimAttr* prims = nullptr;
    const float* primData = nullptr;
    U32 primCount = 0;
    // computeStInverse: the hit triangle's st basis inverted, for its attributes' st derivatives (identity when degenerate).
    float stInv[4] = {1, 0, 0, 1};
};
X2_HD inline V3 xformVector(const float* m, V3 v) {
    return V3{m[0] * v.x + m[1] * v.y + m[2] * v.z, m[4] * v.x + m[5] * v.y + m[6] * v.z, m[8] * v.x + m[9] * v.y + m[10] * v.z};
}
// MoonRay shades in render space (the camera's), XPU2 in world space: a value MoonRay reads as a render-space
// normal (an RgbToNormalMap's colour) or vector (a toon specular's input vectors) comes into world space through
// world-to-render (st.worldToRender, null for identity): a normal by its linear part transposed (the inverse transpose
// of render-to-world), a vector by its inverse.
X2_HD inline V3 renderToWorldNormal(const float* m, V3 n) {
    if (!m) return n;
    return V3{m[0] * n.x + m[4] * n.y + m[8] * n.z, m[1] * n.x + m[5] * n.y + m[9] * n.z, m[2] * n.x + m[6] * n.y + m[10] * n.z};
}
// The other way: a world normal's components in render space (the inverse transpose of world-to-render).
X2_HD inline V3 worldToRenderNormal(const float* m, V3 n) {
    if (!m) return n;
    const float a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], i = m[10];
    const float A = e * i - f * h, B = f * g - d * i, C = d * h - e * g;
    const float det = a * A + b * B + c * C;
    if (det == 0.0f) return n;
    const float r = 1.0f / det;
    // (L^-1)^T n: the cofactor matrix over the determinant
    return V3{(A * n.x + B * n.y + C * n.z) * r, ((c * h - b * i) * n.x + (a * i - c * g) * n.y + (b * g - a * h) * n.z) * r,
              ((b * f - c * e) * n.x + (c * d - a * f) * n.y + (a * e - b * d) * n.z) * r};
}
X2_HD inline V3 renderToWorldVector(const float* m, V3 v) {
    if (!m) return v;
    const float a = m[0], b = m[1], c = m[2], d = m[4], e = m[5], f = m[6], g = m[8], h = m[9], i = m[10];
    const float A = e * i - f * h, B = f * g - d * i, C = d * h - e * g;
    const float det = a * A + b * B + c * C;
    if (det == 0.0f) return v;
    const float r = 1.0f / det;
    return V3{(A * v.x + (c * h - b * i) * v.y + (b * f - c * e) * v.z) * r, (B * v.x + (a * i - c * g) * v.y + (c * d - a * f) * v.z) * r,
              (C * v.x + (b * g - a * h) * v.y + (a * e - b * d) * v.z) * r};
}
// A curve's attribute at the hit (LineSegmentsInterpolator, CubicSplineInterpolator): a uniform value is its
// curve's; vertex values are a linear span's ends or a cubic span's four points by its basis; varying values a
// span's ends (on a linear curve, its vertices).
X2_CALL bool curvePrimValue(const State& st, const PrimAttr& a, float out[3]) {
    const U32 n = a.components;
    const float* d = st.primData + a.offset;
    const float u = st.u;
    switch (a.rate) {
    case PrimConstant:
        for (U32 k = 0; k < n; ++k) out[k] = d[k];
        return true;
    case PrimUniform:
        for (U32 k = 0; k < n; ++k) out[k] = d[st.chain * n + k];
        return true;
    case PrimVertex:
    case PrimVarying:
    case PrimFaceVarying:
        if (st.curve == 1 || a.rate != PrimVertex) {  // curves::BasisLinear, or a span's ends
            const U32 i0 = st.curve == 1 ? st.ia : st.varying;
            for (U32 k = 0; k < n; ++k) out[k] = (1.0f - u) * d[i0 * n + k] + u * d[(i0 + 1) * n + k];
        } else {
            const float s = 1.f - u;
            float w[4];
            if (st.curve == 3) {  // curves::BasisBspline (BSpline::evalWeights)
                const float oneSixth(1.0f / 6.0f);
                w[0] = oneSixth * s * s * s;
                w[1] = 0.5f * s * (s * u + 1.0f) + oneSixth;
                w[2] = 0.5f * u * (s * u + 1.0f) + oneSixth;
                w[3] = oneSixth * u * u * u;
            } else {  // BezierSpanChains::evalWeights
                w[0] = s * s * s;
                w[1] = 3.0f * s * s * u;
                w[2] = 3.0f * s * u * u;
                w[3] = u * u * u;
            }
            for (U32 k = 0; k < n; ++k)
                out[k] = w[0] * d[st.ia * n + k] + w[1] * d[(st.ia + 1) * n + k] + w[2] * d[(st.ia + 2) * n + k] +
                         w[3] * d[(st.ia + 3) * n + k];
        }
        return true;
    default: return false;
    }
}
// getd<T>Attributeds and getd<T>Attributedt (Mesh::computeDerivatives): an attribute's st derivatives over the hit
// triangle; false when the mesh has no such attribute. Curves' attribute derivatives are not ported (false).
X2_CALL bool primPartials(const State& st, U32 key, float ds[3], float dt[3]) {
    for (U32 i = 0; i < st.primCount; ++i) {
        const PrimAttr& a = st.prims[i];
        if (a.key != key) continue;
        if (st.curve) return false;
        const U32 n = a.components;
        const float* d = st.primData + a.offset;
        U32 i1 = 0, i2 = 0, i3 = 0;
        switch (a.rate) {
        case PrimConstant: break;
        case PrimUniform: i1 = i2 = i3 = st.prim; break;
        case PrimVertex:
        case PrimVarying:
            i1 = st.ia;
            i2 = st.ib;
            i3 = st.ic;
            break;
        case PrimFaceVarying:
            i1 = st.prim * 3;
            i2 = i1 + 1;
            i3 = i1 + 2;
            break;
        default: return false;
        }
        ds[0] = ds[1] = ds[2] = dt[0] = dt[1] = dt[2] = 0.0f;
        for (U32 k = 0; k < n; ++k) {
            const float df0 = d[i2 * n + k] - d[i1 * n + k], df1 = d[i3 * n + k] - d[i1 * n + k];
            ds[k] = st.stInv[0] * df0 + st.stInv[1] * df1;
            dt[k] = st.stInv[2] * df0 + st.stInv[3] * df1;
        }
        return true;
    }
    return false;
}
// isProvided: whether the hit's geometry has the attribute.
X2_HD inline bool primProvided(const State& st, U32 key) {
    for (U32 i = 0; i < st.primCount; ++i)
        if (st.prims[i].key == key) return true;
    return false;
}
// isProvided and get<T>Attribute: the attribute with this key at the hit, interpolated as its rate says.
X2_CALL bool primValue(const State& st, U32 key, float out[3]) {
    for (U32 i = 0; i < st.primCount; ++i) {
        const PrimAttr& a = st.prims[i];
        if (a.key != key) continue;
        const U32 n = a.components;
        const float* d = st.primData + a.offset;
        out[0] = out[1] = out[2] = 0.0f;
        if (st.curve) return curvePrimValue(st, a, out);
        switch (a.rate) {
        case PrimConstant:
            for (U32 k = 0; k < n; ++k) out[k] = d[k];
            return true;
        case PrimUniform:
            for (U32 k = 0; k < n; ++k) out[k] = d[st.prim * n + k];
            return true;
        case PrimVertex:
        case PrimVarying: {
            const float w = 1.0f - st.u - st.v;
            for (U32 k = 0; k < n; ++k) out[k] = w * d[st.ia * n + k] + st.u * d[st.ib * n + k] + st.v * d[st.ic * n + k];
            return true;
        }
        case PrimFaceVarying: {
            const float w = 1.0f - st.u - st.v;
            const U32 b = st.prim * 3;
            for (U32 k = 0; k < n; ++k) out[k] = w * d[b * n + k] + st.u * d[(b + 1) * n + k] + st.v * d[(b + 2) * n + k];
            return true;
        }
        default: return false;
        }
    }
    return false;
}
X2_HD inline V3 xformPoint(const float* m, V3 p) {
    return V3{m[0] * p.x + m[1] * p.y + m[2] * p.z + m[3], m[4] * p.x + m[5] * p.y + m[6] * p.z + m[7],
              m[8] * p.x + m[9] * p.y + m[10] * p.z + m[11]};
}

// Intersection_adaptNormal ("The Iray Light Transport System", A.3).
X2_HD inline V3 adaptNormal(const State& st, V3 Ns) {
    const V3 wo = st.wo, Ng = st.Ng;
    const V3 r = 2.f * dot(Ns, wo) * Ns - wo;
    const float rDotNg = dot(r, Ng), eps = 0.001f;
    if (rDotNg < eps) {
        const V3 rBent = normalize(r + (eps - rDotNg) * Ng);
        return normalize(wo + rBent);
    }
    return Ns;
}
X2_HD inline V3 adaptToonNormal(const State& st, V3 Ns) { return st.useAdaptNormal ? adaptNormal(st, Ns) : Ns; }
X2_HD inline float minRoughness(const State& st) { return fminf(st.minRoughness[0], st.minRoughness[1]); }

// Ior.isph ShaderIor (ISPC: the medium outside is always 1).
struct ShaderIor {
    float incident, transmitted, ratio;
};
X2_HD inline ShaderIor shaderIor(const State& st, float materialIor, bool thin) {
    ShaderIor r;
    r.incident = (st.entering || thin) ? 1.0f : materialIor;
    r.transmitted = (st.entering || thin) ? materialIor : 1.0f;
    r.ratio = r.incident / r.transmitted;
    return r;
}
}}}
