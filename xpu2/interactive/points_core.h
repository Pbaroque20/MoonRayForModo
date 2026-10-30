// MoonRay's points (geom/prim/Points.cc): spheres met from outside only, as its intersection function has them, and
// their shading state (Points::postIntersect: the normal from the centre, St from the "st" or "uv" attribute or one,
// no derivatives), shared by the CPU and CUDA lanes.
//
// Adapted from MoonRay geom/prim/Points.cc, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC; see
// MOONRAY_LICENSE.txt.
#pragma once
#include "shade_material.h"

namespace xpu2::interactive::points {
using surface::V3;
using sample::U32;

// The ray against the sphere: no hit for a ray leaving the centre or starting inside, else the nearer root within
// (tnear, tfar), and its geometric normal ((1 / r) * rn).
X2_HD inline bool intersect(V3 p, float r, V3 o, V3 d, float tnear, float tfar, float& t, V3& Ng) {
    const float r2 = r * r;
    const V3 u = surface::add(p, surface::mul(o, -1.0f));
    if (surface::dot(d, u) < 0.0f) return false;
    if (surface::dot(u, u) < r2) return false;
    const V3 v = surface::cross(d, u);
    const float v2 = surface::dot(v, v), d2 = surface::dot(d, d), D = r2 * d2 - v2;
    if (D < 0.0f) return false;
    const float s = sqrtf(D);
    const V3 w = surface::cross(d, v);
    const V3 rn = surface::mul(surface::add(w, surface::mul(d, -s)), 1.0f / d2);
    const V3 urn = surface::add(u, rn);
    const float tt = sqrtf(surface::dot(urn, urn)) * (1.0f / sqrtf(d2));
    if (!(tnear < tt && tt < tfar)) return false;
    t = tt;
    Ng = surface::mul(rn, 1.0f / r);
    return true;
}

// Points::postIntersect: Ng and N the hit's normalized geometric normal, St the point's "st" (else "uv") attribute
// or (1, 1), no derivatives; a motion vector from the point's first two time steps (positions0, positions1).
X2_HD inline bool state(const shade::MeshAttributes& m, U32 prim, V3 Ng, V3 P, V3 rayDir, shade::State& st) {
    using namespace shade;
    const float l = length(Ng);
    if (!(l > 0)) return false;
    st.Ng = Ng / l;
    st.prims = m.prims;
    st.primData = m.primData;
    st.primCount = m.primCount;
    st.instancePrims = m.instancePrims;
    st.instancePrimData = m.instancePrimData;
    st.instancePrimCount = m.instancePrimCount;
    st.prim = prim;
    st.ia = st.ib = st.ic = prim;
    st.u = st.v = 0.0f;
    float uv[3] = {1, 1, 0};
    st.s = 1.0f;
    st.t = 1.0f;
    if (primValue(st, primKey("st", PrimVec2f), uv) || primValue(st, primKey("uv", PrimVec2f), uv)) {
        st.s = uv[0];
        st.t = uv[1];
    }
    st.stInv[0] = st.stInv[3] = 1.0f;
    st.stInv[1] = st.stInv[2] = 0.0f;
    st.dPds = st.dPdt = V3{0, 0, 0};
    st.dNds = st.dNdt = V3{0, 0, 0};
    st.P = P;
    st.wo = -rayDir;
    st.entering = dot(st.Ng, rayDir) < 0.0f;
    if (!st.entering) st.Ng = -st.Ng;
    st.N = st.Ng;
    st.pa = st.pb = st.pc = st.pd = P;
    st.polyCount = 0;  // the wireframe AOV is blank
    st.motion = V3{0, 0, 0};
    if (m.positions0 && m.positions1) {
        const float t0 = m.time - 0.01f, t1 = m.time + 0.01f;
        const V3 a = m.positions0[prim], b = m.positions1[prim];
        const V3 p0 = (1.0f - t0) * a + t0 * b, p1 = (1.0f - t1) * a + t1 * b;
        st.motion = (p1 - p0) / (2.0f * 0.01f);
    }
    st.dsdx = st.dsdy = st.dtdx = st.dtdy = 0.0f;
    return finite3(st.N);
}

}  // namespace xpu2::interactive::points
