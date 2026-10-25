// Private XPU2 curves, shared CPU/CUDA: MoonRay XPU's curve intersection (its OptiX __intersection__ programs,
// OptixGPUPrograms.cu) as functions both lanes call, the GPU from its curve intersection program and the CPU from
// an Embree user geometry, so both find what MoonRay XPU's GPU finds. Derived from MoonRay Apache-2.0
// (lib/rendering/rt/gpu/optix), Copyright 2023-2024 DreamWorks Animation LLC, which ports Embree 4 (Copyright
// 2009-2021 Intel Corporation, Apache-2.0) for round curves. See MOONRAY_LICENSE.txt.
//
// A curve set is a mesh of the plan whose spans take the place of triangles: span i is primitive i, as MoonRay's
// index buffer (geom/prim/Curves.h IndexData) numbers them for both Embree and OptiX. The hit programs report only
// the span; each lane then works the hit out again from it with these functions (as resume::geometryHit does for
// triangles), so the hit's numbers never depend on the lane.
#pragma once
#include "surface_core.h"
#if !defined(__CUDACC_RTC__)
#include <limits>
#include <math.h>
#include <stddef.h>
#endif
namespace xpu2 { namespace interactive { namespace curves {
using U32 = unsigned int;
using surface::V3;

// The vector types MoonRay's device code is written in: CUDA's own on the GPU, these on the CPU.
#if defined(__CUDACC__)
using ::float2;
using ::float3;
using ::float4;
using ::make_float2;
using ::make_float3;
using ::make_float4;
#else
struct float2 { float x, y; };
struct float3 { float x, y, z; };
struct float4 { float x, y, z, w; };
inline float2 make_float2(float x, float y) { return {x, y}; }
inline float3 make_float3(float x, float y, float z) { return {x, y, z}; }
inline float4 make_float4(float x, float y, float z, float w) { return {x, y, z, w}; }
inline float rsqrtf(float a) { return 1.f / ::sqrtf(a); }  // OptixGPUMath.h's host rsqrtf
#endif
// The C library's float functions, beside the vendored overloads of the same names that would hide them here
// (MoonRay's are global, so CUDA's own overloads stay in sight there).
X2_HD inline float fminf(float a, float b) { return ::fminf(a, b); }
X2_HD inline float fmaxf(float a, float b) { return ::fmaxf(a, b); }
X2_HD inline float min(float a, float b) { return ::fminf(a, b); }
X2_HD inline float max(float a, float b) { return ::fmaxf(a, b); }
X2_HD inline float abs(float a) { return ::fabsf(a); }
X2_HD inline float sqrt(float a) { return ::sqrtf(a); }

// EmbreeSupport.h's constants, as macros for the vendored code only.
#if defined(__CUDACC__)
#define pos_inf (__int_as_float(0x7f800000))
#else
#define pos_inf (std::numeric_limits<float>::infinity())
#endif
#define inf pos_inf
#define neg_inf (-pos_inf)
#define ulp (1.192092896e-07f)
#define min_rcp_input (1E-18f)
#include "curve_embree.h"
#undef min_rcp_input
#undef ulp
#undef neg_inf
#undef inf
#undef pos_inf

// The curve programs stay single calls on the GPU (each is reached from several places).
#if defined(__CUDACC__)
#define X2_CURVE_CALL __host__ __device__ __noinline__ inline
#else
#define X2_CURVE_CALL inline
#endif

X2_HD inline float infinity() {
#if defined(__CUDACC__)
    return __int_as_float(0x7f800000);
#else
    return std::numeric_limits<float>::infinity();
#endif
}

// Curves::Type and SubType. MoonRay XPU draws Bezier curves flat whatever their subtype (its
// OptixGPUPrimitiveGroup gives Bezier curves the flat program).
enum Basis : U32 { BasisNone = 0, BasisLinear = 1, BasisBezier = 2, BasisBspline = 3 };

// A curve set: its control points (x, y, z and radius, render space) and spans (MoonRay's IndexData: the span's
// first control point, its curve, its place along the curve), each curve's span count, the type, whether round,
// and the flat cubic programs' quads per span (tessellation_rate).
struct Set {
    const float* points = nullptr;
    const U32* spans = nullptr;      // three words a span
    const U32* curveSpans = nullptr;  // a word a curve
    U32 spanCount = 0, pointCount = 0, basis = BasisNone, round = 0, segments = 4;
    // Under motion blur: the control points at the later time steps (stepCount - 1 arrays laid out as points), and
    // the time (0 to 1 over the shutter, the ray's) the points are taken at.
    const float* const* steps = nullptr;
    U32 stepCount = 1;
    float time = 0.0f;
};
X2_HD inline float4 stepPoint(const Set& c, U32 k, U32 i) {
    const float* p = (k ? c.steps[k - 1] : c.points) + 4 * size_t(i);
    return make_float4(p[0], p[1], p[2], p[3]);
}
// A control point at the set's time: between the two time steps about it, as Embree interpolates them.
X2_HD inline float4 point(const Set& c, U32 i) {
    if (c.stepCount < 2) return stepPoint(c, 0, i);
    const float f = c.time * float(c.stepCount - 1);
    U32 k = f > 0.0f ? U32(f) : 0u;
    if (k > c.stepCount - 2) k = c.stepCount - 2;
    const float u = f - float(k);
    return (1.0f - u) * stepPoint(c, k, i) + u * stepPoint(c, k + 1, i);
}
// The control point LineSegments' and CubicSpline's postIntersect shade with: the first two time steps lerped to
// t (whatever the steps).
X2_HD inline float4 shadingPoint(const Set& c, U32 i, float t) {
    if (c.stepCount < 2) return stepPoint(c, 0, i);
    return (1.0f - t) * stepPoint(c, 0, i) + t * stepPoint(c, 1, i);
}
X2_HD inline U32 spanVertex(const Set& c, U32 span) { return c.spans[3 * size_t(span)]; }
X2_HD inline U32 spanCurve(const Set& c, U32 span) { return c.spans[3 * size_t(span) + 1]; }
X2_HD inline U32 spanIndex(const Set& c, U32 span) { return c.spans[3 * size_t(span) + 2]; }
X2_HD inline U32 pointsPerSpan(const Set& c) { return c.basis == BasisLinear ? 2u : 4u; }

// A hit on a span: its distance, the span's u, v across a flat cubic (-1 to 1, else 0), and a round curve's
// geometric normal (unnormalised; zero for flat curves, whose normal faces the ray).
struct Hit {
    float t = 0, u = 0, v = 0;
    V3 Ng{0, 0, 0};
};

// OptixGPUPrograms.cu: projectCurveControlPoints, computeCurveEpsilon, intersectCurveQuad.
X2_HD inline void projectCurveControlPoints(const float4* cp, const unsigned int numPoints, const float3& rayOrg,
                                            const float3& rayDir, float4* cp2d) {
    // Rotate curve control points to Z plane perpendicular to ray
    OptixGPUXform curve2DXform = OptixGPUXform::rotateToZAxisXform(rayDir);
    for (int i = 0; i < int(numPoints); i++) {
        float3 pos2d = curve2DXform.transformVector(make_float3(cp[i]) - rayOrg);
        cp2d[i] = make_float4(pos2d, cp[i].w);
    }
}
X2_HD inline float computeCurveEpsilon(const float4 cp[4]) {
    // from embree
    return 4.f * 1.192092896e-07f *  // FLOAT_EPSILON
           fmaxf(maxAbsComponent(make_float3(cp[0])), maxAbsComponent(make_float3(cp[1])), maxAbsComponent(make_float3(cp[2])),
                 maxAbsComponent(make_float3(cp[3])));
}
X2_HD inline bool intersectCurveQuad(const float3 vtx[4], const float dirLength, const float rayTMin, const float rayTMax, float* u,
                                     float* v, float* t) {
    // From embree intersect_quad_backface_culling(), except we assume the ray origin is at zero.
    float side = dot(cross(vtx[3], vtx[1]), make_float3(0.f, 0.f, dirLength));
    const float3 v0 = side <= 0.f ? vtx[0] : vtx[2];
    const float3 v1 = side <= 0.f ? vtx[1] : vtx[3];
    const float3 v2 = side <= 0.f ? vtx[3] : vtx[1];
    const float3 e0 = v2 - v0;
    const float3 e1 = v0 - v1;
    float uu = dot(cross(v0, e0), make_float3(0.f, 0.f, dirLength));
    float vv = dot(cross(v1, e1), make_float3(0.f, 0.f, dirLength));
    if (uu > 0.f || vv > 0.f) return false;
    const float3 Ng = cross(e1, e0);  // geom normal
    float den = dot(Ng, make_float3(0.f, 0.f, dirLength));
    if (den == 0.f) return false;
    float invDen = 1.f / den;
    *t = invDen * dot(v0, Ng);
    if (rayTMin > *t || rayTMax < *t) return false;
    *u = uu * invDen;
    *v = vv * invDen;
    *u = side <= 0.f ? *u : 1.f - *u;
    *v = side <= 0.f ? *v : 1.f - *v;
    return true;
}

// __intersection__flat_bezier_curve and __intersection__flat_bspline_curve (based on PBRT): the span as
// segmentsPerCurve quads that face the ray.
X2_CURVE_CALL bool flatCubic(const float4 cp[4], bool bspline, U32 segmentsPerCurve, float3 rayOrg, float3 rayDir, float rayTmin,
                            float rayTmax, Hit& out) {
    const float dirLength = length(rayDir);
    float4 cp2d[4];
    projectCurveControlPoints(cp, 4, rayOrg, rayDir, cp2d);
    float eps = computeCurveEpsilon(cp2d);
    bool hit = false;
    float closestHitT = rayTmax;
    float isectU = 0.f;
    float isectV = 0.f;
    float deltaT = 1.f / static_cast<float>(segmentsPerCurve);
    float4 p1;
    float3 tangentVec;
    if (bspline) {
        p1 = evalBspline(cp2d, 0.f);
        tangentVec = evalBsplineDerivative(cp2d, 0.f);
        if (maxAbsComponent(tangentVec) < eps) {
            float t2 = deltaT;
            tangentVec = make_float3(evalBspline(cp2d, t2)) - make_float3(p1);
        }
    } else {
        p1 = cp2d[0];  // The bezier basis at u=0 is {1, 0, 0, 0}
        tangentVec = 3.f * make_float3(cp2d[1] - cp2d[0]);
        if (maxAbsComponent(tangentVec) < eps) {
            float t2 = deltaT;
            tangentVec = make_float3(evalBezier(cp2d, t2)) - make_float3(p1);
        }
    }
    float3 n1 = p1.w * normalize(make_float3(tangentVec.y, -tangentVec.x, 0.f));
    for (int i = 0; i < int(segmentsPerCurve); i++) {
        float4 p0 = p1;
        float3 n0 = n1;
        float t0 = static_cast<float>(i) * deltaT;
        float t1 = static_cast<float>(i + 1) * deltaT;
        if (bspline) {
            p1 = evalBspline(cp2d, t1);
            tangentVec = evalBsplineDerivative(cp2d, t1);
        } else {
            p1 = evalBezier(cp2d, t1);
            tangentVec = evalBezierDerivative(cp2d, t1);
        }
        if (maxAbsComponent(tangentVec) < eps) tangentVec = make_float3(p1) - make_float3(p0);
        n1 = p1.w * normalize(make_float3(tangentVec.y, -tangentVec.x, 0.f));
        const float3 quadVerts[4] = {make_float3(p0) + n0, make_float3(p1) + n1, make_float3(p1) - n1, make_float3(p0) - n0};
        float u, v, t;
        if (!intersectCurveQuad(quadVerts, dirLength, rayTmin, closestHitT, &u, &v, &t)) continue;
        float r = lerpf(p0.w, p1.w, u);
        if (t < 2.f * r / dirLength) continue;
        hit = true;
        closestHitT = t;
        isectU = t0 + u * deltaT;
        isectV = 2.f * v - 1.f;
    }
    if (!hit) return false;
    out.t = closestHitT;
    out.u = isectU;
    out.v = isectV;
    out.Ng = V3{0, 0, 0};
    return true;
}

// __intersection__round_bspline_curve: Embree's swept round B-spline.
X2_CURVE_CALL bool roundBspline(const float4 cp[4], float3 rayOrg, float3 rayDir, float rayTmin, float rayTmax, Hit& out) {
    EmbreeRayHit rayHit;
    rayHit.org = rayOrg;
    rayHit.dir = rayDir;
    rayHit.tnear = rayTmin;
    rayHit.tfar = rayTmax;
    rayHit.Ng = make_float3(0.f, 0.f, 0.f);
    rayHit.u = 0.f;
    rayHit.v = 0.f;
    RoundBezierCurveEpilog epilog(&rayHit);
    SweepCurveIntersector intersector;
    if (!intersector.intersect(rayHit, cp[0], cp[1], cp[2], cp[3], epilog)) return false;
    out.t = rayHit.tfar;
    out.u = rayHit.u;
    out.v = 0.f;
    out.Ng = V3{rayHit.Ng.x, rayHit.Ng.y, rayHit.Ng.z};
    return true;
}

// __intersection__flat_linear_curve (PBRT3 section 3.7 fig 3.23): the closest point of the segment to the ray.
X2_CURVE_CALL bool flatLinear(const float4 cp[2], float3 rayOrg, float3 rayDir, float rayTmin, float rayTmax, Hit& out) {
    const float dirLength = length(rayDir);
    float4 cp2d[2];
    projectCurveControlPoints(cp, 2, rayOrg, rayDir, cp2d);
    const float4 dv = cp2d[1] - cp2d[0];
    if (dv.x == 0.f && dv.y == 0.f && dv.z == 0.f) return false;  // Ignore degenerate segments
    const float d0 = -cp2d[0].x * dv.x - cp2d[0].y * dv.y;
    const float d1 = dv.x * dv.x + dv.y * dv.y;
    const float u = clampf(d0 / d1, 0.f, 1.f);
    const float4 p = cp2d[0] + u * dv;
    const float t = p.z / dirLength;
    const float d2 = p.x * p.x + p.y * p.y;
    const float r = p.w;
    const float r2 = r * r;
    if (!(d2 <= r2 && rayTmin <= t && t <= rayTmax && t > 2.f * r / dirLength)) return false;
    out.t = t;
    out.u = u;
    out.v = 0.f;
    out.Ng = V3{0, 0, 0};
    return true;
}

// __intersection__round_linear_curve: Embree's round linear curve, its neighbouring segments cut away.
X2_CURVE_CALL bool roundLinear(const Set& c, U32 span, const float4 cp[2], float3 rayOrg, float3 rayDir, float rayTmin, float rayTmax,
                              Hit& out) {
    const U32 cpIdx = spanVertex(c, span);
    float4 cpL = make_float4(infinity(), infinity(), infinity(), infinity());
    if (span > 0) {
        const U32 cpLeftIdx = spanVertex(c, span - 1);
        if (cpLeftIdx + 1 == cpIdx) cpL = point(c, cpLeftIdx);  // Curve continues to the left
    }
    float4 cpR = make_float4(infinity(), infinity(), infinity(), infinity());
    if (span + 1 < c.spanCount) {
        const U32 cpRightIdx = spanVertex(c, span + 1);
        if (cpRightIdx - 1 == cpIdx) cpR = point(c, cpRightIdx);  // Curve continues to the right
    }
    EmbreeRayHit rayHit;
    rayHit.org = rayOrg;
    rayHit.dir = rayDir;
    rayHit.tnear = rayTmin;
    rayHit.tfar = rayTmax;
    rayHit.Ng = make_float3(0.f, 0.f, 0.f);
    rayHit.u = 0.f;
    rayHit.v = 0.f;
    RoundLinearCurveEpilog epilog(&rayHit);
    RoundLinearCurveIntersector intersector;
    if (!intersector.intersect(true, rayHit, cp[0], cp[1], cpL, cpR, epilog)) return false;
    out.t = rayHit.tfar;
    out.u = rayHit.u;
    out.v = 0.f;
    out.Ng = V3{rayHit.Ng.x, rayHit.Ng.y, rayHit.Ng.z};
    return true;
}

// A ray against one span, as MoonRay XPU's program for the set's type finds it.
X2_HD inline bool intersectSpan(const Set& c, U32 span, V3 org, V3 dir, float tmin, float tmax, Hit& out) {
    if (span >= c.spanCount) return false;
    const float3 o = make_float3(org.x, org.y, org.z), d = make_float3(dir.x, dir.y, dir.z);
    const U32 first = spanVertex(c, span);
    if (c.basis == BasisLinear) {
        const float4 cp[2] = {point(c, first), point(c, first + 1)};
        return c.round ? roundLinear(c, span, cp, o, d, tmin, tmax, out) : flatLinear(cp, o, d, tmin, tmax, out);
    }
    const float4 cp[4] = {point(c, first), point(c, first + 1), point(c, first + 2), point(c, first + 3)};
    if (c.basis == BasisBspline && c.round) return roundBspline(cp, o, d, tmin, tmax, out);
    return flatCubic(cp, c.basis == BasisBspline, c.segments, o, d, tmin, tmax, out);
}

// OptixGPUCurve::getPrimitiveAabbs: a span's bounds, its control points grown by their radii.
X2_HD inline void spanBounds(const Set& c, U32 span, float lower[3], float upper[3]) {
    lower[0] = lower[1] = lower[2] = 3.402823466e+38f;
    upper[0] = upper[1] = upper[2] = -3.402823466e+38f;
    const U32 first = spanVertex(c, span), n = pointsPerSpan(c);
    for (U32 j = 0; j < n; ++j) {
        const float4 p = point(c, first + j);
        const float q[3] = {p.x, p.y, p.z};
        for (int k = 0; k < 3; ++k) {
            lower[k] = fminf(lower[k], q[k] - p.w);
            upper[k] = fmaxf(upper[k], q[k] + p.w);
        }
    }
}

// BSpline's and BezierSpanChains' evalWeights: the span's control points' weights at t (MoonRay's CPU forms,
// with which postIntersect interpolates).
X2_HD inline void cubicWeights(U32 basis, float t, float w[4]) {
    const float s = 1.f - t;
    if (basis == BasisBspline) {
        const float oneSixth(1.0f / 6.0f);
        w[0] = oneSixth * s * s * s;
        w[1] = 0.5f * s * (s * t + 1.0f) + oneSixth;
        w[2] = 0.5f * t * (s * t + 1.0f) + oneSixth;
        w[3] = oneSixth * t * t * t;
    } else {
        w[0] = s * s * s;
        w[1] = 3.0f * s * s * t;
        w[2] = 3.0f * s * t * t;
        w[3] = t * t * t;
    }
}
// evalCubicDeriv with evalDerivWeights: the span's tangent at t.
X2_HD inline V3 cubicTangent(U32 basis, const float4 cp[4], float t) {
    const float s = 1.f - t;
    float w0, w1, w2;
    if (basis == BasisBspline) {
        w0 = 0.5f * s * s;
        w1 = s * t + 0.5f;
        w2 = 0.5f * t * t;
    } else {
        w0 = 3.0f * s * s;
        w1 = 6.0f * s * t;
        w2 = 3.0f * t * t;
    }
    const float4 d = w0 * (cp[1] - cp[0]) + w1 * (cp[2] - cp[1]) + w2 * (cp[3] - cp[2]);
    return V3{d.x, d.y, d.z};
}
}}}
