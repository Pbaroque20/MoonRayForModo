// MoonRay's lights for the asynchronous renderer, shared by the CPU and CUDA
// lanes: each light samples a direction toward itself, evaluates its radiance
// and solid-angle pdf, and intersects the rays BSDF samples cast.
//
// Adapted from MoonRay pbr/light (Light.h, LightUtil.h, EnvLight.cc,
// RectLight.cc, DiskLight.cc, SphereLight.cc, DistantLight.cc, SpotLight.cc), pbr/core/Util.h
// and shading/Util.h, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC;
// see MOONRAY_LICENSE.txt. Without motion blur, image maps, spread, light filters
// or clear radius: scenes with those render by fallback. Render space is world
// space, as in the rest of the prototype; a light's local frame is its node
// transform turned about X by 180 degrees, so it shines down its local -Z.
#pragma once
#include "light_image.h"
#include "surface_core.h"

namespace xpu2::interactive::lights {
using surface::V3;
using sample::U32;

enum Type : U32 { Env = 0, Rect = 1, Disk = 2, Sphere = 3, Distant = 4, Spot = 5, Cylinder = 6, Mesh = 7, Portal = 8 };
enum Sidedness : U32 { Regular = 0, Reverse = 1, TwoSided = 2 };

constexpr float Epsilon = 1e-6f;  // scene_rdl2 sEpsilon (C++ and ISPC alike)
constexpr float NoFootprint = -1e30f;  // a ray without differentials (MoonRay: -infinity), so mip level 0
constexpr float InfiniteDistance = 3.4028234663852886e+38f - 1e32f;
constexpr float EnvDistance = InfiniteDistance * 0.9f;
constexpr float DistantDistance = InfiniteDistance * 0.8f;
constexpr float HitEpsilonEnd = 1.0f - 1e-3f;  // shadow rays stop this far short of the light
constexpr float Pi = 3.14159265358979323846f, TwoPi = 6.28318530717958647692f;
constexpr float OneOverTwoPi = 0.15915494309189533577f, OneOverFourPi = 0.07957747154594766788f;

// A MeshLight (MeshLight.cc, MeshLight.ispc): its mesh's faces in the light's local space, each a flat polygonal
// light, and the sampling BVH over them (Estevez and Kulla 2017), which a sample descends by each node's importance to
// the shading point. A node's left child is the next node.
struct MeshNode {
    V3 lower, upper;  // its bounds
    V3 center;        // Node::getCenter: a leaf's face centre, else its bounds' centre
    V3 axis;          // its bounding cone's axis
    float thetaO;     // and spread
    float radius;     // from its centre to its bounds' upper corner (importance's bounding sphere)
    float energy;
    int right, parent, face;  // its right child and parent (-1: the root), and a leaf's face (-1: none)
};
struct MeshFace {
    U32 v[4];        // its corners' vertices: three, or four (a QuadMesh's triangle repeats its third)
    V3 normal;       // unit; a quad's of its two triangles' sum
    float invArea;
    U32 count, prim; // its corner count and its face in the tessellated mesh
};
struct MeshLightData {
    const MeshNode* nodes;
    const MeshFace* faces;
    const V3* vertices;
    U32 nodeCount, faceCount;
};

// One light, in render space. Linear parts are stored as rows, as MoonRay's
// row-vector transforms are: a local vector v maps to v.x row0 + v.y row1 + v.z row2.
struct Light {
    U32 type, sidedness, index;  // index: its place among the scene's lights (shadow linking's)
    // A ray termination light (ray_termination): its light samples are never occluded, and a BSDF sample meets it only
    // from a lobe whose bounces have ended (PathIntegratorMultiSampler's FORCE_NOT_OCCLUDED).
    U32 rayTerminator;
    V3 radiance;
    V3 position, direction;  // local origin; local +Z, unit (MoonRay getPosition, getDirection)
    V3 local2Render[3];      // with scale
    V3 render2Local[3];      // its inverse
    V3 render2LocalRot[3];   // rotation only
    float scale;             // local to render length scale
    float invArea;
    float planeOffset;       // -dot(direction, position): the light's plane
    float halfWidth, halfHeight;            // rect, local units
    float radius, radiusSq, rcpRadius;      // sphere, render units
    float cosThetaMax, versineThetaMax;     // distant
    // spot: its lens and focal plane, local units, and its falloff between the cones
    float lensRadius, lensRadiusY, rcpLensRadius, rcpLensRadiusY;
    float focalDistance, focalRadius, focalRadiusY, rcpFocalRadius, rcpFocalRadiusY;
    float falloffGradient, crossOverDistance, focalPlanePdfConst;
    U32 falloffType;
    // Its texture (Light::updateImageMap; none: its radiance alone, times the fallback colour), the filter it is
    // read with, the log2 of a texel's angle (env and distant mip levels), and whether the camera sees it.
    const Image* image;
    U32 filter, visibleInCamera, hemispherical, pad2;
    float log2TexelAngle;
    float uvScale[2], uvOffset[2];
    V3 fallback;
    // Rect and disk: their spread (1: none) as an egg-crate's tangent; disk: its texture's pdf scale.
    float spread, tanSpreadTheta, distributionPdfScale;
    // Distant: its equisolid fisheye texture mapping and the texture pdf's Jacobian.
    float localToUvConst, uvToLocalConst, jacobian;
    float blackLevel;  // spot: what the camera sees outside its cone
    // Cylinder: its radius and half height in local units, the half height in render units (its render radius is
    // radius, radiusSq and rcpRadius), and its axis, local +Y, in render space.
    float localRadius, localHalfHeight, actualHalfHeight;
    V3 axis;
    const MeshLightData* mesh;  // MeshLight: its faces and their sampling BVH
    // Shadows nearer the light than its clear radius are ignored, or fade over the falloff distance beyond it
    // (calculateShadowFalloff); its shadow rays start at least its min shadow distance out and reach at most its max
    // shadow distance (0: unlimited).
    float clearRadius, clearRadiusFalloff, minShadowDistance, maxShadowDistance;
    U32 clearRadiusInterpolation;
    int lpeLabel = -1;  // its label in the light path expressions (Light::getLabelId), -1: none
    U32 pad4, pad5;
    // PortalLight: a rect (the fields above) through which the environment or distant light it references (ref, a
    // copy; refIndex among the lights) lights the scene, which then lights no shading point itself (hasPortal).
    const Light* ref;
    U32 refIndex, hasPortal;
    // The lobe types that see the light (rdl2::Light::getVisibilityMask: visible_diffuse_reflection and the rest, as
    // rdl2's VisibilityType bits).
    U32 visibilityMask;
    U32 presenceShadows;  // its shadow rays gather the presence of what they pass (Light::updatePresenceShadows)
};

// A light under motion blur (its mb switch; LocalParamLight::updateParamAndTransforms, EnvLight's and DistantLight's
// orientations): its record holds the shutter's open; this, what has moved by the close: its position (MbTranslation),
// its orientation (MbRotation: quaternions r, i, j, k at both ends, the close's sign agreeing with the open's) and its
// scale (MbScale). light is its index among the lights.
enum : U32 { MbTranslation = 1u, MbRotation = 2u, MbScale = 4u };
struct LightMotion {
    U32 light = 0, flags = 0;
    V3 position[2];
    float orientation[2][4];
    float scale[2];
};
// scene_rdl2's quaternion slerp (Quaternion.h) and Mat3(Quaternion)'s rows (its last diagonal term in double).
X2_HD inline void lightSlerp(const float a[4], const float b[4], float t, float out[4]) {
    float angle = 0.0f, sineAngle = 0.0f;
    const float cosAngle = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
    if (fabsf(cosAngle) < 1.0f) {
        angle = acosf(cosAngle);
        sineAngle = sinf(angle);
    }
    if (fabsf(sineAngle) < 0.00001f) {
        for (int k = 0; k < 4; ++k) out[k] = (1.0f - t) * a[k] + t * b[k];
        return;
    }
    const float rcpSine = 1.0f / sineAngle, rA = sinf((1.0f - t) * angle) * rcpSine, rB = sinf(t * angle) * rcpSine;
    for (int k = 0; k < 4; ++k) out[k] = a[k] * rA + b[k] * rB;
}
X2_HD inline void quaternionRows(const float q[4], V3 rows[3]) {
    const float r = q[0], i = q[1], j = q[2], k = q[3];
    rows[0] = V3{1.0f - 2.0f * (j * j + k * k), 2.0f * (i * j + r * k), 2.0f * (i * k - r * j)};
    rows[1] = V3{2.0f * (i * j - r * k), 1.0f - 2.0f * (i * i + k * k), 2.0f * (j * k + r * i)};
    rows[2] = V3{2.0f * (i * k + r * j), 2.0f * (j * k - r * i), float(1.0 - double(2.0f * (i * i + j * j)))};
}
// The light at a time in the shutter (slerpPointLocal2Render and its kin, getPosition, getDirection): its frame made of
// the slerped orientation, the lerped scale and the lerped position, as the record's matrices. What does not move keeps
// the open's (the record's own, mLocal2RenderRot[0] and the rest); the derived constants (area, radii) stay the open's.
X2_HD inline Light lightAtTime(const Light& base, const LightMotion& m, float time) {
    Light l = base;
    const bool oriented = base.type == Env || base.type == Distant;
    const float s0 = oriented ? 1.0f : base.scale;
    const float s = (m.flags & MbScale) ? (1.0f - time) * m.scale[0] + time * m.scale[1] : s0;
    V3 R[3];
    if (m.flags & MbRotation) {
        float q[4];
        lightSlerp(m.orientation[0], m.orientation[1], time, q);
        quaternionRows(q, R);
    } else {
        for (int i = 0; i < 3; ++i) R[i] = surface::mul(base.local2Render[i], 1.0f / s0);
    }
    if (oriented) {
        if (m.flags & MbRotation) {
            for (int i = 0; i < 3; ++i) l.local2Render[i] = R[i];
            l.direction = R[2];
        }
        return l;
    }
    const V3 T = (m.flags & MbTranslation) ? surface::add(surface::mul(m.position[0], 1.0f - time), surface::mul(m.position[1], time))
                                           : base.position;
    for (int i = 0; i < 3; ++i) l.local2Render[i] = surface::mul(R[i], s);
    l.render2LocalRot[0] = V3{R[0].x, R[1].x, R[2].x};
    l.render2LocalRot[1] = V3{R[0].y, R[1].y, R[2].y};
    l.render2LocalRot[2] = V3{R[0].z, R[1].z, R[2].z};
    for (int i = 0; i < 3; ++i) l.render2Local[i] = surface::mul(l.render2LocalRot[i], 1.0f / s);
    l.position = T;
    if (m.flags & MbRotation) l.direction = R[2];
    l.planeOffset = -surface::dot(l.direction, l.position);
    l.scale = s;
    if (base.type == Cylinder && (m.flags & MbRotation)) l.axis = R[1];
    return l;
}

// Where a light sample or a BSDF ray meets the light (LightIntersection).
struct Hit {
    V3 N;            // the light's normal facing the shading point
    float distance;
    float data0, data1;  // sphere: cos(theta) over sin^2(theta max), and the distance used for its pdf; spot, env,
                         // distant, rect and disk: the texture's uv
    float pdf;       // rect and disk with spread: the area pdf of the region sampled (LightIntersection::pdf)
    float u, v;      // sphere: its texture's uv; mesh: the barycentrics on its face (the map shader's)
    U32 face;        // mesh: the face (MeshLightData::faces)
};

// rdl2's VisibilityType bits for a lobe type (lobeTypeToRayMask): its diffuse, glossy and mirror bits as
// reflection, shifted up one as transmission.
constexpr U32 VisibleDiffuseReflection = 1u << 2, VisibleAllLights = 0xfcu;
X2_HD inline U32 lobeRayMask(U32 lobeType) {
    U32 mask = 0;
    if (lobeType & 1u) mask |= lobeType & 0x54u;
    if (lobeType & 2u) mask |= (lobeType & 0x54u) << 1;
    return mask;
}
X2_HD inline V3 rows(const V3 m[3], V3 v) {
    return surface::add(surface::add(surface::mul(m[0], v.x), surface::mul(m[1], v.y)), surface::mul(m[2], v.z));
}
// A frame's global-to-local: the dot products with its X, Y, Z (ReferenceFrame::globalToLocal).
X2_HD inline V3 dots(const V3 m[3], V3 v) { return {surface::dot(v, m[0]), surface::dot(v, m[1]), surface::dot(v, m[2])}; }
X2_HD inline V3 sub(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
X2_HD inline float lengthSq(V3 a) { return surface::dot(a, a); }
X2_HD inline float powerHeuristic(float f, float g) { return (f * f) / (f * f + g * g); }

// A solid-angle pdf from an area pdf: distance squared over the cosine at the
// light, 0 when that cosine is about 0 (areaToSolidAngleScale).
X2_HD inline float areaToSolidAngleScale(V3 wi, V3 lightNormal, float dist) {
    const float denom = -surface::dot(wi, lightNormal);
    return denom < 0.00001f ? 0.0f : (dist * dist) / denom;
}

// A unit vector at polar angle theta (as its cosine) and azimuth phi, about +Z.
X2_HD inline V3 polar(float cosTheta, float sinTheta, float phi) {
    float s, c;
    surface::sincosSample(phi, s, c);
    return {sinTheta * c, sinTheta * s, cosTheta};
}

// The spot light's lens and focal-plane coordinates (SpotLight.cc).
X2_HD inline void lensToFocal(const Light& l, float lx, float ly, V3 localP, float& fx, float& fy) {
    const float f = l.focalDistance;
    float z = localP.z;
    if (z == 0.0f) z = 1.0e-20f;
    fx = ((z - f) * lx + f * localP.x) / z;
    fy = ((z - f) * ly + f * localP.y) / z;
}
X2_HD inline void focalToLens(const Light& l, float fx, float fy, V3 localP, float& lx, float& ly) {
    const float f = l.focalDistance, z = localP.z;
    float denom = z - f;
    if (denom == 0.0f) denom = 1.0e-20f;
    lx = (z * fx - f * localP.x) / denom;
    ly = (z * fy - f * localP.y) / denom;
}
// MoonRay's FalloffCurve.
X2_HD inline float falloff(U32 type, float t) {
    t = fminf(fmaxf(t, 0.0f), 1.0f);
    switch (type) {
    case 0: return t > 0.0f ? 1.0f : 0.0f;
    case 2: return t * t;
    case 3: return t * (2.0f - t);
    case 4: return t * t * (3.0f - 2.0f * t);
    default: return t;
    }
}

X2_HD inline float planeDistance(const Light& l, V3 p) {
    float d = surface::dot(l.direction, p) + l.planeOffset;
    if (l.sidedness == Reverse) d = -d;
    else if (l.sidedness == TwoSided) d = fabsf(d);
    return d;
}
X2_HD inline bool rejectPosDirSidedness(const Light& l, float pz, float wz) {
    if ((pz < 0.0f) == (wz < 0.0f)) return true;
    return pz < 0.0f ? l.sidedness == Regular : l.sidedness == Reverse;
}


// Rect and disk spread (RectLight/DiskLight::getOverlapBounds): the overlap of the light with the square of half
// side `length` about localP, as a centre and size; false when they do not overlap.
X2_HD inline bool rectOverlap(const Light& l, float px, float py, float length, float& cx, float& cy, float& w, float& h) {
    const float minX = fmaxf(px - length, -l.halfWidth), maxX = fminf(px + length, l.halfWidth);
    const float minY = fmaxf(py - length, -l.halfHeight), maxY = fminf(py + length, l.halfHeight);
    if (maxX <= minX || maxY <= minY) return false;
    cx = 0.5f * (maxX + minX);
    cy = 0.5f * (maxY + minY);
    w = maxX - minX;
    h = maxY - minY;
    return true;
}
X2_HD inline bool diskOverlap(float px, float py, float length, float& cx, float& cy, float& w, float& h) {
    const float x0 = px - length, x1 = px + length, y0 = py - length, y1 = py + length;
    const float xc = fminf(fmaxf(0.f, x0), x1), yc = fminf(fmaxf(0.f, y0), y1);  // clamp(0, x0, x1)
    if (xc * xc + yc * yc >= 1.f) return false;
    const float xi = sqrtf(1 - yc * yc), yi = sqrtf(1 - xc * xc);
    const float minX = fmaxf(-xi, x0), maxX = fminf(xi, x1), minY = fmaxf(-yi, y0), maxY = fminf(yi, y1);
    cx = 0.5f * (maxX + minX);
    cy = 0.5f * (maxY + minY);
    w = maxX - minX;
    h = maxY - minY;
    return true;
}
// The egg-crate's attenuation of a spread light (RectLight/DiskLight::eval).
X2_HD inline float spreadFactor(const Light& l, V3 wi) {
    const V3 lw = rows(l.render2LocalRot, wi);
    return fmaxf(1.f - fabsf(lw.x / (lw.z * l.tanSpreadTheta)), 0.f) * fmaxf(1.f - fabsf(lw.y / (lw.z * l.tanSpreadTheta)), 0.f);
}
X2_HD inline bool outsideSpread(const Light& l, V3 localWi) {
    return fmaxf(fabsf(localWi.x), fabsf(localWi.y)) > fabsf(localWi.z) * l.tanSpreadTheta;
}
// DistantLight's equisolid fisheye mapping between its local directions and its texture.
X2_HD inline void distantLocalToUv(const Light& l, V3 dir, float& u, float& v) {
    const float oneMinusZ = fmaxf(1.0f - dir.z, 1.0e-20f);
    const float scale = -l.localToUvConst / sqrtf(oneMinusZ);
    u = fminf(fmaxf(dir.x * scale + 0.5f, 0.0f), 1.0f);
    v = fminf(fmaxf(dir.y * scale + 0.5f, 0.0f), 1.0f);
}
X2_HD inline V3 distantUvToLocal(const Light& l, float u, float v) {
    const float u1 = u - 0.5f, v1 = v - 0.5f;
    const float z = -1.0f + l.uvToLocalConst * (u1 * u1 + v1 * v1);
    const float scale = -sqrtf(l.uvToLocalConst * (1.0f - z));
    return {u1 * scale, v1 * scale, z};
}
X2_HD inline V3 times(V3 a, V3 b) { return {a.x * b.x, a.y * b.y, a.z * b.z}; }
// ---- MeshLight (MeshLight.ispc: the vector renderer's, with dw_acos)
// MeshLight_importance: a node's energy over the squared distance to its centre, times how well its bounding cone
// and the shading normal face each other across its bounding sphere (Kulla 2017, Eq. 3).
X2_HD inline float meshImportance(const MeshNode& node, V3 p, const V3* n) {
    if (node.energy == 0.0f) return 0.0f;
    V3 toCenter = sub(node.center, p);
    const float distance2 = lengthSq(toCenter);
    float orientation = 1.0f;
    if (!(fabsf(node.thetaO - Pi) <= fmaxf(fabsf(node.thetaO), 1.0f) * Epsilon) && distance2 != 0.0f) {
        const float distance = sqrtf(distance2);
        toCenter = {toCenter.x / distance, toCenter.y / distance, toCenter.z / distance};
        const float thetaU = distance >= node.radius ? asinf(node.radius / distance) : Pi;
        float normalContribution = 1.0f;
        if (n) {
            const float thetaI = dwAcos(fminf(fmaxf(surface::dot(toCenter, *n), -1.0f), 1.0f));
            normalContribution = fabsf(cosf(fmaxf(thetaI - thetaU, 0.0f)));
        }
        const float theta = dwAcos(fminf(fmaxf(-surface::dot(node.axis, toCenter), -1.0f), 1.0f));
        const float thetaPrime = fmaxf(theta - node.thetaO - thetaU, 0.0f);
        orientation = normalContribution * (thetaPrime < 0.5f * Pi ? cosf(thetaPrime) : 0.0f);
    }
    return node.energy * orientation / distance2;
}
// MeshLight_drawSampleRecurse: down the tree by u, rescaled at each node; pdf the product of the choices and the
// face's inverse area. Returns the leaf.
X2_HD inline int meshDrawSample(const MeshLightData& m, V3 p, const V3* n, float u, float& pdf) {
    int index = 0;
    for (;;) {
        const MeshNode& node = m.nodes[index];
        if (node.face >= 0) {
            pdf *= m.faces[node.face].invArea;
            return index;
        }
        const int left = index + 1, right = node.right;
        const float li = meshImportance(m.nodes[left], p, n), ri = meshImportance(m.nodes[right], p, n);
        const float pdfL = (li == 0.0f && ri == 0.0f) ? 0.5f : li / (li + ri);
        const float pdfR = 1.0f - pdfL;
        if (u <= pdfL && pdfL != 0.0f) {
            u = u / pdfL;
            pdf *= pdfL;
            index = left;
        } else {
            u = (u - pdfL) / pdfR;
            pdf *= pdfR;
            index = right;
        }
    }
}
// MeshLight_getPdfOfFace: the probability of choosing a leaf, up the tree.
X2_HD inline float meshLeafPdf(const MeshLightData& m, int index, V3 p, const V3* n) {
    float pdf = 1.0f;
    while (index > 0) {
        const MeshNode& node = m.nodes[index];
        const MeshNode& parent = m.nodes[node.parent];
        const MeshNode& sibling = parent.right == index ? m.nodes[node.parent + 1] : m.nodes[parent.right];
        const float ci = meshImportance(node, p, n), si = meshImportance(sibling, p, n);
        pdf *= (ci == 0.0f && si == 0.0f) ? 0.5f : ci / (ci + si);
        index = node.parent;
    }
    return pdf;
}
// A ray against a triangle as Embree meets it for MeshLight: its front alone (the backFaceCullingFilter rejects a
// ray along Ng = (b - a) x (c - a)), nearer than tfar; u and v weigh b and c.
X2_HD inline bool meshTriangle(V3 o, V3 d, V3 a, V3 b, V3 c, float& tfar, float& u, float& v) {
    const V3 e1 = sub(b, a), e2 = sub(c, a);
    if (surface::dot(d, surface::cross(e1, e2)) >= 0.0f) return false;
    const V3 pv = surface::cross(d, e2);
    const float det = surface::dot(e1, pv);
    if (!(det > 0.0f)) return false;
    const float inv = 1.0f / det;
    const V3 tv = sub(o, a);
    const float uu = surface::dot(tv, pv) * inv;
    if (uu < 0.0f || uu > 1.0f) return false;
    const V3 qv = surface::cross(tv, e1);
    const float vv = surface::dot(d, qv) * inv;
    if (vv < 0.0f || uu + vv > 1.0f) return false;
    const float t = surface::dot(e2, qv) * inv;
    if (!(t > 0.0f) || t >= tfar) return false;
    tfar = t;
    u = uu;
    v = vv;
    return true;
}
X2_HD inline bool meshBox(const MeshNode& n, V3 o, V3 inv, float tfar) {
    const float tx0 = (n.lower.x - o.x) * inv.x, tx1 = (n.upper.x - o.x) * inv.x;
    const float ty0 = (n.lower.y - o.y) * inv.y, ty1 = (n.upper.y - o.y) * inv.y;
    const float tz0 = (n.lower.z - o.z) * inv.z, tz1 = (n.upper.z - o.z) * inv.z;
    const float tmin = fmaxf(fmaxf(fminf(tx0, tx1), fminf(ty0, ty1)), fmaxf(fminf(tz0, tz1), 0.0f));
    const float tmax = fminf(fminf(fmaxf(tx0, tx1), fmaxf(ty0, ty1)), fminf(fmaxf(tz0, tz1), tfar));
    return tmin <= tmax;
}
// The nearest face a local ray meets (Embree over the mesh, a quad as its triangles (0, 1, 3) and (2, 3, 1), the
// second's barycentrics flipped): down the tree without a stack, by its parent links. Returns the leaf, or -1.
X2_HD inline int meshIntersect(const MeshLightData& m, V3 o, V3 d, float& tfar, float& u, float& v) {
    const V3 inv{1.0f / d.x, 1.0f / d.y, 1.0f / d.z};
    int hit = -1, current = 0, previous = -1;
    while (current >= 0) {
        const MeshNode& node = m.nodes[current];
        int next;
        if (previous == node.parent) {
            if (!meshBox(node, o, inv, tfar)) next = node.parent;
            else if (node.face >= 0) {
                const MeshFace& f = m.faces[node.face];
                const V3 v0 = m.vertices[f.v[0]], v1 = m.vertices[f.v[1]], v2 = m.vertices[f.v[2]];
                float a, b;
                if (f.count == 3) {
                    if (meshTriangle(o, d, v0, v1, v2, tfar, a, b)) {
                        hit = current;
                        u = a;
                        v = b;
                    }
                } else {
                    const V3 v3 = m.vertices[f.v[3]];
                    if (meshTriangle(o, d, v0, v1, v3, tfar, a, b)) {
                        hit = current;
                        u = a;
                        v = b;
                    }
                    if (meshTriangle(o, d, v2, v3, v1, tfar, a, b)) {
                        hit = current;
                        u = 1.0f - a;
                        v = 1.0f - b;
                    }
                }
                next = node.parent;
            } else next = current + 1;
        } else if (previous == current + 1) next = node.right;
        else next = node.parent;
        previous = current;
        current = next;
    }
    return hit;
}

// CylinderLight's (u, v) parameterization: u along its height, v around it (CylinderLight.ispc).
X2_HD inline V3 cylinderUv2Local(const Light& l, float u, float v) {
    float s, c;
    surface::sincosSample(v * TwoPi, s, c);
    return {l.localRadius * c, (u - l.uvOffset[0]) / l.uvScale[0], l.localRadius * s};
}
X2_HD inline void cylinderLocal2Uv(const Light& l, V3 pos, float& u, float& v) {
    u = pos.y * l.uvScale[0] + l.uvOffset[0];
    const float phi = atan2f(pos.z, pos.x);
    v = (phi < 0.0f ? phi + TwoPi : phi) * OneOverTwoPi;
}


// Draws a direction toward the light from p, given the surface's culling normal
// n (null for a BSDF with transmission) and three uniform numbers. False when
// the light cannot be sampled from there (Light::sample).
// SphereLight's own latitude-longitude mapping, y up (local2uv in SphereLight.cc and .ispc).
X2_HD inline void sphereUv(const Light& l, V3 normal, bool ispc, Hit& h) {
    h.u = h.v = 0.0f;
    if (!l.image) return;
    const V3 local = rows(l.render2LocalRot, normal);
    if (fabsf(local.y) >= 1.0f) {
        h.v = local.y > 0.0f ? 0.0f : 1.0f;
        return;
    }
    const float theta = ispc ? dwAcos(local.y) : acosf(local.y);
    const float phi = atan2f(-local.z, -local.x);
    h.u = phi * OneOverTwoPi + 0.5f;
    h.v = theta * 0.31830988618379067154f;
}
X2_CALL bool sampleShapeHere(const Light& l, V3 p, const V3* n, const float r[3], V3& wi, Hit& h, float footprint = NoFootprint) {
    using namespace surface;
    switch (l.type) {
    case Env: {
        // EnvLight_sample: the texture's distribution, else the upper hemisphere or the whole sphere, uniformly.
        if (l.image) {
            float u, v;
            imageSample(*l.image, r[0], r[1], footprint - l.log2TexelAngle, l.filter, u, v);
            if (v < 0.0005f || v > 0.9995f) u = 0.0f;
            wi = rows(l.local2Render, uv2local(u, v));
            h.data0 = u;
            h.data1 = v;
        } else if (l.hemispherical) {
            const float cosTheta = r[0] > 1.0f ? 1.0f : r[0];
            wi = rows(l.local2Render, polar(cosTheta, sqrtf(1.0f - cosTheta * cosTheta), r[1] * TwoPi));
            h.data0 = h.data1 = 0.0f;
        } else {
            const float cosTheta = 1.0f - 2.0f * r[0];
            wi = polar(cosTheta, sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta)), r[1] * TwoPi);
            h.data0 = h.data1 = 0.0f;
        }
        if (n && dot(*n, wi) < Epsilon) return false;
        h.N = mul(wi, -1);
        h.distance = EnvDistance;
        return true;
    }
    case Distant: {
        if (l.image) {
            float u, v;
            imageSample(*l.image, r[0], r[1], footprint - l.log2TexelAngle, l.filter, u, v);
            const float U = u * 2.0f - 1.0f, V = v * 2.0f - 1.0f;
            if (U * U + V * V >= 1.0f) return false;
            wi = rows(l.local2Render, distantUvToLocal(l, u, v));
            h.data0 = u;
            h.data1 = v;
        } else {
            const float versine = fmaxf(r[0] * l.versineThetaMax, 0.0f);
            const float cosTheta = 1.0f - versine;
            const V3 cap = polar(cosTheta, sqrtf(fmaxf(0.0f, versine * (2.0f - versine))), r[1] * TwoPi);
            wi = rows(l.local2Render, mul(cap, -1));  // an orthonormal frame here
            h.data0 = h.data1 = 0.0f;
        }
        if (n && dot(*n, wi) < Epsilon) return false;
        h.N = mul(wi, -1);
        h.distance = DistantDistance;
        return true;
    }
    case Rect:
    case Disk: {
        const float distance = planeDistance(l, p);
        if (l.sidedness != TwoSided && distance < Epsilon) return false;
        V3 local;
        h.data0 = h.data1 = 0.0f;
        h.pdf = l.invArea;
        // The image's distribution, else the spread's overlap with the light, else the whole shape.
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        const float spreadLength = distance * l.tanSpreadTheta / l.scale;  // in local units
        bool uniform = true;
        if (l.image) {
            float u, v;
            imageSample(*l.image, r[0], r[1], 0.0f, l.filter, u, v);
            if (l.type == Disk) {
                const float x = u * 2.0f - 1.0f, y = v * 2.0f - 1.0f;
                if (x * x + y * y >= 1.0f) return false;
            }
            local = {(u - l.uvOffset[0]) / l.uvScale[0], (v - l.uvOffset[1]) / l.uvScale[1], 0.0f};
            h.data0 = u;
            h.data1 = v;
            if (l.spread < 1.f && outsideSpread(l, sub(local, localP))) return false;
            uniform = false;
        } else if (l.spread < 1.f) {
            const bool inside = l.type == Disk && localP.x - spreadLength < -1.f && localP.x + spreadLength > 1.f &&
                                localP.y - spreadLength < -1.f && localP.y + spreadLength > 1.f;
            if (!inside) {
                float cx, cy, w, hh;
                if (l.type == Rect ? !rectOverlap(l, localP.x, localP.y, spreadLength, cx, cy, w, hh)
                                   : !diskOverlap(localP.x, localP.y, spreadLength, cx, cy, w, hh))
                    return false;
                local = {(0.5f - r[0]) * w + cx, (0.5f - r[1]) * hh + cy, 0.0f};
                if (l.type == Disk && local.x * local.x + local.y * local.y > 1.f) return false;
                h.pdf = 1.f / ((w * l.scale) * (hh * l.scale));
                uniform = false;
            }
        }
        if (uniform) {
            if (l.type == Rect) {
                local = {(0.5f - r[0]) * (2 * l.halfWidth), (0.5f - r[1]) * (2 * l.halfHeight), 0.0f};
            } else {
                float s, c;
                sincosSample(TwoPi * r[1], s, c);
                const float radius = sqrtf(r[0]);
                local = {radius * c, radius * s, 0.0f};
            }
        }
        wi = sub(add(rows(l.local2Render, local), l.position), p);
        if (l.type == Disk && n && dot(*n, wi) < Epsilon) return false;
        h.distance = sqrtf(lengthSq(wi));
        if (h.distance < Epsilon) return false;
        wi = mul(wi, 1.0f / h.distance);
        if (l.type == Rect && n && dot(*n, wi) < Epsilon) return false;
        h.N = dot(l.direction, wi) < 0.0f ? l.direction : mul(l.direction, -1);
        return true;
    }
    case Mesh: {
        // MeshLight_sample: a face by r[2] down the tree, a point on it by r[0], r[1] (a quad's triangle by area).
        const MeshLightData& m = *l.mesh;
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        V3 localN{0, 0, 0};
        if (n) localN = rows(l.render2LocalRot, *n);
        float pdf = 1.0f;
        const int leaf = meshDrawSample(m, localP, n ? &localN : nullptr, r[2], pdf);
        if (!(pdf > 0.0f) || pdf > 3.4028234663852886e+38f) return false;
        const MeshFace& f = m.faces[m.nodes[leaf].face];
        V3 hit, normal;
        float u, v;
        if (f.count == 3) {
            const V3 p1 = m.vertices[f.v[0]], p2 = m.vertices[f.v[1]], p3 = m.vertices[f.v[2]];
            normal = f.normal;
            u = r[0];
            v = r[1];
            float w = 1.0f - u - v;
            if (w < 0.0f) {
                u = 1.0f - u;
                v = 1.0f - v;
                w = -w;
            }
            hit = add(add(mul(p1, w), mul(p2, u)), mul(p3, v));
        } else {
            const V3 v0 = m.vertices[f.v[0]], v1 = m.vertices[f.v[1]], v2 = m.vertices[f.v[2]], v3 = m.vertices[f.v[3]];
            const V3 n013 = surface::cross(sub(v1, v0), sub(v3, v0)), n231 = surface::cross(sub(v3, v2), sub(v1, v2));
            const float a013 = sqrtf(lengthSq(n013)), a231 = sqrtf(lengthSq(n231)), sum = a013 + a231;
            if (sum == 0.0f) return false;
            const float rSplit = a013 / sum;
            const bool first = r[0] < rSplit;
            V3 p1, p2, p3;
            if (first) {
                u = r[0] / rSplit;
                p1 = v0;
                p2 = v1;
                p3 = v3;
                normal = mul(n013, 1.0f / a013);
            } else {
                u = (r[0] - rSplit) / (1.0f - rSplit);
                p1 = v2;
                p2 = v3;
                p3 = v1;
                normal = mul(n231, 1.0f / a231);
            }
            v = r[1];
            float w = 1.0f - u - v;
            if (w < 0.0f) {
                u = 1.0f - u;
                v = 1.0f - v;
                w = -w;
            }
            hit = add(add(mul(p1, w), mul(p2, u)), mul(p3, v));
            if (!first) {
                u = 1.0f - u;
                v = 1.0f - v;
            }
        }
        wi = rows(l.local2Render, sub(hit, localP));
        h.distance = sqrtf(lengthSq(wi));
        if (h.distance > Epsilon) wi = mul(wi, 1.0f / h.distance);
        if (n && dot(*n, wi) < Epsilon) return false;
        h.N = dots(l.render2LocalRot, normal);
        h.pdf = pdf;
        h.face = U32(m.nodes[leaf].face);
        h.u = u;
        h.v = v;
        return true;
    }
    case Cylinder: {
        float u = r[0], v = r[1];
        if (l.image) imageSample(*l.image, r[0], r[1], 0.0f, l.filter, u, v);
        h.data0 = l.image ? u : 0.0f;
        h.data1 = l.image ? v : 0.0f;
        const V3 localHit = cylinderUv2Local(l, u, v);
        wi = sub(add(rows(l.local2Render, localHit), l.position), p);
        h.distance = sqrtf(lengthSq(wi));
        if (h.distance < Epsilon) return false;
        wi = mul(wi, 1.0f / h.distance);
        if (n && dot(*n, wi) < Epsilon) return false;
        V3 renderN;
        if (!normalize(dots(l.render2Local, V3{localHit.x, 0.0f, localHit.z}), renderN)) return false;
        h.N = l.sidedness == Regular ? renderN : mul(renderN, -1);
        if (dot(h.N, wi) > -Epsilon) return false;
        return true;
    }
    case Spot: {
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        if (localP.z <= 0.0f) return false;
        float s, c, lx, ly;
        sincosSample(TwoPi * r[1], s, c);
        const float dx = sqrtf(r[0]) * c, dy = sqrtf(r[0]) * s;
        if (localP.z > l.crossOverDistance) {
            lx = dx * l.lensRadius;
            ly = dy * l.lensRadiusY;
            float fx, fy;
            lensToFocal(l, lx, ly, localP, fx, fy);
            h.data0 = 0.5f * (fx * l.rcpFocalRadius) + 0.5f;
            h.data1 = -0.5f * (fy * l.rcpFocalRadiusY) + 0.5f;
        } else {
            focalToLens(l, dx * l.focalRadius, dy * l.focalRadiusY, localP, lx, ly);
            const float nx = lx * l.rcpLensRadius, ny = ly * l.rcpLensRadiusY;
            if (nx * nx + ny * ny > 1.0f) return false;
            h.data0 = 0.5f * dx + 0.5f;
            h.data1 = -0.5f * dy + 0.5f;
        }
        wi = sub(add(rows(l.local2Render, V3{lx, ly, 0.0f}), l.position), p);
        if (n && dot(*n, wi) <= 0.0f) return false;
        h.distance = sqrtf(lengthSq(wi));
        h.N = l.direction;
        wi = mul(wi, 1.0f / h.distance);
        return true;
    }
    case Sphere: {
        const V3 v = sub(l.position, p);
        const float v2 = dot(v, v), c = v2 - l.radiusSq;
        float t;
        V3 normal;
        if (c < 0.0f) {
            if (l.sidedness == Regular) return false;
            h.data1 = -1.0f;
            if (n) {
                const float cosTheta = r[0];
                wi = localToGlobal(*n, polar(cosTheta, sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta)), TwoPi * r[1]));
                h.data0 = OneOverTwoPi;
            } else {
                const float cosTheta = 2.0f * r[0] - 1.0f;
                wi = polar(cosTheta, sqrtf(fmaxf(0.0f, 1.0f - cosTheta * cosTheta)), TwoPi * r[1]);
                h.data0 = OneOverFourPi;
            }
            const float b = dot(wi, v), s = sqrtf(b * b - c);
            t = b + s;
            normal = mul(sub(mul(wi, t), v), l.rcpRadius);
        } else {
            const float sinThetaMaxSq = c / v2, sinThetaSq = r[0] * sinThetaMaxSq;
            const float sinTheta = sqrtf(sinThetaSq), cosTheta = sqrtf(1.0f - sinThetaSq);
            normal = localToGlobal(mul(v, -1.0f / sqrtf(v2)), polar(cosTheta, sinTheta, TwoPi * r[1]));
            const V3 rayDir = add(v, mul(normal, l.radius));
            t = sqrtf(lengthSq(rayDir));
            if (t < Epsilon) return false;
            wi = mul(rayDir, 1.0f / t);
            if (n && dot(*n, wi) < Epsilon) return false;
            h.data0 = cosTheta / sinThetaMaxSq;
            h.data1 = t;
            if (l.sidedness == Reverse) {
                const float b = dot(wi, v), d = l.radiusSq - lengthSq(sub(v, mul(wi, b)));
                t = b + sqrtf(fmaxf(d, 0.0f));
                normal = mul(sub(mul(wi, t), v), l.rcpRadius);
            }
        }
        h.N = l.sidedness == Regular ? normal : mul(normal, -1);
        h.distance = t;
        sphereUv(l, normal, true, h);
        return true;
    }
    }
    return false;
}

// The radiance arriving at p from the light along wi, and the solid-angle pdf of
// sampling it (Light::eval).
X2_CALL V3 evalShapeHere(const Light& l, V3 p, V3 wi, const Hit& h, float& pdf, float footprint = NoFootprint, bool fromCamera = false) {
    if (l.type == Env) {
        // EnvLight_eval: the texture at the hit's uv, its pdf over the sphere (2 pi^2 sin theta per unit uv).
        const float mip = footprint - l.log2TexelAngle;
        if (!l.image) {
            pdf = l.invArea;
            return {l.radiance.x * l.fallback.x, l.radiance.y * l.fallback.y, l.radiance.z * l.fallback.z};
        }
        const V3 t = imageEval(*l.image, h.data0, h.data1, mip, l.filter);
        const float sinTheta = fmaxf(sinf(h.data1 * Pi), SEpsilon);
        pdf = imagePdf(*l.image, h.data0, h.data1, mip, l.filter) / (2.0f * Pi * Pi * sinTheta);
        return {l.radiance.x * t.x, l.radiance.y * t.y, l.radiance.z * t.z};
    }
    if (l.type == Spot) {
        const float x = 2.0f * h.data0 - 1.0f, y = 2.0f * h.data1 - 1.0f;
        const float shaped = falloff(l.falloffType, (1.0f - sqrtf(x * x + y * y)) * l.falloffGradient);
        // SpotLight::eval: its texture at the focal plane, the cone's falloff (from the black level for the camera).
        V3 t = l.image ? imageEval(*l.image, h.data0, h.data1, 0.0f, l.filter) : l.fallback;
        t = fromCamera ? V3{lerpF(l.blackLevel, t.x, shaped), lerpF(l.blackLevel, t.y, shaped), lerpF(l.blackLevel, t.z, shaped)}
                       : surface::mul(t, shaped);
        const float scale = areaToSolidAngleScale(wi, h.N, h.distance);
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        if (localP.z > l.crossOverDistance) {
            pdf = l.invArea * scale;
        } else {
            const float zRatio = (l.focalDistance - localP.z) / localP.z;
            pdf = l.focalPlanePdfConst * scale * zRatio * zRatio;
        }
        return times(t, l.radiance);
    }
    if (l.type == Distant) {
        const float mip = footprint - l.log2TexelAngle;
        if (!l.image) {
            pdf = l.invArea;
            return times(l.radiance, l.fallback);
        }
        pdf = imagePdf(*l.image, h.data0, h.data1, mip, l.filter) * l.jacobian;
        return times(l.radiance, imageEval(*l.image, h.data0, h.data1, mip, l.filter));
    }
    if (l.type == Mesh) {
        pdf = h.pdf * areaToSolidAngleScale(wi, h.N, h.distance);
        return l.radiance;
    }
    if (l.type == Cylinder) {
        pdf = l.invArea;
        if (l.image) pdf *= imagePdf(*l.image, h.data0, h.data1, 0.0f, l.filter);
        pdf *= areaToSolidAngleScale(wi, h.N, h.distance);
        return times(l.radiance, l.image ? imageEval(*l.image, h.data0, h.data1, 0.0f, l.filter) : l.fallback);
    }
    if (l.type == Rect || l.type == Disk) {
        V3 radiance = l.radiance;
        if (l.spread < 1.f) radiance = surface::mul(radiance, spreadFactor(l, wi));
        radiance = times(radiance, l.image ? imageEval(*l.image, h.data0, h.data1, 0.0f, l.filter) : l.fallback);
        if (l.image) pdf = l.type == Rect ? l.invArea * imagePdf(*l.image, h.data0, h.data1, 0.0f, l.filter)
                                          : imagePdf(*l.image, h.data0, h.data1, 0.0f, l.filter) * l.distributionPdfScale;
        else pdf = l.spread < 1.f ? h.pdf : l.invArea;
        pdf *= areaToSolidAngleScale(wi, h.N, h.distance);
        return radiance;
    }
    switch (l.type) {
    case Sphere:
        pdf = h.data1 >= 0.0f ? h.data0 / (Pi * l.radiusSq) * areaToSolidAngleScale(wi, h.N, h.data1) : h.data0;
        break;
    default: pdf = 0.0f;
    }
    // A sphere's texture does not enter its pdf: it is not sampled by it.
    return times(l.radiance, l.type == Sphere && l.image ? imageEval(*l.image, h.u, h.v, 0.0f, l.filter) : l.fallback);
}

// Whether a ray from p along wi meets the light within maxDistance
// (Light::intersect), for MIS of BSDF samples. n is the culling normal, as in sample().
// fromCamera: a camera ray's (Scene::intersectVisibleLight, MoonRay's C++, acos) rather than a shading point's (the
// ISPC light set, dw_acos).
X2_CALL bool intersectShapeHere(const Light& l, V3 p, const V3* n, V3 wi, float maxDistance, Hit& h, bool fromCamera = false) {
    using namespace surface;
    switch (l.type) {
    case Env:
        if (l.hemispherical && dot(wi, l.direction) < 0.0f) return false;
        if (EnvDistance > maxDistance) return false;
        h.N = mul(wi, -1);
        h.distance = EnvDistance;
        h.data0 = h.data1 = 0.0f;
        if (l.image) local2uv(dots(l.local2Render, wi), !fromCamera, h.data0, h.data1);
        return true;
    case Distant:
        if (dot(wi, l.direction) > -l.cosThetaMax || DistantDistance > maxDistance) return false;
        h.N = mul(wi, -1);
        h.distance = DistantDistance;
        h.data0 = h.data1 = 0.0f;
        if (l.image) distantLocalToUv(l, dots(l.local2Render, wi), h.data0, h.data1);
        return true;
    case Rect:
    case Disk: {
        const V3 localWi = rows(l.render2LocalRot, wi), localP = rows(l.render2Local, sub(p, l.position));
        if (rejectPosDirSidedness(l, localP.z, localWi.z)) return false;
        const float localDistance = -localP.z / localWi.z, renderDistance = l.scale * localDistance;
        if (renderDistance > maxDistance) return false;
        const V3 hit = add(localP, mul(localWi, localDistance));
        if (l.type == Rect ? (fabsf(hit.x) >= l.halfWidth || fabsf(hit.y) >= l.halfHeight)
                           : (hit.x * hit.x + hit.y * hit.y > 1.0f))
            return false;
        h.pdf = l.invArea;
        if (l.spread < 1.f) {
            if (outsideSpread(l, localWi)) return false;
            float cx, cy, w, hh;
            const float spreadLength = localP.z * l.tanSpreadTheta;
            if (l.type == Rect) rectOverlap(l, localP.x, localP.y, spreadLength, cx, cy, w, hh);
            else diskOverlap(localP.x, localP.y, spreadLength, cx, cy, w, hh);
            h.pdf = 1.f / ((w * l.scale) * (hh * l.scale));
        }
        h.data0 = l.image ? hit.x * l.uvScale[0] + l.uvOffset[0] : 0.0f;
        h.data1 = l.image ? hit.y * l.uvScale[1] + l.uvOffset[1] : 0.0f;
        h.N = localWi.z < 0.0f ? l.direction : mul(l.direction, -1);
        h.distance = renderDistance;
        return true;
    }
    case Mesh: {
        // MeshLight_intersect: the light's mesh in its local space, the face's pdf up the tree.
        const MeshLightData& m = *l.mesh;
        const V3 localP = rows(l.render2Local, sub(p, l.position)), localW = rows(l.render2LocalRot, wi);
        float tfar = maxDistance, u = 0.0f, v = 0.0f;
        const int leaf = meshIntersect(m, localP, localW, tfar, u, v);
        if (leaf < 0) return false;
        V3 localN{0, 0, 0};
        if (n) localN = rows(l.render2LocalRot, *n);
        const MeshFace& f = m.faces[m.nodes[leaf].face];
        h.pdf = f.invArea * meshLeafPdf(m, leaf, localP, n ? &localN : nullptr);
        h.N = dots(l.render2LocalRot, f.normal);
        h.distance = tfar * l.scale;
        h.face = U32(m.nodes[leaf].face);
        h.u = u;
        h.v = v;
        return true;
    }
    case Cylinder: {
        const V3 e = l.axis, dp = sub(l.position, p);
        const float A = dot(dp, e), B = dot(wi, e);
        const float signB = B > 0.0f ? 1.0f : B < 0.0f ? -1.0f : 0.0f;
        if (A * signB <= -l.actualHalfHeight) return false;
        const float C = dot(dp, wi), b = C - A * B, c = lengthSq(dp) - A * A - l.radiusSq;
        if (c > 0.0f ? b <= 0.0f : l.sidedness == Regular) return false;
        const float a = 1.0f - B * B, D = b * b - a * c;
        if (D <= 0.0f) return false;
        const float s = sqrtf(D);
        const float t = l.sidedness == Regular ? (b - s) / a : (b + s) / a;
        if (a == 0.0f || t < 0.0f || t > maxDistance) return false;
        const float y = t * B - A;
        if (fabsf(y) > l.actualHalfHeight) return false;
        const V3 hitPoint = sub(mul(wi, t), dp);
        h.N = mul(sub(hitPoint, mul(e, y)), l.sidedness == Regular ? l.rcpRadius : -l.rcpRadius);
        h.data0 = h.data1 = 0.0f;
        if (l.image) cylinderLocal2Uv(l, rows(l.render2Local, hitPoint), h.data0, h.data1);
        h.distance = t;
        return true;
    }
    case Spot: {
        const V3 localWi = rows(l.render2LocalRot, wi);
        if (localWi.z >= 0.0f) return false;
        const V3 localP = rows(l.render2Local, sub(p, l.position));
        if (localP.z <= 0.0f) return false;
        const float localDistance = -localP.z / localWi.z, renderDistance = l.scale * localDistance;
        if (renderDistance > maxDistance) return false;
        const float lx = localP.x + localDistance * localWi.x, ly = localP.y + localDistance * localWi.y;
        const float nx = lx * l.rcpLensRadius, ny = ly * l.rcpLensRadiusY;
        if (nx * nx + ny * ny > 1.0f) return false;
        h.N = l.direction;
        h.distance = renderDistance;
        float fx, fy;
        lensToFocal(l, lx, ly, localP, fx, fy);
        h.data0 = 0.5f * (fx * l.rcpFocalRadius) + 0.5f;
        h.data1 = -0.5f * (fy * l.rcpFocalRadiusY) + 0.5f;
        return true;
    }
    case Sphere: {
        const V3 v = sub(l.position, p);
        const float b = dot(wi, v), v2 = dot(v, v), c = v2 - l.radiusSq;
        if (c > 0.0f ? b <= 0.0f : l.sidedness == Regular) return false;
        const float d = l.radiusSq - lengthSq(sub(v, mul(wi, b)));
        if (d <= 0.0f) return false;
        const float s = sqrtf(d), t = l.sidedness == Regular ? b - s : b + s;
        if (t > maxDistance) return false;
        const V3 normal = mul(sub(mul(wi, t), v), l.rcpRadius);
        h.N = l.sidedness == Regular ? normal : mul(normal, -1);
        h.distance = t;
        sphereUv(l, normal, !fromCamera, h);
        if (c < 0.0f) {
            h.data1 = -1.0f;
            h.data0 = n ? OneOverTwoPi : OneOverFourPi;
        } else {
            const float sinThetaMaxSq = c / v2;
            float cosTheta;
            if (l.sidedness == Reverse) {
                const float front = b - s;
                cosTheta = -dot(v, mul(sub(mul(wi, front), v), l.rcpRadius)) / sqrtf(v2);
                h.data1 = front;
            } else {
                cosTheta = -dot(v, normal) / sqrtf(v2);
                h.data1 = t;
            }
            h.data0 = cosTheta / sinThetaMaxSq;
        }
        return true;
    }
    }
    return false;
}


// ---- PortalLight (PortalLight.ispc): its rect (the light as a RectLight), its reference's sample through it (an
// environment) or its own (a distant light), the reference's radiance times the rect's. No light beyond the portal
// (canIlluminate). The shapes' functions are called directly: no recursion on the GPU.
// The light module's callables' places in the GPU program's binding table (async_gpu_device.h's MaterialCall).
// (An enumerator, not a constexpr: no global in every relocatable module.)
enum : U32 { LightSampleCallable = 3, LightIntersectCallable = 4, LightEvalCallable = 5 };
// The shapes as the path tracer calls them: on the GPU, in a program built in modules (XPU2_LIGHT_MODULE), the light
// module's callables (async_lights.cu); elsewhere the functions themselves.
X2_HD inline bool sampleShape(const Light& l, V3 p, const V3* n, const float r[3], V3& wi, Hit& h, float footprint = NoFootprint) {
#if defined(__CUDACC__) && defined(XPU2_LIGHT_MODULE)
    return optixDirectCall<bool, const Light*, V3, const V3*, const float*, V3*, Hit*, float>(LightSampleCallable, &l, p, n, r, &wi, &h,
                                                                                             footprint);
#else
    return sampleShapeHere(l, p, n, r, wi, h, footprint);
#endif
}
X2_HD inline bool intersectShape(const Light& l, V3 p, const V3* n, V3 wi, float maxDistance, Hit& h, bool fromCamera = false) {
#if defined(__CUDACC__) && defined(XPU2_LIGHT_MODULE)
    return optixDirectCall<bool, const Light*, V3, const V3*, V3, float, Hit*, bool>(LightIntersectCallable, &l, p, n, wi, maxDistance, &h,
                                                                                     fromCamera);
#else
    return intersectShapeHere(l, p, n, wi, maxDistance, h, fromCamera);
#endif
}
X2_HD inline V3 evalShape(const Light& l, V3 p, V3 wi, const Hit& h, float& pdf, float footprint = NoFootprint, bool fromCamera = false) {
#if defined(__CUDACC__) && defined(XPU2_LIGHT_MODULE)
    V3 out{0, 0, 0};
    optixDirectCall<void, const Light*, V3, V3, const Hit*, float*, float, bool, V3*>(LightEvalCallable, &l, p, wi, &h, &pdf, footprint,
                                                                                      fromCamera, &out);
    return out;
#else
    return evalShapeHere(l, p, wi, h, pdf, footprint, fromCamera);
#endif
}
X2_HD inline Light portalRect(const Light& l) {
    Light r = l;
    r.type = Rect;
    return r;
}
X2_HD inline bool beyondPortal(const Light& l, V3 p) { return rows(l.render2Local, sub(p, l.position)).z <= 0.0f; }
X2_HD inline bool sample(const Light& l, V3 p, const V3* n, const float r[3], V3& wi, Hit& h, float footprint = NoFootprint) {
    if (l.type != Portal) return sampleShape(l, p, n, r, wi, h, footprint);
    if (beyondPortal(l, p)) return false;
    if (l.ref->type == Env) {
        Hit hr;
        return sampleShape(portalRect(l), p, n, r, wi, hr, footprint) &&
               intersectShape(*l.ref, p, n, wi, 3.4028234663852886e+38f, h);
    }
    return sampleShape(*l.ref, p, n, r, wi, h, footprint);
}
// cameraRay: a camera ray, which sees the portal from anywhere (the visible light set is not culled).
X2_HD inline bool intersect(const Light& l, V3 p, const V3* n, V3 wi, float maxDistance, Hit& h, bool fromCamera = false,
                            bool cameraRay = false) {
    if (l.type != Portal) return intersectShape(l, p, n, wi, maxDistance, h, fromCamera);
    if (!cameraRay && beyondPortal(l, p)) return false;
    Hit hr;
    return intersectShape(portalRect(l), p, n, wi, maxDistance, hr, fromCamera) &&
           intersectShape(*l.ref, p, n, wi, maxDistance, h, fromCamera);
}
X2_HD inline V3 eval(const Light& l, V3 p, V3 wi, const Hit& h, float& pdf, float footprint = NoFootprint, bool fromCamera = false) {
    if (l.type != Portal) return evalShape(l, p, wi, h, pdf, footprint, fromCamera);
    const Light rect = portalRect(l);
    Hit hr;
    pdf = 0.0f;
    if (!intersectShape(rect, p, nullptr, wi, 3.4028234663852886e+38f, hr)) return V3{0, 0, 0};
    float pdfRef = 0.0f, pdfRect = 0.0f;
    const V3 radiance = evalShape(*l.ref, p, wi, h, pdfRef, footprint, fromCamera);
    const V3 portal = evalShape(rect, p, wi, hr, pdfRect, footprint, fromCamera);
    pdf = l.ref->type == Distant ? pdfRef : pdfRect;
    return times(radiance, portal);
}

// Light::canIlluminate (computeActiveLights' culling, before a hit's light samples): false where the light lies wholly
// behind the point's culling plane n (none: no culling), its threshold eased by the subsurface's reach (radius), or
// the point wholly behind a one-sided rect or disk, inside an outward sphere, or beyond a portal. An environment or
// distant light a portal references lights no point itself. Cylinders and meshes cull nothing (their light filters
// alone would).
X2_CALL bool canIlluminate(const Light& l, V3 p, const V3* n, float radius) {
    using namespace surface;
    const float threshold = Epsilon - radius;
    auto corners = [&](float hx, float hy) {
        if (!n) return true;
        const float c[4][2] = {{hx, hy}, {hx, -hy}, {-hx, hy}, {-hx, -hy}};
        for (int i = 0; i < 4; ++i)
            if (dot(*n, sub(add(rows(l.local2Render, V3{c[i][0], c[i][1], 0.0f}), l.position), p)) > threshold) return true;
        return false;
    };
    switch (l.type) {
    case Env: return !l.hasPortal;
    case Distant: {
        if (l.hasPortal) return false;
        const float cullThreshold = -cosf(fminf(acosf(fminf(fmaxf(l.cosThetaMax, -1.0f), 1.0f)) + 0.5f * Pi, Pi));
        return !(n && dot(*n, l.direction) > cullThreshold);
    }
    case Rect:
        if (l.sidedness != TwoSided && planeDistance(l, p) < threshold) return false;
        return corners(l.halfWidth, l.halfHeight);
    case Portal:
        if (beyondPortal(l, p)) return false;
        return corners(l.halfWidth, l.halfHeight);
    case Spot: return corners(l.lensRadius, l.lensRadiusY);
    case Disk: {
        if (l.sidedness != TwoSided && planeDistance(l, p) < threshold) return false;
        if (!n) return true;
        // The disk's point furthest along n: n in the light's frame, flattened onto the unit circle.
        V3 local = rows(l.render2LocalRot, *n);
        local.z = 0.0f;
        const float rcpLength = 1.0f / sqrtf(local.x * local.x + local.y * local.y);
        if (rcpLength < 1.0f / Epsilon) local = V3{local.x * rcpLength, local.y * rcpLength, 0.0f};
        else local = V3{1.0f, 0.0f, 0.0f};
        return dot(*n, sub(add(rows(l.local2Render, local), l.position), p)) > threshold;
    }
    case Sphere: {
        if (n && dot(*n, sub(l.position, p)) < Epsilon - l.radius - radius) return false;
        if (l.sidedness == Regular) {
            const float inside = l.radius + Epsilon - radius;
            if (lengthSq(sub(p, l.position)) < inside * inside) return false;
        }
        return true;
    }
    default: return true;
    }
}

}  // namespace xpu2::interactive::lights
