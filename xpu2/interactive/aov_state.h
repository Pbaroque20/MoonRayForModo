// State variable and primitive attribute AOVs (pbr/core/Aov.cc getStateVar, sampleWireframe, aovSetPrimAttrs) at a
// hit, in MoonRay's render space (the camera's space at its first motion step; XPU2 shades in world space).
#pragma once
#include "aov_core.h"
#include "shade_state.h"

namespace xpu2::interactive::aov {

// What the state variables need beyond the hit's state.
struct StateContext {
    const float* worldToRender;  // 3x4 rows (null: identity)
    V3 cameraPosition;           // world space
    float tHit;                  // the ray's distance to the hit
    bool projective;             // a projective camera: depth is camera space -z, else the ray's distance
    // getStateVar's volume depth, -volumeT * the ray's render space direction z, which the depth state variable takes
    // the least of with the camera's: volumeT is sMaxValue where the ray met no volume surface, so a ray toward the
    // camera's +z (an inside-out spherical camera's, a fisheye's past 90 degrees) gives a depth of -sMaxValue * z.
    float volumeZ = 3.402823466e38f;
};
X2_HD inline V3 renderPointOf(const float* m, V3 p) {
    if (!m) return p;
    return V3{m[0] * p.x + m[1] * p.y + m[2] * p.z + m[3], m[4] * p.x + m[5] * p.y + m[6] * p.z + m[7],
              m[8] * p.x + m[9] * p.y + m[10] * p.z + m[11]};
}
X2_HD inline V3 renderVectorOf(const float* m, V3 v) { return m ? shade::xformVector(m, v) : v; }

// sampleWireframe: one where the hit lies within half a pixel's width of its polygon's edge (every hit on a curve).
X2_HD inline float wireframe(const shade::State& st, V3 cameraPosition) {
    if (st.curve) return 1.0f;
    const V3 dpdx = surface::add(surface::mul(st.dPds, st.dsdx), surface::mul(st.dPdt, st.dtdx));
    const V3 dpdy = surface::add(surface::mul(st.dPds, st.dsdy), surface::mul(st.dPdt, st.dtdy));
    V3 I;
    if (!surface::normalize(surface::add(st.P, surface::mul(cameraPosition, -1.0f)), I)) return 0.0f;
    const V3 ex = surface::add(dpdx, surface::mul(I, -surface::dot(I, dpdx))), ey = surface::add(dpdy, surface::mul(I, -surface::dot(I, dpdy)));
    const float pwSq = (surface::dot(ex, ex) + surface::dot(ey, ey)) * 0.125f;
    const V3 v[4] = {st.pa, st.pb, st.pc, st.pd};
    const U32 n = st.polyCount;
    for (U32 i1 = 0; i1 < n; ++i1) {
        const U32 i0 = i1 ? i1 - 1 : n - 1;
        const V3 edge = surface::add(v[i1], surface::mul(v[i0], -1.0f)), dir = surface::add(st.P, surface::mul(v[i0], -1.0f));
        const V3 c = surface::cross(edge, dir);
        if (surface::dot(c, c) < pwSq * surface::dot(edge, edge)) return 1.0f;
    }
    return 0.0f;
}

// getStateVar: one state variable's value, scaled by the weight.
X2_HD inline void stateValue(U32 schema, const shade::State& st, const StateContext& c, float w, float* d) {
    auto put3 = [&](V3 v) {
        d[0] = v.x * w;
        d[1] = v.y * w;
        d[2] = v.z * w;
    };
    switch (schema) {
    case StateP: put3(renderPointOf(c.worldToRender, st.P)); break;
    case StateNg: put3(renderVectorOf(c.worldToRender, st.Ng)); break;
    case StateN: put3(renderVectorOf(c.worldToRender, st.N)); break;
    case StateSt:
        d[0] = st.s * w;
        d[1] = st.t * w;
        break;
    case StateDpds: put3(renderVectorOf(c.worldToRender, st.dPds)); break;
    case StateDpdt: put3(renderVectorOf(c.worldToRender, st.dPdt)); break;
    case StateDsdx: d[0] = st.dsdx * w; break;
    case StateDsdy: d[0] = st.dsdy * w; break;
    case StateDtdx: d[0] = st.dtdx * w; break;
    case StateDtdy: d[0] = st.dtdy * w; break;
    case StateWireframe: d[0] = wireframe(st, c.cameraPosition) * w; break;
    case StateWp: put3(st.P); break;
    case StateDepth: d[0] = fminf(c.projective ? -renderPointOf(c.worldToRender, st.P).z : c.tHit, c.volumeZ) * w; break;
    case StateMotion:
        // computeMotion: the screen-space motion of the point and the camera, none for a still scene.
        d[0] = d[1] = 0.0f;
        break;
    default: break;
    }
}

// A primitive attribute at the hit (shade::primValue), NaN where the hit's geometry does not have it.
X2_HD inline float notANumber() {
    union {
        U32 u;
        float f;
    } x{0x7fc00000u};
    return x.f;
}
X2_HD inline void primValueAt(const shade::State& st, U32 key, float* v) {
    float t[3] = {0, 0, 0};
    if (shade::primValue(st, key, t)) {
        v[0] = t[0];
        v[1] = t[1];
        v[2] = t[2];
    } else {
        v[0] = v[1] = v[2] = notANumber();
    }
}

}  // namespace xpu2::interactive::aov
