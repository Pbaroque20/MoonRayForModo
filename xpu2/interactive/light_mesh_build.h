// Host side of MoonRay's MeshLight (light_core.h): its faces from a mesh as MoonRay tessellates it, and the sampling
// BVH over them (Estevez and Kulla 2017's SAOH tree) built as MeshLight::buildBVHRecurse builds it, in the same
// order, so that each face is chosen with MoonRay's probabilities.
//
// Adapted from MoonRay pbr/light/MeshLight.cc, Apache-2.0, copyright 2023-2024 DreamWorks Animation LLC;
// see MOONRAY_LICENSE.txt.
#pragma once
#include "light_core.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <utility>
#include <vector>

namespace xpu2::interactive::lights {

// A mesh light's tables (host memory), which MeshLightData points into.
struct MeshLightTables {
    std::vector<MeshNode> nodes;
    std::vector<MeshFace> faces;
    std::vector<V3> vertices;
    MeshLightData view{};
    float area = 0.0f;  // the faces' summed area, local units
    void point() {
        view.nodes = nodes.data();
        view.faces = faces.data();
        view.vertices = vertices.data();
        view.nodeCount = U32(nodes.size());
        view.faceCount = U32(faces.size());
    }
};

namespace meshbuild {
constexpr int BucketsCount = 8;
constexpr float ThetaE = 1.57079632679489661923f;
constexpr float PiF = 3.14159265358979323846f;
constexpr float Eps = 1e-6f;

struct F3 {
    float x = 0, y = 0, z = 0;
    float operator[](int i) const { return i == 0 ? x : i == 1 ? y : z; }
};
inline F3 operator+(F3 a, F3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline F3 operator-(F3 a, F3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline F3 operator*(float s, F3 a) { return {s * a.x, s * a.y, s * a.z}; }
inline F3 operator*(F3 a, float s) { return {a.x * s, a.y * s, a.z * s}; }
inline float dot(F3 a, F3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline F3 cross(F3 a, F3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
inline float length(F3 a) { return std::sqrt(dot(a, a)); }
inline F3 normalize(F3 a) { const float l = length(a); return {a.x / l, a.y / l, a.z / l}; }
inline bool isEqual(float a, float b) { return std::fabs(a - b) <= std::max(std::fabs(a), 1.0f) * Eps; }

struct Box {
    F3 lower{std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity(), std::numeric_limits<float>::infinity()};
    F3 upper{-std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity()};
    void extend(F3 p) {
        lower = {std::min(lower.x, p.x), std::min(lower.y, p.y), std::min(lower.z, p.z)};
        upper = {std::max(upper.x, p.x), std::max(upper.y, p.y), std::max(upper.z, p.z)};
    }
    void extend(const Box& b) {
        lower = {std::min(lower.x, b.lower.x), std::min(lower.y, b.lower.y), std::min(lower.z, b.lower.z)};
        upper = {std::max(upper.x, b.upper.x), std::max(upper.y, b.upper.y), std::max(upper.z, b.upper.z)};
    }
    bool empty() const { return lower.x > upper.x || lower.y > upper.y || lower.z > upper.z; }
    F3 size() const { return upper - lower; }
};
// scene_rdl2's maxDim.
inline int maxDim(F3 a) { return a.x > a.y ? (a.x > a.z ? 0 : 2) : (a.y > a.z ? 1 : 2); }

struct Cone {
    F3 axis;
    float thetaO = 0;
};
// combineBoundingCones (Kulla 2017, Algorithm 1).
inline Cone combine(const Cone* a, const Cone* b) {
    if (b->thetaO > a->thetaO) std::swap(a, b);
    if (a->thetaO > PiF) return *a;
    const float cosThetaD = std::min(std::max(dot(a->axis, b->axis), -1.0f), 1.0f);
    const float thetaD = std::acos(cosThetaD);
    if (thetaD + b->thetaO <= a->thetaO) return *a;
    const float thetaO = (a->thetaO + thetaD + b->thetaO) / 2.0f;
    if (PiF <= thetaO) return {a->axis, PiF};
    F3 rotAxis = cross(a->axis, b->axis);
    if (std::fabs(length(rotAxis)) <= Eps) return {{1.f, 0.f, 0.f}, PiF};
    rotAxis = normalize(rotAxis);
    const float thetaR = thetaO - a->thetaO;
    return {std::cos(thetaR) * a->axis + std::sin(thetaR) * cross(rotAxis, a->axis), thetaO};
}

struct Face {
    unsigned v[4] = {0, 0, 0, 0};
    unsigned count = 3, prim = 0;
    F3 center, normal;
    float invArea = 0, energy = 0, thetaO = 0;
};
struct Node {
    float energy = 0;
    int right = -1, parent = 0, face = -1;
    Cone cone;
    Box box;
};
struct Bucket {
    float energy = 0;
    Box box;
    Cone cone{{0, 0, 0}, 0};
};
struct SplitCost {
    float leftEnergy = 0, rightEnergy = 0;
    Box leftBox, rightBox;
    Cone leftCone{{0, 0, 0}, 0}, rightCone{{0, 0, 0}, 0};
    static float orientation(float thetaO) {
        const float thetaW = std::min(thetaO + ThetaE, PiF);
        return (PiF / 2) * (4 - 3 * std::cos(thetaO) + 2 * (thetaW - thetaO) * std::sin(thetaO) - std::cos(thetaO - 2 * thetaW));
    }
    static float area(F3 d) { return d[0] * d[1] + d[1] * d[2] + d[2] * d[0]; }
    float eval(float splitCoefficient) const {
        const float lo = orientation(leftCone.thetaO), ro = orientation(rightCone.thetaO);
        const Cone c = combine(&leftCone, &rightCone);
        const float co = orientation(c.thetaO);
        const float la = area(leftBox.size()), ra = area(rightBox.size());
        Box all = leftBox;
        all.extend(rightBox);
        const float ca = area(all.size());
        return (leftEnergy * la * lo + rightEnergy * ra * ro) * splitCoefficient / (ca * co);
    }
};

struct Builder {
    const std::vector<F3>& vertices;
    std::vector<Face>& faces;
    std::vector<Node> bvh;
    F3 vertex(const Face& f, unsigned i) const { return vertices[f.v[i]]; }
    void cornerBounds(int start, int end, Box& b) const {
        for (int i = start; i < end; ++i)
            for (unsigned j = 0; j < faces[size_t(i)].count; ++j) b.extend(vertex(faces[size_t(i)], j));
    }
    int naiveSplit(int start, int end, int axis, Box& left, Box& right) {
        left = Box();
        right = Box();
        const int mid = (start + end) / 2;
        std::nth_element(faces.begin() + start, faces.begin() + mid, faces.begin() + end,
                         [&](const Face& a, const Face& b) { return a.center[axis] < b.center[axis]; });
        cornerBounds(start, mid, left);
        cornerBounds(mid, end, right);
        return mid;
    }
    Cone facesCone(int start, int end) const {
        Cone cone{faces[size_t(start)].normal, faces[size_t(start)].thetaO};
        for (int i = start + 1; i < end; ++i) {
            const Cone fc{faces[size_t(i)].normal, faces[size_t(i)].thetaO};
            cone = combine(&cone, &fc);
        }
        return cone;
    }
    int build(const Box& box, int start, int end, int parent) {
        if (end - start < BucketsCount) {
            const int index = int(bvh.size());
            bvh.push_back(Node());
            if (end - start > 1) {
                float energy = 0.0f;
                for (int i = start; i < end; ++i) energy += faces[size_t(i)].energy;
                const Cone cone = facesCone(start, end);
                bvh[size_t(index)].parent = parent;
                bvh[size_t(index)].box = box;
                bvh[size_t(index)].cone = cone;
                bvh[size_t(index)].energy = energy;
                bvh[size_t(index)].face = -1;
                Box left, right;
                const int mid = naiveSplit(start, end, maxDim(box.size()), left, right);
                build(left, start, mid, index);
                const int r = build(right, mid, end, index);
                bvh[size_t(index)].right = r;
            } else {
                Node& n = bvh[size_t(index)];
                n.parent = parent;
                n.energy = faces[size_t(start)].energy;
                n.face = start;
                n.box = box;
                n.cone = {faces[size_t(start)].normal, faces[size_t(start)].thetaO};
                n.right = -1;
            }
            return index;
        }
        // The surface area orientation heuristic, over buckets of face centres.
        Box centroids;
        for (int i = start; i < end; ++i) centroids.extend(faces[size_t(i)].center);
        const F3 csize = centroids.size(), pMin = centroids.lower;
        float minCosts[3];
        std::pair<Box, Box> minBoxes[3];
        std::pair<Cone, Cone> minCones[3];
        for (int axis = 0; axis < 3; ++axis) {
            if (csize[axis] == 0.f) {
                minCosts[axis] = std::numeric_limits<float>::infinity();
                continue;
            }
            minBoxes[axis] = {Box(), Box()};
            Bucket buckets[BucketsCount];
            const float stride = csize[axis] / BucketsCount;
            for (int i = start; i < end; ++i) {
                const Face& f = faces[size_t(i)];
                const int b = int(std::min(std::max(std::floor((f.center[axis] - pMin[axis]) / stride), 0.0f), float(BucketsCount - 1)));
                buckets[b].energy += f.energy;
                const Cone fc{f.normal, f.thetaO};
                if (buckets[b].box.empty()) buckets[b].cone = fc;
                else buckets[b].cone = combine(&buckets[b].cone, &fc);
                buckets[b].box.extend(f.center);
            }
            Bucket used[BucketsCount];
            int count = 0;
            for (int i = 0; i < BucketsCount; ++i)
                if (!buckets[i].box.empty()) used[count++] = buckets[i];
            const float splitCoefficient = csize[maxDim(csize)] / csize[axis];
            if (count == 2) {
                minBoxes[axis] = {used[0].box, used[1].box};
                minCones[axis] = {used[0].cone, used[1].cone};
                SplitCost cost;
                cost.leftEnergy = used[0].energy;
                cost.leftBox = used[0].box;
                cost.leftCone = used[0].cone;
                cost.rightEnergy = used[1].energy;
                cost.rightBox = used[1].box;
                cost.rightCone = used[1].cone;
                minCosts[axis] = cost.eval(splitCoefficient);
            } else {
                const int splits = count - 1;
                std::vector<SplitCost> costs(size_t(std::max(splits, 1)));
                costs[0].leftEnergy = used[0].energy;
                costs[0].leftBox = used[0].box;
                costs[0].leftCone = used[0].cone;
                costs[size_t(splits - 1)].rightEnergy = used[count - 1].energy;
                costs[size_t(splits - 1)].rightBox = used[count - 1].box;
                costs[size_t(splits - 1)].rightCone = used[count - 1].cone;
                for (int i = 1; i < splits; ++i) {
                    costs[size_t(i)].leftEnergy = used[i].energy + costs[size_t(i - 1)].leftEnergy;
                    costs[size_t(i)].leftBox = used[i].box;
                    costs[size_t(i)].leftBox.extend(costs[size_t(i - 1)].leftBox);
                    costs[size_t(i)].leftCone = combine(&used[i].cone, &costs[size_t(i - 1)].leftCone);
                }
                for (int i = splits - 2; i >= 0; --i) {
                    costs[size_t(i)].rightEnergy = used[i + 1].energy + costs[size_t(i + 1)].rightEnergy;
                    costs[size_t(i)].rightBox = used[i + 1].box;
                    costs[size_t(i)].rightBox.extend(costs[size_t(i + 1)].rightBox);
                    costs[size_t(i)].rightCone = combine(&used[i + 1].cone, &costs[size_t(i + 1)].rightCone);
                }
                float minCost = costs[0].eval(splitCoefficient);
                int best = 0;
                for (int i = 1; i < splits; ++i) {
                    const float c = costs[size_t(i)].eval(splitCoefficient);
                    if (c < minCost) {
                        minCost = c;
                        best = i;
                    }
                }
                minCosts[axis] = minCost;
                minBoxes[axis] = {costs[size_t(best)].leftBox, costs[size_t(best)].rightBox};
                minCones[axis] = {costs[size_t(best)].leftCone, costs[size_t(best)].rightCone};
            }
        }
        int axis = 0;
        float minCost = minCosts[0];
        for (int i = 1; i < 3; ++i)
            if (minCosts[i] < minCost) {
                axis = i;
                minCost = minCosts[i];
            }
        Box left = minBoxes[axis].first, right = minBoxes[axis].second;
        const float splitAt = left.upper[axis];
        const auto pMid = std::partition(faces.begin() + start, faces.begin() + end,
                                         [&](const Face& f) { return f.center[axis] <= splitAt; });
        int mid = int(pMid - faces.begin());
        Cone cone;
        if (mid == start || mid == end) {
            mid = naiveSplit(start, end, maxDim(csize), left, right);
            cone = facesCone(start, end);
        } else {
            cornerBounds(start, mid, left);
            cornerBounds(mid, end, right);
            cone = combine(&minCones[axis].first, &minCones[axis].second);
        }
        Node node;
        node.parent = parent;
        node.box = box;
        node.cone = cone;
        node.face = -1;
        node.energy = 0.0f;
        for (int i = start; i < end; ++i) node.energy += faces[size_t(i)].energy;
        const int index = int(bvh.size());
        bvh.push_back(node);
        build(left, start, mid, index);
        const int r = build(right, mid, end, index);
        bvh[size_t(index)].right = r;
        return index;
    }
};
}  // namespace meshbuild

// A mesh light's faces (MeshLight::setMesh) from its mesh's vertices (in the light's local space: the geometry's
// world space) and faces as MoonRay tessellates the mesh, three or four corners each (a QuadMesh's triangle repeats
// its third), and its sampling BVH (MeshLight::finalize). Null when it has no faces or no area: the light is off.
inline std::shared_ptr<MeshLightTables> buildMeshLight(const std::vector<V3>& positions, const std::vector<unsigned>& corners,
                                                       unsigned cornersPerFace, const std::vector<unsigned>& prims) {
    using namespace meshbuild;
    std::vector<F3> vertices;
    vertices.reserve(positions.size());
    for (const V3& p : positions) vertices.push_back({p.x, p.y, p.z});
    const size_t faceCount = corners.size() / cornersPerFace;
    if (faceCount == 0) return nullptr;
    std::vector<Face> faces(faceCount);
    Box local;
    float area = 0.0f;
    for (size_t f = 0; f < faceCount; ++f) {
        Face& face = faces[f];
        face.count = cornersPerFace;
        face.prim = prims[f];
        for (unsigned j = 0; j < cornersPerFace; ++j) {
            face.v[j] = corners[f * cornersPerFace + j];
            local.extend(vertices[face.v[j]]);
        }
        const F3 v0 = vertices[face.v[0]], v1 = vertices[face.v[1]], v2 = vertices[face.v[2]];
        face.center = v0 + v1 + v2;
        if (cornersPerFace == 4) {
            face.center = face.center + vertices[face.v[3]];
            face.center = face.center * 0.25f;
        } else {
            face.center = face.center * (1.0f / 3.0f);
        }
        float a = 0.f;
        const bool triangle = cornersPerFace == 3 || (v2.x == vertices[face.v[3]].x && v2.y == vertices[face.v[3]].y && v2.z == vertices[face.v[3]].z);
        if (triangle) {
            const F3 n = cross(v1 - v0, v2 - v0);
            a = 0.5f * length(n);
            face.normal = normalize(n);
            face.thetaO = 0.0f;
        } else {
            const F3 v3 = vertices[face.v[3]];
            const F3 c1 = cross(v1 - v0, v3 - v0), c2 = cross(v3 - v2, v1 - v2);
            a = float(0.5 * length(c1));
            a += 0.5f * length(c2);
            face.normal = normalize(c1 + c2);
            const F3 normals[2] = {normalize(c1), normalize(c2)};
            float minCos = 1.f;
            for (const F3& n : normals) minCos = std::min(minCos, dot(face.normal, n));
            face.thetaO = std::acos(std::min(std::max(minCos, -1.f), 1.f));
        }
        // A face of no area: no energy, never chosen, and a unit normal in place of MoonRay's NaN.
        if (!(a > 0.0f) || !std::isfinite(face.normal.x)) {
            face.normal = {0.f, 0.f, 1.f};
            face.thetaO = 0.0f;
        }
        area += a;
        face.invArea = a > 0.0f ? 1.0f / a : 0.0f;
        face.energy = 1.0f * a;
    }
    if (std::fabs(area) <= Eps) return nullptr;
    Builder b{vertices, faces, {}};
    b.build(local, 0, int(faceCount), 0);
    auto out = std::make_shared<MeshLightTables>();
    out->area = area;
    out->vertices = positions;
    out->faces.reserve(faces.size());
    for (const Face& f : faces) {
        MeshFace m{};
        for (int j = 0; j < 4; ++j) m.v[j] = f.v[j];
        m.count = f.count;
        m.prim = f.prim;
        m.normal = {f.normal.x, f.normal.y, f.normal.z};
        m.invArea = f.invArea;
        out->faces.push_back(m);
    }
    out->nodes.reserve(b.bvh.size());
    for (size_t i = 0; i < b.bvh.size(); ++i) {
        const Node& n = b.bvh[i];
        MeshNode m{};
        m.lower = {n.box.lower.x, n.box.lower.y, n.box.lower.z};
        m.upper = {n.box.upper.x, n.box.upper.y, n.box.upper.z};
        const F3 center = n.face >= 0 ? faces[size_t(n.face)].center : 0.5f * (n.box.lower + n.box.upper);
        m.center = {center.x, center.y, center.z};
        m.radius = length(n.box.upper - center);
        m.axis = {n.cone.axis.x, n.cone.axis.y, n.cone.axis.z};
        m.thetaO = n.cone.thetaO;
        m.energy = n.energy;
        m.right = n.right;
        m.parent = i == 0 ? -1 : n.parent;
        m.face = n.face;
        out->nodes.push_back(m);
    }
    out->point();
    return out;
}

}  // namespace xpu2::interactive::lights
