// Private XPU2 shading library, shared CPU/CUDA: the hit's shading state from a
// mesh's attributes, and the materials (MoonRay's material DSOs' shade()
// functions over the BsdfBuilder). Derived from MoonRay Apache-2.0
// (geom/prim/TriMesh.cc postIntersect, dso/material/UsdPreviewSurface),
// Copyright 2023-2024 DreamWorks Animation LLC. See MOONRAY_LICENSE.txt.
#pragma once
#include "shade_dwalayer.h"
#include "shade_mapnodes.h"
#include "curve_core.h"
namespace xpu2 { namespace interactive { namespace shade {

// A mesh's shading attributes: normals and texture coordinates, per vertex
// (indexed like the positions) or per face-vertex (three per triangle).
enum AttributeRate : U32 { RateNone = 0, RateVertex = 1, RateFaceVarying = 2 };
struct MeshAttributes {
    const V3* normals = nullptr;
    const float* uvs = nullptr;  // two per entry
    U32 normalRate = RateNone, uvRate = RateNone;
    float worldToObject[12] = {1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0};  // the mesh's node transform's inverse, 3x4 rows
    const PrimAttr* prims = nullptr;  // its primitive attributes (UserData)
    const float* primData = nullptr;
    U32 primCount = 0;
    curves::Set curve;  // a curve set in place of triangles (curve_core.h)
    // MoonRay's polyvertices of each triangle (four vertex indices, the fourth ~0u for a TriMesh's triangle) and the
    // positions they index; null where nothing reads them.
    const U32* polyVertices = nullptr;
    const V3* positions = nullptr;
};

// computeTrianglePartialDerivatives (scene_rdl2 MathUtil.h).
X2_HD inline float differenceOfProducts(float a, float b, float c, float d) {
    const float cd = c * d;
    const float err = fmaf(-c, d, cd);
    const float dop = fmaf(a, b, -cd);
    return dop + err;
}
X2_HD inline bool trianglePartials(V3 x0, V3 x1, V3 x2, const float uv0[2], const float uv1[2], const float uv2[2], V3& dPds,
                                   V3& dPdt) {
    const float A[4] = {uv1[0] - uv0[0], uv1[1] - uv0[1], uv2[0] - uv0[0], uv2[1] - uv0[1]};
    const V3 b0 = x1 - x0, b1 = x2 - x0;
    const float det = differenceOfProducts(A[0], A[3], A[1], A[2]);
    if (!(fabsf(det) >= 1.17549435e-38f) || !(fabsf(det) <= 3.402823466e38f)) return false;  // std::isnormal
    const float inv = 1.0f / det;
    dPds = V3{differenceOfProducts(b0.x, A[3], b1.x, A[1]), differenceOfProducts(b0.y, A[3], b1.y, A[1]),
              differenceOfProducts(b0.z, A[3], b1.z, A[1])} * inv;
    dPdt = V3{differenceOfProducts(b1.x, A[0], b0.x, A[2]), differenceOfProducts(b1.y, A[0], b0.y, A[2]),
              differenceOfProducts(b1.z, A[0], b0.z, A[2])} * inv;
    return finite3(dPds) && finite3(dPdt);
}

// TriMesh::postIntersect and initIntersectionPhase1: St, Ng, N, dPds and dPdt
// at barycentrics (u, v) of triangle (a, b, c) of the given mesh, and the
// flip toward the viewer. Ng is (b - a) x (c - a), as MoonRay XPU's OptiX
// program computes it.
X2_CALL bool hitState(const MeshAttributes& m, U32 prim, U32 ia, U32 ib, U32 ic, V3 a, V3 b, V3 c, float u, float v,
                           V3 P, V3 rayDir, State& st) {
    const float w = 1.0f - u - v;
    V3 ng = cross(b - a, c - a);
    const float l = length(ng);
    if (!(l > 0)) return false;
    st.Ng = ng / l;
    float st1[2] = {0, 0}, st2[2] = {1, 0}, st3[2] = {1, 1};
    if (m.uvRate != RateNone && m.uvs) {
        const U32 i1 = m.uvRate == RateVertex ? ia : prim * 3, i2 = m.uvRate == RateVertex ? ib : prim * 3 + 1,
                  i3 = m.uvRate == RateVertex ? ic : prim * 3 + 2;
        st1[0] = m.uvs[2 * i1];
        st1[1] = m.uvs[2 * i1 + 1];
        st2[0] = m.uvs[2 * i2];
        st2[1] = m.uvs[2 * i2 + 1];
        st3[0] = m.uvs[2 * i3];
        st3[1] = m.uvs[2 * i3 + 1];
    }
    st.s = w * st1[0] + u * st2[0] + v * st3[0];
    st.t = w * st1[1] + u * st2[1] + v * st3[1];
    {
        const float A0 = st2[0] - st1[0], A1 = st2[1] - st1[1], A2 = st3[0] - st1[0], A3 = st3[1] - st1[1];
        const float detA = A0 * A3 - A1 * A2;
        if (fabsf(detA) >= 1.17549435e-38f && fabsf(detA) <= 3.402823466e38f) {  // std::isnormal
            const float invDet = 1.0f / detA;
            st.stInv[0] = invDet * A3;
            st.stInv[1] = invDet * -A1;
            st.stInv[2] = invDet * -A2;
            st.stInv[3] = invDet * A0;
        } else {
            st.stInv[0] = st.stInv[3] = 1.0f;
            st.stInv[1] = st.stInv[2] = 0.0f;
        }
    }
    V3 N = st.Ng;
    st.dNds = st.dNdt = V3{0, 0, 0};
    if (m.normalRate != RateNone && m.normals) {
        const U32 i1 = m.normalRate == RateVertex ? ia : prim * 3, i2 = m.normalRate == RateVertex ? ib : prim * 3 + 1,
                  i3 = m.normalRate == RateVertex ? ic : prim * 3 + 2;
        const V3 n = w * m.normals[i1] + u * m.normals[i2] + v * m.normals[i3];
        const float ln = length(n);
        if (ln > 0) N = n / ln;
        if (!trianglePartials(m.normals[i1], m.normals[i2], m.normals[i3], st1, st2, st3, st.dNds, st.dNdt)) st.dNds = st.dNdt = V3{0, 0, 0};
    }
    st.pa = a;
    st.pb = b;
    st.pc = c;
    st.pd = c;
    st.polyCount = 3;
    if (m.polyVertices && m.positions) {
        const U32* q = m.polyVertices + 4 * size_t(prim);
        st.pa = m.positions[q[0]];
        st.pb = m.positions[q[1]];
        st.pc = m.positions[q[2]];
        if (q[3] != ~0u) {
            st.pd = m.positions[q[3]];
            st.polyCount = 4;
        }
    }
    if (!trianglePartials(a, b, c, st1, st2, st3, st.dPds, st.dPdt)) {
        const Frame f = frame(N);
        st.dPds = f.x;
        st.dPdt = f.y;
    }
    st.P = P;
    st.wo = -rayDir;
    st.entering = dot(st.Ng, rayDir) < 0.0f;
    if (!st.entering) {
        N = -N;
        st.Ng = -st.Ng;
    }
    st.N = N;
    st.prim = prim;
    st.u = u;
    st.v = v;
    st.ia = ia;
    st.ib = ib;
    st.ic = ic;
    st.prims = m.prims;
    st.primData = m.primData;
    st.primCount = m.primCount;
    return finite3(st.N) && finite3(st.Ng);
}

//----------------------------------------------------------------------------
// Materials. A material is a record and its parameters in a pool of floats.
enum MaterialKind : U32 { MatUsdPreviewSurface = 1, MatDwaBase = 2, MatSwitch = 3 };
enum MaterialFlags : U32 { MatModoUsdSpecular = 1, MatPolyVertices = 2 };  // MatPolyVertices: its maps read the hit polygon
// maps: the material's map program (shade_maps.h), NoMapProgram for none; bindings: its own bound
// attributes (UsdPreviewSurface; a DwaBase tree's are on its nodes).
struct MaterialRecord {
    U32 kind = 0, flags = 0, offset = 0, count = 0;
    // labels: its label table's pool offset (Builder::labels), NoLabels when no AOV asks for labels.
    U32 maps = NoMapProgram, bindings = 0, bindingCount = 0, labels = 0xffffffffu;
    // Its extra AOVs' pool offset (none: NoExtraAovs): their map program, their count, then each one's label, whether
    // post scatter, the register of the map its colour is bound to (MapNoRegister: none) and its colour.
    U32 extras = 0xffffffffu;
};
constexpr U32 NoExtraAovs = 0xffffffffu, ExtraAovFloats = 6;

// UsdPreviewSurface's parameters, in its pool order.
struct UsdPreviewSurfaceParams {
    Color diffuseColor, emissiveColor, specularColor;
    float useSpecularWorkflow, metallic, roughness, clearcoat, clearcoatRoughness, opacity, opacityThreshold, ior;
    V3 normal;
};
constexpr U32 UsdPreviewSurfaceFloats = sizeof(UsdPreviewSurfaceParams) / sizeof(float);
// UsdPreviewSurface.json's labels, as the build numbers them (labels.h).
enum UsdLabels : U32 { AovDiffuse = 1, AovSpecular, AovSpecularTransmission, AovOuterSpecular };

X2_HD inline void usdMirrorDielectric(Builder& b, V3 N, float ior, float weight, float opacity, U32 reflLabel, U32 transLabel,
                                      U32 behavior) {
    MirrorBSDF m{N, ior, rgb(1), 0.0f, ior, weight, 1.0f - opacity, nullptr};
    addMirrorBSDF(b, m, 1.0f, behavior, reflLabel, transLabel);
}
X2_HD inline void usdMicrofacetDielectric(Builder& b, V3 N, float ior, float roughness, float weight, float opacity,
                                          U32 reflLabel, U32 transLabel, U32 behavior) {
    MicrofacetIsotropicBSDF m{N, ior, roughness, roughness, false, rgb(1), 0.0f, ior, weight, 1.0f - opacity, GGXDistribution,
                              nullptr};
    addMicrofacetIsotropicBSDF(b, m, 1.0f, behavior, reflLabel, transLabel);
}
// UsdPreviewSurface.ispc shade().
X2_CALL void shadeUsdPreviewSurface(const UsdPreviewSurfaceParams& p, U32 flags, const State& st, Builder& bb) {
    V3 N;
    if (isZero(length(st.dPds))) N = st.N;
    else N = normalize(localToGlobal(frame(st.N, normalize(st.dPds)), p.normal));
    const Color albedo = p.diffuseColor;
    const float ior = p.ior, roughness = saturate(p.roughness), opacityThreshold = saturate(p.opacityThreshold);
    const float opacity = opacityThreshold > 0.0f ? 1.0f : saturate(p.opacity);
    const Color emissive = p.emissiveColor;
    if (!isBlack(emissive)) addEmission(bb, emissive);
    if (!isZero(p.clearcoat)) {
        if (isZero(p.clearcoatRoughness))
            usdMirrorDielectric(bb, N, ior, p.clearcoat, 1.0f, AovOuterSpecular, AovSpecularTransmission, Additive);
        else
            usdMicrofacetDielectric(bb, N, ior, p.clearcoatRoughness, p.clearcoat, 1.0f, AovOuterSpecular, AovSpecularTransmission,
                                    Additive);
    }
    const float weight = 1.0f;
    if (p.useSpecularWorkflow != 0.0f) {
        if (flags & MatModoUsdSpecular) {
            const Color spec = {saturate(p.specularColor.x), saturate(p.specularColor.y), saturate(p.specularColor.z)};
            if (!isBlack(spec)) addSchlickReflection(bb, N, spec, roughness, isZero(roughness), AovSpecular);
        }
    } else {
        const float metallic = p.metallic;
        if (isZero(metallic)) {
            if (isZero(roughness)) usdMirrorDielectric(bb, N, ior, weight, opacity, AovSpecular, AovSpecularTransmission, Physical);
            else usdMicrofacetDielectric(bb, N, ior, roughness, weight, opacity, AovSpecular, AovSpecularTransmission, Physical);
        } else if (isOne(metallic)) {
            if (isZero(roughness)) addMirrorBRDF(bb, mirrorConductor(N, albedo, albedo), weight, Physical, AovSpecular);
            else addMicrofacetIsotropicBRDF(bb, microfacetConductor(N, albedo, albedo, roughness, GGXDistribution), weight, Physical,
                                            AovSpecular);
            return;
        } else {
            if (isZero(roughness)) {
                addMirrorBRDF(bb, mirrorConductor(N, albedo, albedo), metallic, Physical, AovSpecular);
                usdMirrorDielectric(bb, N, ior, weight, opacity, AovSpecular, AovSpecularTransmission, Physical);
            } else {
                addMicrofacetIsotropicBRDF(bb, microfacetConductor(N, albedo, albedo, roughness, GGXDistribution), metallic, Physical,
                                           AovSpecular);
                usdMicrofacetDielectric(bb, N, ior, roughness, weight, opacity, AovSpecular, AovSpecularTransmission, Physical);
            }
        }
    }
    if (!isBlack(albedo)) addLambertianBRDF(bb, LambertianBRDF{N, albedo, nullptr}, 1.0f, Physical, AovDiffuse);
}
// UsdPreviewSurface::presence: 1 where the opacity reaches the threshold, else 0.
X2_HD inline float presenceUsdPreviewSurface(const UsdPreviewSurfaceParams& p) {
    return p.opacity >= p.opacityThreshold ? 1.0f : 0.0f;
}

// The texture coordinates' derivatives at the hit (State dsdx...), from the ray's differentials
// (camera rays; the path tracer's other rays carry none, so their lookups use the finest level):
// each differential ray meets the triangle's plane, and its barycentric offset maps through the
// triangle's texture coordinates. The differentials are scaled for the samples per pixel as the
// validated ImageMap subset scales them (tex::footprint).
X2_HD inline void hitTexDerivatives(const MeshAttributes& m, U32 prim, U32 ia, U32 ib, U32 ic, V3 a, V3 b, V3 c,
                                    const surface::Ray& ray, U32 spp, State& st) {
    st.dsdx = st.dsdy = st.dtdx = st.dtdy = 0.0f;
    if (isExactlyZero(ray.dx) || isExactlyZero(ray.dy) || !spp) return;
    float st1[2] = {0, 0}, st2[2] = {1, 0}, st3[2] = {1, 1};
    if (m.uvRate != RateNone && m.uvs) {
        const U32 i1 = m.uvRate == RateVertex ? ia : prim * 3, i2 = m.uvRate == RateVertex ? ib : prim * 3 + 1,
                  i3 = m.uvRate == RateVertex ? ic : prim * 3 + 2;
        st1[0] = m.uvs[2 * i1];
        st1[1] = m.uvs[2 * i1 + 1];
        st2[0] = m.uvs[2 * i2];
        st2[1] = m.uvs[2 * i2 + 1];
        st3[0] = m.uvs[2 * i3];
        st3[1] = m.uvs[2 * i3 + 1];
    }
    const V3 e1 = b - a, e2 = c - a, n = cross(e1, e2);
    U32 axis = fabsf(n.x) > fabsf(n.y) ? 0 : 1;
    if (fabsf(n.z) > (axis == 0 ? fabsf(n.x) : fabsf(n.y))) axis = 2;
    auto pa = [&](V3 v) { return axis == 0 ? v.y : axis == 1 ? v.z : v.x; };
    auto pb = [&](V3 v) { return axis == 0 ? v.z : axis == 1 ? v.x : v.y; };
    const float det = pa(e1) * pb(e2) - pb(e1) * pa(e2), den = dot(n, ray.direction);
    if (!(fabsf(det) > 0) || !(fabsf(den) > 0)) return;
    const float plane = dot(n, a - ray.origin);
    const V3 primary = ray.direction * (plane / den);
    const float scale = 1.f / fminf(sqrtf(float(spp)), 2.f);
    const V3 directions[2] = {ray.dx, ray.dy}, offsets[2] = {ray.ox, ray.oy};
    float ds[2], dt[2];
    for (int i = 0; i < 2; ++i) {
        V3 d = directions[i];
        if (scale < 1) d = normalize(ray.direction + (d - ray.direction) * scale);
        const float dd = dot(n, d);
        if (!(fabsf(dd) > 0)) return;
        const V3 o = offsets[i] * scale;
        const V3 delta = o + d * (dot(n, a - ray.origin - o) / dd) - primary;
        const float x = (pa(delta) * pb(e2) - pb(delta) * pa(e2)) / det, y = (pa(e1) * pb(delta) - pb(e1) * pa(delta)) / det;
        ds[i] = (st2[0] - st1[0]) * x + (st3[0] - st1[0]) * y;
        dt[i] = (st2[1] - st1[1]) * x + (st3[1] - st1[1]) * y;
    }
    if (!(isfinite(ds[0]) && isfinite(ds[1]) && isfinite(dt[0]) && isfinite(dt[1]))) return;
    st.dsdx = ds[0];
    st.dtdx = dt[0];
    st.dsdy = ds[1];
    st.dtdy = dt[1];
}

// Ray::transfer: the incoming ray's auxiliary rays meet the hit's plane; dPdx and dPdy their offsets from P.
X2_HD inline void transferDifferentials(const RayDiff& d, V3 origin, V3 dir, State& st) {
    st.dPdx = st.dPdy = V3{0, 0, 0};
    st.diffValid = false;
    if (!d.valid) return;
    const V3 oX = origin + d.dOx, oY = origin + d.dOy, dX = dir + d.dDx, dY = dir + d.dDy;
    const float denomX = dot(st.Ng, dX), denomY = dot(st.Ng, dY);
    if (denomX == 0.0f || denomY == 0.0f) return;
    const float planeD = -dot(st.Ng, st.P);
    const float distX = -(dot(oX, st.Ng) + planeD) / denomX, distY = -(dot(oY, st.Ng) + planeD) / denomY;
    st.dPdx = (oX + dX * distX) - st.P;
    st.dPdy = (oY + dY * distY) - st.P;
    st.diffValid = finite3(st.dPdx) && finite3(st.dPdy);
    if (!st.diffValid) st.dPdx = st.dPdy = V3{0, 0, 0};
}
// Intersection::transferAndComputeDerivatives: the texture derivatives from dPdx and dPdy over dPds and dPdt;
// without differentials, the coarsest level (1024).
X2_HD inline void differentialTexDerivatives(State& st) {
    st.dsdx = st.dtdx = st.dsdy = st.dtdy = 0.0f;
    if (!st.diffValid) {
        st.dsdx = 1024.0f;
        st.dtdy = 1024.0f;
        return;
    }
    const float e = 1e-5f;  // sIntersectionEpsilon
    if (isZero(dot(st.dPds, st.dPdt), e)) {
        const float du = dot(st.dPds, st.dPds), dv = dot(st.dPdt, st.dPdt);
        if (du > e && dv > e) {
            const float iu = 1.0f / dot(st.dPds, st.dPds), iv = 1.0f / dot(st.dPdt, st.dPdt);
            st.dsdx = dot(st.dPdx, st.dPds) * iu;
            st.dtdx = dot(st.dPdx, st.dPdt) * iv;
            st.dsdy = dot(st.dPdy, st.dPds) * iu;
            st.dtdy = dot(st.dPdy, st.dPdt) * iv;
        }
        return;
    }
    // Drop the normal's largest axis and solve the 2x2 system (pbrt 2nd ed. p. 508).
    const V3 n2 = st.Ng * st.Ng;
    float A[4], bx[2], by[2];
    if (n2.x > n2.y && n2.x > n2.z) {
        A[0] = st.dPds.y; A[1] = st.dPdt.y; A[2] = st.dPds.z; A[3] = st.dPdt.z;
        bx[0] = st.dPdx.y; bx[1] = st.dPdx.z; by[0] = st.dPdy.y; by[1] = st.dPdy.z;
    } else if (n2.y > n2.z) {
        A[0] = st.dPds.x; A[1] = st.dPdt.x; A[2] = st.dPds.z; A[3] = st.dPdt.z;
        bx[0] = st.dPdx.x; bx[1] = st.dPdx.z; by[0] = st.dPdy.x; by[1] = st.dPdy.z;
    } else {
        A[0] = st.dPds.x; A[1] = st.dPdt.x; A[2] = st.dPds.y; A[3] = st.dPdt.y;
        bx[0] = st.dPdx.x; bx[1] = st.dPdx.y; by[0] = st.dPdy.x; by[1] = st.dPdy.y;
    }
    const float det = A[0] * A[3] - A[1] * A[2];
    if (isZero(det, e)) return;
    // solve2x2LinearSystem
    const float detA = differenceOfProducts(A[0], A[3], A[1], A[2]);
    if (!(fabsf(detA) >= 1.17549435e-38f) || !(fabsf(detA) <= 3.402823466e38f)) return;
    const float inv = 1.0f / detA;
    st.dsdx = differenceOfProducts(bx[0], A[3], bx[1], A[1]) * inv;
    st.dtdx = differenceOfProducts(bx[1], A[0], bx[0], A[2]) * inv;
    st.dsdy = differenceOfProducts(by[0], A[3], by[1], A[1]) * inv;
    st.dtdy = differenceOfProducts(by[1], A[0], by[0], A[2]) * inv;
}
// getdNdx and getdNdy: the shading normal across the footprint, from the vertex normals' st partials
// (TriMesh::computeIntersectCurvature); zero without vertex normals.
X2_HD inline void normalDifferentials(const MeshAttributes& m, U32 prim, U32 ia, U32 ib, U32 ic, State& st) {
    st.dNdx = st.dNdy = V3{0, 0, 0};
    if (m.normalRate == RateNone || !m.normals) return;
    float st1[2] = {0, 0}, st2[2] = {1, 0}, st3[2] = {1, 1};
    if (m.uvRate != RateNone && m.uvs) {
        const U32 i1 = m.uvRate == RateVertex ? ia : prim * 3, i2 = m.uvRate == RateVertex ? ib : prim * 3 + 1,
                  i3 = m.uvRate == RateVertex ? ic : prim * 3 + 2;
        st1[0] = m.uvs[2 * i1];
        st1[1] = m.uvs[2 * i1 + 1];
        st2[0] = m.uvs[2 * i2];
        st2[1] = m.uvs[2 * i2 + 1];
        st3[0] = m.uvs[2 * i3];
        st3[1] = m.uvs[2 * i3 + 1];
    }
    const U32 n1 = m.normalRate == RateVertex ? ia : prim * 3, n2 = m.normalRate == RateVertex ? ib : prim * 3 + 1,
              n3 = m.normalRate == RateVertex ? ic : prim * 3 + 2;
    V3 dNds, dNdt;
    if (!trianglePartials(m.normals[n1], m.normals[n2], m.normals[n3], st1, st2, st3, dNds, dNdt)) return;
    const float sign = st.entering ? 1.0f : -1.0f;
    const V3 auxX = normalize(st.N * sign + dNds * st.dsdx + dNdt * st.dtdx);
    const V3 auxY = normalize(st.N * sign + dNds * st.dsdy + dNdt * st.dtdy);
    st.dNdx = auxX * sign - st.N;
    st.dNdy = auxY * sign - st.N;
    if (!finite3(st.dNdx) || !finite3(st.dNdy)) st.dNdx = st.dNdy = V3{0, 0, 0};
}
// The texture derivatives times textureDiffScale (transferAndComputeDerivatives' last step), before dNdx and dNdy.
X2_HD inline void scaleTexDerivatives(State& st) {
    if (st.textureDiffScale == 1.0f) return;
    st.dsdx *= st.textureDiffScale;
    st.dsdy *= st.textureDiffScale;
    st.dtdx *= st.textureDiffScale;
    st.dtdy *= st.textureDiffScale;
}
// The hit's differentials: a camera ray's texture derivatives as the validated subset computes them, and
// its auxiliary rays scaled for the samples per pixel (PathIntegrator::initPrimaryRay) as the incoming
// differentials; any other ray's transferred (MoonRay's texture derivatives); then dNdx and dNdy.
X2_HD inline void hitDifferentials(const MeshAttributes& m, U32 prim, U32 ia, U32 ib, U32 ic, V3 a, V3 b, V3 c,
                                   const surface::Ray& ray, U32 spp, State& st) {
    if (!isExactlyZero(ray.dx) && !isExactlyZero(ray.dy) && spp) {
        hitTexDerivatives(m, prim, ia, ib, ic, a, b, c, ray, spp, st);
        const float scale = 1.f / fminf(sqrtf(float(spp)), 2.f);
        RayDiff d;
        d.dOx = ray.ox * scale;
        d.dOy = ray.oy * scale;
        d.dDx = normalize(ray.direction + (ray.dx - ray.direction) * scale) - ray.direction;
        d.dDy = normalize(ray.direction + (ray.dy - ray.direction) * scale) - ray.direction;
        d.valid = 1;
        st.incoming = d;
        transferDifferentials(d, ray.origin, ray.direction, st);
    } else {
        transferDifferentials(st.incoming, ray.origin, ray.direction, st);
        differentialTexDerivatives(st);
    }
    scaleTexDerivatives(st);
    normalDifferentials(m, prim, ia, ib, ic, st);
}
// LineSegments::postIntersect and CubicSpline::postIntersect: a curve hit's shading state. St is the "st" or "uv"
// primitive attribute, else the span's share of its curve and v across it; dPds is the tangent (a cubic's from
// its derivative weights); N faces the ray (always on a linear curve, whose round program's normal MoonRay leaves
// unused), or is a round cubic's geometric normal. The geometric normal is the shading normal.
X2_CALL bool curveState(const MeshAttributes& m, U32 span, float u, float v, V3 roundNg, V3 P, V3 rayDir, State& st) {
    const curves::Set& c = m.curve;
    if (span >= c.spanCount) return false;
    const U32 vertex = curves::spanVertex(c, span), chain = curves::spanCurve(c, span), index = curves::spanIndex(c, span);
    st.curve = c.basis;
    st.chain = chain;
    st.varying = chain + span;
    st.prim = span;
    st.u = u;
    st.v = v;
    st.ia = st.ib = st.ic = vertex;
    st.prims = m.prims;
    st.primData = m.primData;
    st.primCount = m.primCount;
    float uv[3];
    if (primValue(st, primKey("st", PrimVec2f), uv) || primValue(st, primKey("uv", PrimVec2f), uv)) {
        st.s = uv[0];
        st.t = uv[1];
    } else {
        const float stSpanRange = 1.0f / float(c.curveSpans[chain]);
        const float ststart = stSpanRange * float(index);
        st.s = ststart + u * stSpanRange;
        st.t = v * 0.5f + 0.5f;  // v is in (-1,1)
    }
    const curves::float4 cp0 = curves::point(c, vertex), cp1 = curves::point(c, vertex + 1);
    V3 dPds, dPdt, N;
    const V3 flippedRayDir = normalize(-rayDir);
    const bool rayFacing = c.basis == curves::BasisLinear || !c.round;
    if (c.basis == curves::BasisLinear) {
        dPds = V3{cp1.x - cp0.x, cp1.y - cp0.y, cp1.z - cp0.z};
    } else {
        const curves::float4 cp[4] = {cp0, cp1, curves::point(c, vertex + 2), curves::point(c, vertex + 3)};
        dPds = curves::cubicTangent(c.basis, cp, u);
    }
    if (rayFacing) {
        dPdt = cross(dPds, flippedRayDir);
        if (dot(dPdt, dPdt) < Epsilon) {  // clustered points, or the ray along the curve
            N = flippedRayDir;
            const Frame f = frame(N);
            dPds = f.x;
            dPdt = f.y;
        } else {
            N = cross(dPdt, dPds);
        }
        N = normalize(N);
    } else {
        N = normalize(roundNg);
        dPdt = cross(dPds, N);
        if (dot(dPdt, dPdt) < Epsilon) {
            const Frame f = frame(N);
            dPds = f.x;
            dPdt = f.y;
        }
    }
    st.Ng = N;
    st.dPds = dPds;
    st.dPdt = dPdt;
    st.P = P;
    st.wo = -rayDir;
    // initIntersectionPhase1: N and Ng flipped to face the viewer when the ray leaves the surface.
    st.entering = dot(N, rayDir) < 0.0f;
    if (!st.entering) N = -N;
    st.N = N;
    st.Ng = N;
    return finite3(st.N) && finite3(st.dPds);
}
// A curve hit's differentials (Intersection::transferAndComputeDerivatives over the hit's dPds and dPdt) and
// curvature: computeIntersectCurvature gives a linear curve dNds zero and dNdt its dPdt, a cubic both zero.
X2_HD inline void curveDifferentials(const MeshAttributes& m, const surface::Ray& ray, U32 spp, State& st) {
    if (!isExactlyZero(ray.dx) && !isExactlyZero(ray.dy) && spp) {
        const float scale = 1.f / fminf(sqrtf(float(spp)), 2.f);
        RayDiff d;
        d.dOx = ray.ox * scale;
        d.dOy = ray.oy * scale;
        d.dDx = normalize(ray.direction + (ray.dx - ray.direction) * scale) - ray.direction;
        d.dDy = normalize(ray.direction + (ray.dy - ray.direction) * scale) - ray.direction;
        d.valid = 1;
        st.incoming = d;
    }
    transferDifferentials(st.incoming, ray.origin, ray.direction, st);
    differentialTexDerivatives(st);
    scaleTexDerivatives(st);
    st.dNdx = st.dNdy = V3{0, 0, 0};
    if (m.curve.basis != curves::BasisLinear) return;
    const V3 dNdt = st.dPdt;
    const float sign = st.entering ? 1.0f : -1.0f;
    const V3 auxX = normalize(st.N * sign + dNdt * st.dtdx);
    const V3 auxY = normalize(st.N * sign + dNdt * st.dtdy);
    st.dNdx = auxX * sign - st.N;
    st.dNdy = auxY * sign - st.N;
    if (!finite3(st.dNdx) || !finite3(st.dNdy)) st.dNdx = st.dNdy = V3{0, 0, 0};
}
// scatterAndScale: a BSDF sample's ray differentials, from the hit's and the lobe's differentials function;
// a lobe that ignores the incoming differentials scales them by the primary rays' scale.
X2_HD inline bool lobeIgnoresIncomingDifferentials(const Bsdf& b, U32 record) {
    const Lobe* l = &b.records[record];
    for (int k = 0; k < 8 && (l->kind == KindUnder || l->kind == KindUnderClearcoat || l->kind == KindUnderClearcoatTransmission) &&
                    l->child != NoIndex;
         ++k)
        l = &b.records[l->child];
    if (l->kind == KindIridescence) return false;
    return (l->flags & FlagIgnoresIncomingDifferentials) != 0;
}
X2_HD inline RayDiff scatterDifferentials(const Bsdf& b, U32 record, const State& st, V3 wi, float r1, float r2, V3 childOrigin,
                                          float primaryScale) {
    RayDiff d;
    if (!st.diffValid) return d;
    V3 dDdx = st.incoming.dDx, dDdy = st.incoming.dDy;
    lobeDifferentials(b, record, st.wo, wi, r1, r2, st.dNdx, st.dNdy, dDdx, dDdy);
    const float scale = lobeIgnoresIncomingDifferentials(b, record) ? primaryScale : 1.0f;
    const V3 shift = st.P - childOrigin;
    d.dOx = st.dPdx * scale + shift;
    d.dOy = st.dPdy * scale + shift;
    d.dDx = normalize(wi + dDdx * scale) - wi;
    d.dDy = normalize(wi + dDdy * scale) - wi;
    d.valid = finite3(d.dOx) && finite3(d.dOy) && finite3(d.dDx) && finite3(d.dDy) ? 1u : 0u;
    return d;
}

// SwitchMaterial and RaySwitchMaterial (moonray dso/material): copies of their materials' records (kind 0 for none).
// A SwitchMaterial shades its chosen material (def). A RaySwitchMaterial is replaced once, by the integrator, with
// the material for the type of the lobe whose sample the ray is (PathIntegratorUtil lobeTypeToRayType: none for a
// camera ray, then diffuse, mirror, glossy in that order); shaded itself it shades its default material, or, cutting
// out camera rays, ends a primary path (BsdfBuilder early termination) after its default material's presence.
struct SwitchRecord {
    U32 byRay, cutout, pad[2];
    MaterialRecord def, camera, mirror, glossy, diffuse;
};
constexpr U32 SwitchRecordFloats = sizeof(SwitchRecord) / sizeof(float);
X2_HD inline const MaterialRecord* resolveSwitch(const MaterialRecord& m, const float* pool, const State& st, bool& cutout) {
    const MaterialRecord* cur = &m;
    bool first = true;
    for (U32 hop = 0; hop < 16 && cur && cur->kind == MatSwitch; ++hop) {
        if (cur->count < SwitchRecordFloats) return nullptr;
        const SwitchRecord& s = *reinterpret_cast<const SwitchRecord*>(pool + cur->offset);
        const MaterialRecord* next = nullptr;
        if (first && s.byRay) {
            const U32 t = st.rayLobe;
            if (t == 0) next = s.cutout ? nullptr : &s.camera;
            else if (t & Diffuse) next = &s.diffuse;
            else if (t & Mirror) next = &s.mirror;
            else if (t & Glossy) next = &s.glossy;
            if (next && next->kind == 0) next = nullptr;
        }
        first = false;
        if (!next) {
            if (s.byRay && s.cutout && st.pathType == PathPrimary) cutout = true;
            next = s.def.kind ? &s.def : nullptr;
        }
        cur = next;
    }
    return cur && cur->kind != MatSwitch ? cur : nullptr;
}

// Runs a material into a Bsdf: its maps, then the material over its bound values. The status is
// a texture lookup's: Ready, Miss (a tile is on its way: try the sample again later) or Invalid
// (the material is unknown, its Bsdf overflowed, or it needs what is not shaded yet).
template <class Tex>
X2_CALL U32 shadeChosenMaterial(const MaterialRecord& m, const float* pool, const State& st, const Tex& tex, Bsdf& bsdf, float& presence,
                                DwaParams* slots, GlitterScratch* glitter, bool cutout);
template <class Tex>
X2_CALL U32 shadeRootMaterial(const MaterialRecord& m, const float* pool, const State& st, const Tex& tex, Bsdf& bsdf, float& presence,
                              DwaParams* slots, GlitterScratch* glitter) {
    bool cutout = false;
    if (m.kind == MatSwitch) {
        const MaterialRecord* chosen = resolveSwitch(m, pool, st, cutout);
        if (!chosen) {  // nothing to shade: no lobes (presence one)
            presence = 1.0f;
            if (cutout) bsdf.earlyTermination = true;
            return tex::Ready;
        }
        return shadeChosenMaterial(*chosen, pool, st, tex, bsdf, presence, slots, glitter, cutout);
    }
    return shadeChosenMaterial(m, pool, st, tex, bsdf, presence, slots, glitter, false);
}
// The root material's extra AOVs at the hit (aovAccumExtraAovs and the post scatter ones' values): each one's colour,
// times its bound map's result where its colour is not black (evalColor).
template <class Tex>
X2_CALL U32 extraAovValues(const MaterialRecord& m, const float* pool, const State& st, const Tex& tex, Bsdf& bsdf) {
    const U32* w = reinterpret_cast<const U32*>(pool + m.extras);
    const U32 program = w[0], count = w[1] < Bsdf::MaxExtraAovs ? w[1] : Bsdf::MaxExtraAovs;
    Color regs[MapMaxRegisters];
    if (program != NoMapProgram) {
        const U32 status = runMapProgram(pool, program, st, tex, regs);
        if (status != tex::Ready) return status;
    }
    const float* e = pool + m.extras + 2;
    for (U32 i = 0; i < count; ++i, e += ExtraAovFloats) {
        const U32* ew = reinterpret_cast<const U32*>(e);
        Color v{e[3], e[4], e[5]};
        if (ew[2] != MapNoRegister && !isBlack(v)) v = v * regs[ew[2]];
        bsdf.extraLabel[i] = int(ew[0]);
        bsdf.extraValue[i] = v;
        if (ew[1]) bsdf.extraPost |= 1u << i;
    }
    bsdf.extraCount = count;
    return tex::Ready;
}
template <class Tex>
X2_CALL U32 shadeMaterial(const MaterialRecord& m, const float* pool, const State& st, const Tex& tex, Bsdf& bsdf, float& presence,
                          DwaParams* slots, GlitterScratch* glitter = nullptr) {
    const U32 status = shadeRootMaterial(m, pool, st, tex, bsdf, presence, slots, glitter);
    if (status != tex::Ready || m.extras == NoExtraAovs || bsdf.fatal || bsdf.earlyTermination) return status;
    return extraAovValues(m, pool, st, tex, bsdf);
}
// A material's presence alone (shading::presence, for presence shadows): its maps run, no lobes made.
template <class Tex>
X2_CALL U32 materialPresence(const MaterialRecord& m0, const float* pool, const State& st, const Tex& tex, float& presence) {
    presence = 1.0f;
    const MaterialRecord* m = &m0;
    if (m0.kind == MatSwitch) {
        bool cutout = false;
        m = resolveSwitch(m0, pool, st, cutout);
        if (!m) return tex::Ready;
    }
    Color regs[MapMaxRegisters];
    if (m->maps != NoMapProgram) {
        if (!mapRequirementsMet(pool, m->maps, st)) return tex::Ready;
        const U32 status = runMapProgram(pool, m->maps, st, tex, regs);
        if (status != tex::Ready) return status;
    }
    if (m->kind == MatUsdPreviewSurface && m->count >= UsdPreviewSurfaceFloats) {
        UsdPreviewSurfaceParams p = *reinterpret_cast<const UsdPreviewSurfaceParams*>(pool + m->offset);
        applyBindings(reinterpret_cast<float*>(&p), reinterpret_cast<const MapBinding*>(pool + m->bindings), m->bindingCount, regs);
        presence = presenceUsdPreviewSurface(p);
    } else if (m->kind == MatDwaBase && m->count >= DwaTreeFloats) {
        presence = dwaTreePresence(pool, *reinterpret_cast<const DwaTree*>(pool + m->offset), st, regs);
    }
    return tex::Ready;
}
template <class Tex>
X2_CALL U32 shadeChosenMaterial(const MaterialRecord& m, const float* pool, const State& st, const Tex& tex, Bsdf& bsdf, float& presence,
                                DwaParams* slots, GlitterScratch* glitter, bool cutout) {
    Color regs[MapMaxRegisters];
    // A hit without an attribute its maps require: the fatal colour, and the path ends (hasAllRequiredAttributes).
    if (m.maps != NoMapProgram && !mapRequirementsMet(pool, m.maps, st)) {
        Builder fatal(bsdf, st);
        presence = 1.0f;
        addEmission(fatal, Color{1.0f, 0.0f, 1.0f});
        bsdf.fatal = true;
        return tex::Ready;
    }
    if (m.maps != NoMapProgram) {
        const U32 status = runMapProgram(pool, m.maps, st, tex, regs);
        if (status != tex::Ready) return status;
    }
    Builder bb(bsdf, st);
    if (m.labels != 0xffffffffu) {
        bb.labels = reinterpret_cast<const U32*>(pool + m.labels);
        bsdf.materialLabels = encodeLabel(bb, 0);
    }
    presence = 1.0f;
    switch (m.kind) {
    case MatUsdPreviewSurface: {
        if (m.count < UsdPreviewSurfaceFloats) return tex::Invalid;
        UsdPreviewSurfaceParams p = *reinterpret_cast<const UsdPreviewSurfaceParams*>(pool + m.offset);
        applyBindings(reinterpret_cast<float*>(&p), reinterpret_cast<const MapBinding*>(pool + m.bindings), m.bindingCount, regs);
        presence = presenceUsdPreviewSurface(p);
        if (presence <= 0.0f) return tex::Ready;  // a cut out: the integrator continues through it
        if (cutout) {
            bsdf.earlyTermination = true;
            return tex::Ready;
        }
        shadeUsdPreviewSurface(p, m.flags, st, bb);
        break;
    }
    case MatDwaBase: {
        if (m.count < DwaTreeFloats || !slots) return tex::Invalid;
        const DwaTree& tree = *reinterpret_cast<const DwaTree*>(pool + m.offset);
        // A geometry without a required attribute shades as the fatal colour (validateRequiredAttributes).
        if (tree.requiresRefP && !primProvided(st, primKey("ref_P", PrimVec3f))) {
            addEmission(bb, Color{1.0f, 0.0f, 1.0f});
            bsdf.fatal = true;
            return tex::Ready;
        }
        presence = dwaTreePresence(pool, tree, st, regs);
        if (fabsf(presence) <= 1e-6f) return tex::Ready;  // nothing of it shows (isEqual(presence, 0))
        if (cutout) {
            bsdf.earlyTermination = true;
            return tex::Ready;
        }
        initColorCorrectParameters(slots[0]);
        // A material whose resolve fails (a missing input) gives no lobes, as in MoonRay.
        if (resolveDwaTree(pool, tree, st, slots, regs) && !createDwaLobes(slots[0], tree.up, st, bb, pool, glitter)) return tex::Invalid;
        break;
    }
    default: return tex::Invalid;
    }
    return bb.overflow ? tex::Invalid : tex::Ready;
}
}}}
