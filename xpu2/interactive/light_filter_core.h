// MoonRay's light filters for the path tracer, shared by the CPU and CUDA lanes: intensity, decay, colour ramp, rod,
// barn door, cookie (a map shader's) and cookie v2 (a texture's), and combine (pbr/lightfilter/*.ispc, the vector
// mode's). A light's filter list (Scene::buildLightFilterTables: the light's light_filters, those of the assignment's
// LightFilterSet where it has one) multiplies its radiance wherever a shading point evaluates it (Light::eval's
// LightFilterList_eval) and culls it where a filter says it cannot light the point (canIlluminateLightFilterList).
//
// Adapted from MoonRay pbr/lightfilter, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC; see
// MOONRAY_LICENSE.txt. XPU2 shades in world space: what MoonRay keeps in render space is kept in world space here.
#pragma once
#include "light_core.h"
#include "shade_color.h"

namespace xpu2::interactive::lights {

enum FilterKind : U32 {
    FilterNone = 0, FilterIntensity, FilterDecay, FilterColorRamp, FilterRod, FilterBarnDoor, FilterCookie, FilterCookie2,
    FilterCombine, FilterVdb
};
// LightFilter.hh's enums.
enum : U32 {
    PathsAll = 0, PathsAllIndirect, PathsAllIndirectFirst, PathsIndirectDiffuse, PathsIndirectDiffuseFirst,
    PathsIndirectSpecular, PathsIndirectSpecularFirst
};
enum : U32 { RampRadial = 0, RampDirectional = 1 };
enum : U32 { WrapExtend = 0, WrapMirror = 1 };
enum : U32 { CombineMultiply = 0, CombineMin, CombineMax, CombineAdd, CombineSubtract };
enum : U32 { OutsideBlack = 0, OutsideWhite, OutsideDefault };
enum : U32 { BlurGaussian = 0, BlurCircular = 1 };
enum : U32 { BarnAnalytic = 0, BarnPhysical = 1 };
enum : U32 { FilterMbTranslation = 1u, FilterMbRotation = 2u, FilterMbScale = 4u };
constexpr U32 FilterMaxChildren = 8, FilterMaxList = 16;

// A row-vector 3x3 matrix and an affine 3x4 (rows 0-2 linear, row 3 translation), as scene_rdl2's Mat3f and Xform3f.
struct M3 { V3 r[3]; };
struct X34 { V3 r[4]; };
X2_HD inline V3 m3Apply(V3 v, const M3& m) {  // v * m
    return V3{v.x * m.r[0].x + v.y * m.r[1].x + v.z * m.r[2].x, v.x * m.r[0].y + v.y * m.r[1].y + v.z * m.r[2].y,
              v.x * m.r[0].z + v.y * m.r[1].z + v.z * m.r[2].z};
}
X2_HD inline M3 m3Mul(const M3& a, const M3& b) {  // a * b
    M3 m;
    for (int i = 0; i < 3; ++i) m.r[i] = m3Apply(a.r[i], b);
    return m;
}
X2_HD inline M3 m3Transpose(const M3& a) {
    M3 m;
    m.r[0] = V3{a.r[0].x, a.r[1].x, a.r[2].x};
    m.r[1] = V3{a.r[0].y, a.r[1].y, a.r[2].y};
    m.r[2] = V3{a.r[0].z, a.r[1].z, a.r[2].z};
    return m;
}
X2_HD inline M3 m3Lerp(const M3& a, const M3& b, float t) {
    M3 m;
    for (int i = 0; i < 3; ++i) m.r[i] = surface::add(surface::mul(a.r[i], 1.0f - t), surface::mul(b.r[i], t));
    return m;
}
X2_HD inline M3 m3Inverse(const M3& a) {
    const V3 c0 = surface::cross(a.r[1], a.r[2]), c1 = surface::cross(a.r[2], a.r[0]), c2 = surface::cross(a.r[0], a.r[1]);
    const float det = surface::dot(a.r[0], c0), inv = 1.0f / det;
    M3 m;
    m.r[0] = V3{c0.x * inv, c1.x * inv, c2.x * inv};
    m.r[1] = V3{c0.y * inv, c1.y * inv, c2.y * inv};
    m.r[2] = V3{c0.z * inv, c1.z * inv, c2.z * inv};
    return m;
}
X2_HD inline V3 x34Point(const X34& x, V3 p) { return surface::add(m3Apply(p, M3{{x.r[0], x.r[1], x.r[2]}}), x.r[3]); }
X2_HD inline V3 x34Vector(const X34& x, V3 v) { return m3Apply(v, M3{{x.r[0], x.r[1], x.r[2]}}); }
// scene_rdl2 transformH: (p, 1) times a 4x4 over its w.
X2_HD inline V3 m44H(const float m[16], V3 p) {
    const float x = p.x * m[0] + p.y * m[4] + p.z * m[8] + m[12], y = p.x * m[1] + p.y * m[5] + p.z * m[9] + m[13],
                z = p.x * m[2] + p.y * m[6] + p.z * m[10] + m[14], w = p.x * m[3] + p.y * m[7] + p.z * m[11] + m[15];
    if (w == 0.0f) return V3{0, 0, 0};
    return V3{x / w, y / w, z / w};
}

// One filter (LightFilter.hh's members of each kind, in one record).
struct Filter {
    U32 kind = FilterNone, mode = 0, wrap = 0, pathSelection = 0, invert = 0, mb = 0, useXform = 0, useLightXform = 0;
    V3 color{1, 1, 1};
    float intensity = 1.0f, density = 1.0f;
    // Decay.
    U32 falloffNear = 0, falloffFar = 0;
    float nearStart = 0, nearEnd = 0, farStart = 0, farEnd = 0;
    // Colour ramp: world to the filter's space at the shutter's open and close; its ramp.
    X34 xform[2];
    shade::ColorRamp colorRamp;
    // Rod and barn door: their transforms (updateTransforms: the open's inverse, its rotation's and scale's inverses,
    // and both ends' positions, orientations and scales for motion).
    X34 render2Local0;
    M3 render2LocalRot0, render2LocalScale0, local2RenderScale[2], render2LocalRotAndScale;
    V3 position[2];
    float orientation[2][4];
    // Rod.
    V3 boxCorner{0, 0, 0};
    float radius = 0, edge = 0, edgeInv = 1, radiusEdgeSum = 0;
    shade::FloatRamp ramp;
    // Barn door.
    float projector2Screen[16];
    float minCorner[2], maxCorner[2], reciprocalEdgeScales[4];
    float focalDist = 1, preBarnDist = 0;
    U32 preBarnMode = OutsideDefault;
    // Cookies: render (world) to screen at both ends, the projector's place and direction at both ends, the blur.
    float projectorR2S[2][16];
    V3 projectorPos[2], projectorDir[2];
    float blurNearDistance = 0, blurMidpoint = 0, blurFarDistance = 0, blurNearValue = 0, blurMidValue = 0, blurFarValue = 0;
    U32 blurType = BlurGaussian, outside = OutsideBlack;
    // Cookie v2: its texture (null: the fallback colour); cookie: its map shader's program (shade_maps.h; ~0u none).
    const Image* image = nullptr;
    V3 fallback{1, 1, 1};
    U32 mapProgram = 0xffffffffu, mapRegister = 0;
    // VDB: its density grid (the plan's volume grids; ~0u: density 1), its interpolation, render to VDB space at both
    // ends, its blur radius (blurType 0 gaussian, 1 spherical); its tint in color, its remap in ramp.
    U32 vdbGrid = 0xffffffffu, vdbInterpolation = 0;
    X34 vdbR2V[2];
    float vdbBlur = 0;
    // Combine: its children (filter indices).
    U32 children[FilterMaxChildren];
    U32 childCount = 0;
    U32 needsSamples = 0;
};
// The filters of a light at a shading point (LightFilterList): indices into the filters, and whether any reads its
// light's transform (needsLightXform).
struct FilterList {
    U32 items[FilterMaxList];
    U32 count = 0, needsSamples = 0;
};

// What a filter reads of the shading point and the light (CanIlluminateData, EvalData). depths: the path vertex's
// diffuse, glossy and mirror depths (doesLightPathSelectionMatch), none for a camera ray (pv null in MoonRay).
struct FilterPoint {
    V3 p;                 // the shading point
    float radius = 0;     // canIlluminate: its radius
    float time = 0;
    V3 lightPosition, lightDirection;
    float lightRadius = 0;
    X34 lightRender2Local;  // the light's render to local transform (getXformRender2Local)
    V3 wi{0, 0, 0};         // eval: the incoming light's direction (-wi of the sample, EvalData::wi)
    float distance = 0;     // eval: the light intersection's distance
    float r2[2] = {0, 0};   // eval: LightFilterRandomValues
    float r3[3] = {0, 0, 0};
    bool hasPath = false;
    U32 diffuseDepth = 0, glossyDepth = 0, mirrorDepth = 0;
};

X2_HD inline bool pathSelected(U32 selection, const FilterPoint& d) {
    if (!d.hasPath) return true;
    switch (selection) {
    case PathsAll: return true;
    case PathsAllIndirect: return d.diffuseDepth + d.glossyDepth + d.mirrorDepth > 0;
    case PathsAllIndirectFirst: return d.diffuseDepth + d.glossyDepth + d.mirrorDepth == 1;
    case PathsIndirectDiffuse: return d.diffuseDepth > 0;
    case PathsIndirectDiffuseFirst: return d.diffuseDepth == 1;
    case PathsIndirectSpecular: return d.glossyDepth + d.mirrorDepth > 0;
    case PathsIndirectSpecularFirst: return d.glossyDepth + d.mirrorDepth == 1;
    default: return false;
    }
}

// The rod's and barn door's render (world) to local transform at a time (slerpPointRender2Local, getXformRender2Local).
X2_HD inline M3 filterRotation(const Filter& f, float time) {
    float q[4];
    lightSlerp(f.orientation[0], f.orientation[1], time, q);
    V3 rows[3];
    quaternionRows(q, rows);
    return m3Transpose(M3{{rows[0], rows[1], rows[2]}});
}
X2_HD inline V3 filterRender2Local(const Filter& f, V3 p, float time) {
    if (!f.mb) return x34Point(f.render2Local0, p);
    const V3 t = surface::mul((f.mb & FilterMbTranslation) ? surface::add(surface::mul(f.position[0], 1.0f - time), surface::mul(f.position[1], time))
                                                           : f.position[0],
                              -1.0f);
    const M3 r = (f.mb & FilterMbRotation) ? filterRotation(f, time) : f.render2LocalRot0;
    const M3 s = (f.mb & FilterMbScale) ? m3Inverse(m3Lerp(f.local2RenderScale[0], f.local2RenderScale[1], time)) : f.render2LocalScale0;
    return m3Apply(m3Apply(surface::add(p, t), r), s);
}
// BarnDoorLightFilter_getXformRender2Local: translate, then rotation times scale.
X2_HD inline X34 barnRender2Local(const Filter& f, float time) {
    if (!f.mb) return f.render2Local0;
    const V3 trans = surface::mul((f.mb & FilterMbTranslation) ? surface::add(surface::mul(f.position[0], 1.0f - time), surface::mul(f.position[1], time))
                                                               : f.position[0],
                                  -1.0f);
    const M3 rot = (f.mb & FilterMbRotation) ? filterRotation(f, time) : f.render2LocalRot0;
    const M3 scale = (f.mb & FilterMbScale) ? m3Inverse(m3Lerp(f.local2RenderScale[0], f.local2RenderScale[1], time)) : f.render2LocalScale0;
    const M3 l = m3Mul(rot, scale);
    // Xform(identity, trans) * Xform(l, 0): p -> (p + trans) * l.
    X34 x;
    x.r[0] = l.r[0];
    x.r[1] = l.r[1];
    x.r[2] = l.r[2];
    x.r[3] = m3Apply(trans, l);
    return x;
}

// Rod: isOutsideInfluence and the rounded box's signed distance.
X2_HD inline bool rodOutside(const Filter& f, V3 p, float rad) {
    if (f.mb) return false;
    const V3 l = m3Apply(surface::add(p, surface::mul(f.position[0], -1.0f)), f.render2LocalRotAndScale);
    const V3 a{fabsf(l.x), fabsf(l.y), fabsf(l.z)};
    float buf = f.radiusEdgeSum + rad;
    if (f.invert) buf = -buf;
    bool out = a.x > f.boxCorner.x + buf || a.y > f.boxCorner.y + buf || a.z > f.boxCorner.z + buf;
    if (f.invert) out = !out;
    return out;
}
X2_HD inline float rodDistance(const Filter& f, V3 p) {
    const V3 q{fabsf(p.x) - f.boxCorner.x, fabsf(p.y) - f.boxCorner.y, fabsf(p.z) - f.boxCorner.z};
    const V3 m{fmaxf(q.x, 0.0f), fmaxf(q.y, 0.0f), fmaxf(q.z, 0.0f)};
    return sqrtf(surface::dot(m, m)) + fminf(fmaxf(fmaxf(q.x, q.y), q.z), 0.0f) - f.radius;
}
X2_HD inline bool isBlackColor(V3 c) { return c.x == 0.0f && c.y == 0.0f && c.z == 0.0f; }

// pbr/core/Util quadraticBSplineWarp (the camera's gaussian filter warp) and toUnitDisk, for the cookies' blur.
X2_HD inline float quadraticBSplineWarp(float r) {
    if (r < 1.0f / 6.0f) return powf(6.0f * r, 1.0f / 3.0f) - 3.0f / 2.0f;
    if (r < 5.0f / 6.0f) {
        float u = (6.0f * r - 3.0f) / 4.0f;
        for (int j = 0; j < 4; ++j) u = (8.0f * u * u * u - 12.0f * r + 6.0f) / (12.0f * u * u - 9.0f);
        return u;
    }
    return 3.0f / 2.0f - powf(6.0f * (1.0f - r), 1.0f / 3.0f);
}
X2_HD inline void filterUnitDisk(float& u, float& v) {
    if (u == 0.5f && v == 0.5f) {
        u = v = 0.0f;
        return;
    }
    const float a = 2.0f * u - 1.0f, b = 2.0f * v - 1.0f;
    float phi, r;
    if (fabsf(a) > fabsf(b)) {
        r = a;
        phi = (Pi / 4.0f) * (b / a);
    } else {
        r = b;
        phi = (Pi / 2.0f) - (Pi / 4.0f) * (a / b);
    }
    u = r * cosf(phi);
    v = r * sinf(phi);
}
// The cookies' blur radius at a distance from the projector.
X2_HD inline float cookieBlur(const Filter& f, float d) {
    if (d <= f.blurNearDistance) return f.blurNearValue;
    if (d <= f.blurMidpoint) {
        const float dt = f.blurMidpoint - f.blurNearDistance;
        return dt > 0.0f ? f.blurNearValue + (f.blurMidValue - f.blurNearValue) * ((d - f.blurNearDistance) / dt) : f.blurMidValue;
    }
    if (d <= f.blurFarDistance) {
        const float dt = f.blurFarDistance - f.blurMidpoint;
        return dt > 0.0f ? f.blurMidValue + (f.blurFarValue - f.blurMidValue) * ((d - f.blurMidpoint) / dt) : f.blurFarValue;
    }
    return f.blurFarValue;
}
// BarnDoorLightFilter_gaussianBlur.
X2_HD inline float barnBlur(float t) {
    t = 1.0f - 2.0f * t;
    const float variance = 0.1f;
    const float val = 0.5f * (1.0f + erff(t / (sqrtf(variance) * sqrtf(2.0f))));
    const float minVal = 0.0007862747f;
    return val * (1.0f + 2.0f * minVal) - minVal;
}

// canIlluminate of a leaf filter (not a combine).
X2_HD inline bool filterCanIlluminateLeaf(const Filter& f, const FilterPoint& d) {
    switch (f.kind) {
    case FilterIntensity: return !pathSelected(f.pathSelection, d) || !isBlackColor(f.color);
    case FilterDecay: {
        const float distance = sqrtf(surface::dot(surface::add(d.lightPosition, surface::mul(d.p, -1.0f)),
                                                  surface::add(d.lightPosition, surface::mul(d.p, -1.0f))));
        const float buffer = d.lightRadius + d.radius;
        const float minDistance = buffer > distance ? 0.0f : distance - buffer, maxDistance = distance + buffer;
        bool ok = true;
        if (f.falloffNear) ok = ok && maxDistance >= f.nearStart;
        if (f.falloffFar) ok = ok && minDistance <= f.farEnd;
        return ok;
    }
    case FilterRod: {
        if (f.density < 1.0f) return true;
        if (rodOutside(f, d.p, d.radius)) return true;
        const float r = rodDistance(f, filterRender2Local(f, d.p, d.time));
        if (f.invert) {
            if (isBlackColor(f.color) && r > d.radius + f.edge) return false;
        } else if (isBlackColor(f.color) && r < -d.radius) {
            return false;
        }
        return true;
    }
    case FilterBarnDoor: {
        const X34 r2l = f.useLightXform ? d.lightRender2Local : barnRender2Local(f, d.time);
        const float z = x34Point(r2l, d.p).z;
        if (z < 0.0f) return false;
        if (z < f.preBarnDist) {
            if (f.preBarnMode == OutsideBlack) return false;
            if (f.preBarnMode == OutsideWhite) return true;
        }
        return true;
    }
    case FilterCookie:
    case FilterCookie2: {
        const V3 pos = surface::add(surface::mul(f.projectorPos[0], 1.0f - d.time), surface::mul(f.projectorPos[1], d.time));
        const V3 dir = surface::add(surface::mul(f.projectorDir[0], 1.0f - d.time), surface::mul(f.projectorDir[1], d.time));
        if (surface::dot(surface::add(d.p, surface::mul(pos, -1.0f)), dir) < 0.0f) return f.outside == OutsideWhite;
        return true;
    }
    default: return true;  // colour ramp
    }
}

// eval of a leaf filter. map(program, s, t, color): a cookie's map shader at (s, t).
template <class MapFn>
X2_HD inline V3 filterEvalLeaf(const Filter& f, const FilterPoint& d, const MapFn& map) {
    switch (f.kind) {
    case FilterIntensity: return pathSelected(f.pathSelection, d) ? f.color : V3{1, 1, 1};
    case FilterDecay: {
        const float dist = d.distance;
        float v = 1.0f;
        if ((f.falloffNear && dist < f.nearStart) || (f.falloffFar && dist > f.farEnd)) {
            v = 0.0f;
        } else if (f.falloffNear && dist < f.nearEnd) {
            v = (dist - f.nearStart) / (f.nearEnd - f.nearStart);
        } else if (f.falloffFar && dist > f.farStart) {
            v = (f.farEnd - dist) / (f.farEnd - f.farStart);
        }
        return V3{v, v, v};
    }
    case FilterColorRamp: {
        float dist;
        if (f.mode == RampRadial) {
            if (f.useXform) {
                const V3 a = x34Point(f.xform[0], d.p), b = x34Point(f.xform[1], d.p);
                const float la = sqrtf(surface::dot(a, a)), lb = sqrtf(surface::dot(b, b));
                dist = la + (lb - la) * d.time;
            } else {
                dist = d.distance;
            }
        } else {
            if (f.useXform) {
                const V3 a = x34Point(f.xform[0], d.p), b = x34Point(f.xform[1], d.p);
                dist = -(a.z + (b.z - a.z) * d.time);
            } else {
                // Plane_init(lightPosition, lightDirection) and Plane_getDistance, which in vector mode is signed: the
                // sign "restored" behind the light flips it again, so the distance comes out positive either side.
                const float offset = -surface::dot(d.lightPosition, d.lightDirection);
                dist = surface::dot(d.p, d.lightDirection) + offset;
                if (surface::dot(surface::add(d.p, surface::mul(d.lightPosition, -1.0f)), d.lightDirection) < 0.0f) dist *= -1.0f;
            }
            if (f.wrap == WrapExtend) {
                if (dist < 0.0f) dist = 0.0f;
            } else {
                dist = fabsf(dist);
            }
        }
        V3 c = shade::rampEval(f.colorRamp, dist);
        c = surface::mul(c, f.intensity);
        return surface::add(V3{1.0f - f.density, 1.0f - f.density, 1.0f - f.density}, surface::mul(c, f.density));
    }
    case FilterRod: {
        if (rodOutside(f, d.p, 0.0f)) return V3{1, 1, 1};
        float r = rodDistance(f, filterRender2Local(f, d.p, d.time));
        float scale = 1.0f;
        if (r <= 0.0f) {
            scale = 0.0f;
        } else if (r < f.edge) {
            r *= f.edgeInv;
            scale = shade::rampEval(f.ramp, r);
        }
        if (f.invert) scale = 1.0f - scale;
        scale = 1.0f + (scale - 1.0f) * f.density;
        return surface::add(f.color, surface::mul(surface::add(V3{1, 1, 1}, surface::mul(f.color, -1.0f)), scale));
    }
    case FilterBarnDoor: {
        const X34 r2l = f.useLightXform ? d.lightRender2Local : barnRender2Local(f, d.time);
        V3 pt = x34Point(r2l, d.p);
        const float shadingDist = pt.z;
        if (shadingDist < f.preBarnDist) {
            if (f.preBarnMode == OutsideBlack) return V3{0, 0, 0};
            if (f.preBarnMode == OutsideWhite) return V3{1, 1, 1};
        }
        if (f.mode == BarnPhysical) {
            const V3 wi = x34Vector(r2l, d.wi);
            const float t = (f.focalDist - shadingDist) / wi.z;
            pt = surface::add(pt, surface::mul(wi, t));
        }
        const V3 screen = m44H(f.projector2Screen, pt);
        const float sx = screen.x, sy = screen.y;
        const float cx = fminf(fmaxf(sx, f.minCorner[0]), f.maxCorner[0]), cy = fminf(fmaxf(sy, f.minCorner[1]), f.maxCorner[1]);
        const float dx = sx - cx, dy = sy - cy;
        const float rx = f.reciprocalEdgeScales[dx < 0.0f ? 0 : 2], ry = f.reciprocalEdgeScales[dy < 0.0f ? 1 : 3];
        const float r0 = f.radius, r = sqrtf(dx * dx + dy * dy);
        const float r1 = r / sqrtf((dx * rx) * (dx * rx) + (dy * ry) * (dy * ry));
        float scale = 0.0f;
        if (r <= r0) {
            scale = 1.0f;
        } else if (r < r1) {
            scale = barnBlur((r - r0) / (r1 - r0));
        }
        if (f.invert) scale = 1.0f - scale;
        const V3 c = surface::mul(f.color, scale);
        return surface::add(surface::mul(V3{1, 1, 1}, 1.0f - f.density), surface::mul(c, f.density));
    }
    case FilterCookie:
    case FilterCookie2: {
        if (f.kind == FilterCookie && f.mapProgram == 0xffffffffu) return V3{1, 1, 1};
        const V3 pos = surface::add(surface::mul(f.projectorPos[0], 1.0f - d.time), surface::mul(f.projectorPos[1], d.time));
        const V3 dir = surface::add(surface::mul(f.projectorDir[0], 1.0f - d.time), surface::mul(f.projectorDir[1], d.time));
        const V3 sv = surface::add(d.p, surface::mul(pos, -1.0f));
        const float distanceToProjector = sqrtf(surface::dot(sv, sv));
        if (surface::dot(sv, dir) < 0.0f) return f.outside == OutsideWhite ? V3{1, 1, 1} : V3{0, 0, 0};
        const V3 a = m44H(f.projectorR2S[0], d.p), b = m44H(f.projectorR2S[1], d.p);
        V3 screen = surface::add(surface::mul(a, 1.0f - d.time), surface::mul(b, d.time));
        screen.x += 0.5f;
        screen.y += 0.5f;
        const float radius = cookieBlur(f, distanceToProjector);
        float ox, oy;
        if (f.blurType == BlurGaussian) {
            ox = quadraticBSplineWarp(d.r2[0]) * radius;
            oy = quadraticBSplineWarp(d.r2[1]) * radius;
        } else {
            ox = d.r2[0];
            oy = d.r2[1];
            filterUnitDisk(ox, oy);
            ox *= radius;
            oy *= radius;
        }
        const float s = screen.x + ox, t = screen.y + oy;
        if (s < 0.0f || s > 1.0f || t < 0.0f || t > 1.0f) {
            if (f.outside == OutsideBlack) return V3{0, 0, 0};
            if (f.outside == OutsideWhite) return V3{1, 1, 1};
        }
        V3 c;
        if (f.kind == FilterCookie) {
            c = map(f.mapProgram, f.mapRegister, s, t);
        } else if (f.image) {
            c = imageEval(*f.image, s, t, 0.0f, FilterBilinear);
        } else {
            c = f.fallback;
        }
        c = V3{1.0f - f.density + c.x * f.density, 1.0f - f.density + c.y * f.density, 1.0f - f.density + c.z * f.density};
        if (f.invert) c = V3{1.0f - c.x, 1.0f - c.y, 1.0f - c.z};
        return c;
    }
    case FilterVdb: {
        const V3 a = x34Point(f.vdbR2V[0], d.p), b = x34Point(f.vdbR2V[1], d.p);
        V3 p = surface::add(surface::mul(a, 1.0f - d.time), surface::mul(b, d.time));
        if (f.vdbBlur > 0.0f) {
            V3 o;
            if (f.blurType == 0) {
                o = V3{quadraticBSplineWarp(d.r3[0]) * f.vdbBlur, quadraticBSplineWarp(d.r3[1]) * f.vdbBlur,
                       quadraticBSplineWarp(d.r3[2]) * f.vdbBlur};
            } else {
                o = shade::sampleSphereUniform(d.r3[0], d.r3[1]);
                const float s = f.vdbBlur * powf(d.r3[2], 1.0f / 3.0f);
                o = V3{o.x * s, o.y * s, o.z * s};
            }
            p = surface::add(p, o);
        }
        float density = map.vdb(f.vdbGrid, f.vdbInterpolation, p);
        if (f.invert) density = 1.0f - density;
        density = fmaxf(shade::rampEval(f.ramp, density), 0.0f);
        return V3{f.color.x * (1.0f - density) + density, f.color.y * (1.0f - density) + density, f.color.z * (1.0f - density) + density};
    }
    default: return V3{1, 1, 1};
    }
}

// A filter, a combine's children each a filter in turn (a combine within a combine: LightFilter_canIlluminate's
// function pointer).
X2_HD inline bool filterCanIlluminate(const Filter* filters, U32 index, const FilterPoint& d) {
    const Filter& f = filters[index];
    if (f.kind != FilterCombine) return filterCanIlluminateLeaf(f, d);
    for (U32 i = 0; i < f.childCount; ++i)
        if (filterCanIlluminate(filters, f.children[i], d)) return true;
    return false;
}
template <class MapFn>
X2_HD inline V3 filterEval(const Filter* filters, U32 index, const FilterPoint& d, const MapFn& map) {
    const Filter& f = filters[index];
    if (f.kind != FilterCombine) return filterEvalLeaf(f, d, map);
    V3 v = (f.mode == CombineMax || f.mode == CombineAdd) ? V3{0, 0, 0} : V3{1, 1, 1};
    for (U32 i = 0; i < f.childCount; ++i) {
        const V3 c = filterEval(filters, f.children[i], d, map);
        switch (f.mode) {
        case CombineMultiply: v = V3{v.x * c.x, v.y * c.y, v.z * c.z}; break;
        case CombineMin: v = V3{fminf(v.x, c.x), fminf(v.y, c.y), fminf(v.z, c.z)}; break;
        case CombineMax: v = V3{fmaxf(v.x, c.x), fmaxf(v.y, c.y), fmaxf(v.z, c.z)}; break;
        case CombineAdd: v = surface::add(v, c); break;
        default: v = i == 0 ? c : surface::add(v, surface::mul(c, -1.0f)); break;
        }
    }
    if (f.mode == CombineAdd) v = V3{fminf(v.x, 1.0f), fminf(v.y, 1.0f), fminf(v.z, 1.0f)};
    if (f.mode == CombineSubtract) v = V3{fmaxf(v.x, 0.0f), fmaxf(v.y, 0.0f), fmaxf(v.z, 0.0f)};
    return v;
}
// What a light hands its filters (each light's canIlluminate and eval): its radius (CanIlluminateData::lightRadius,
// each light type's; a mesh light's taken as unbounded) and its render (world) to local transform
// (getXformRender2Local; env and distant lights: their rotation's inverse).
X2_HD inline float filterLightRadius(const Light& l) {
    switch (l.type) {
    case Rect:
    case Portal: {
        const float w = 2.0f * l.halfWidth, h = 2.0f * l.halfHeight;
        return l.scale * (sqrtf(w * w + h * h) / 2.0f);
    }
    case Disk: return l.scale * 1.0f;
    case Sphere: return l.radius;
    case Spot: return l.scale * fmaxf(l.lensRadius, l.lensRadiusY);
    case Cylinder: return l.scale * fmaxf(l.localHalfHeight * 2.0f, l.localRadius);
    default: return 3.402823466e38f * 2.0f;  // inf
    }
}
X2_HD inline X34 lightRender2Local(const Light& l) {
    X34 x;
    if (l.type == Env || l.type == Distant) {
        const M3 r = m3Transpose(M3{{l.local2Render[0], l.local2Render[1], l.local2Render[2]}});
        x.r[0] = r.r[0];
        x.r[1] = r.r[1];
        x.r[2] = r.r[2];
        x.r[3] = V3{0, 0, 0};
        return x;
    }
    x.r[0] = l.render2Local[0];
    x.r[1] = l.render2Local[1];
    x.r[2] = l.render2Local[2];
    x.r[3] = surface::mul(m3Apply(l.position, M3{{l.render2Local[0], l.render2Local[1], l.render2Local[2]}}), -1.0f);
    return x;
}
// LightFilterList_canIlluminate and LightFilterList_eval.
X2_HD inline bool filterListCanIlluminate(const Filter* filters, const FilterList& l, const FilterPoint& d) {
    for (U32 i = 0; i < l.count; ++i)
        if (!filterCanIlluminate(filters, l.items[i], d)) return false;
    return true;
}
template <class MapFn>
X2_HD inline V3 filterListEval(const Filter* filters, const FilterList& l, const FilterPoint& d, const MapFn& map) {
    V3 v{1, 1, 1};
    for (U32 i = 0; i < l.count; ++i) {
        const V3 c = filterEval(filters, l.items[i], d, map);
        v = V3{v.x * c.x, v.y * c.y, v.z * c.z};
    }
    return v;
}

}  // namespace xpu2::interactive::lights
