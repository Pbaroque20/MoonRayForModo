// Host side of MoonRay's light tree (light_tree.h): LightTree::build over one light set's bounded lights, as
// MoonRay builds it (LightTree.cc, LightTreeUtil.cc), its quirks included: twelve buckets an axis, the last non-empty
// bucket dropped when the bucket after it is empty (purgeEmptyBuckets), and nodes taking a split's energy, cone and
// bounds rather than their own lights'.
//
// Adapted from MoonRay pbr/light/LightTree.cc, LightTree.h, LightTreeUtil.cc and LightTreeUtil.h, Apache-2.0,
// copyright 2024 DreamWorks Animation LLC; see MOONRAY_LICENSE.txt.
#pragma once
#include "light_tree.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <utility>
#include <vector>

namespace xpu2::interactive::lights {
namespace treebuild {
constexpr float PiF = 3.14159265358979323846f, HalfPiF = 1.57079632679489661923f, EpsF = 1e-6f;

struct Box {
    V3 lower{3.402823466e+38f, 3.402823466e+38f, 3.402823466e+38f}, upper{-3.402823466e+38f, -3.402823466e+38f, -3.402823466e+38f};
    void extend(const Box& b) {
        lower = {std::min(lower.x, b.lower.x), std::min(lower.y, b.lower.y), std::min(lower.z, b.lower.z)};
        upper = {std::max(upper.x, b.upper.x), std::max(upper.y, b.upper.y), std::max(upper.z, b.upper.z)};
    }
    V3 size() const { return sub(upper, lower); }
};
inline float at(V3 v, int i) { return i == 0 ? v.x : i == 1 ? v.y : v.z; }
inline int maxDim(V3 a) { return a.x > a.y ? (a.x > a.z ? 0 : 2) : (a.y > a.z ? 1 : 2); }

struct Cone {
    V3 axis{0, 0, 0};
    float cosO = 0, sinO = 0, cosE = 0;
    bool twoSided = false;
    Cone() = default;
    Cone(V3 a, float cosThetaO, float cosThetaE, bool ts)
        : axis(a), cosO(std::min(std::max(cosThetaO, -1.f), 1.f)), sinO(std::sqrt(1.f - cosO * cosO)),
          cosE(std::min(std::max(cosThetaE, -1.f), 1.f)), twoSided(ts) {}
    bool empty() const { return axis.x == 0.f && axis.y == 0.f && axis.z == 0.f; }
    float thetaO() const { return dwAcos(cosO); }
    float thetaE() const { return dwAcos(cosE); }
};
// combineCones (LightTreeUtil.cc); the axes' cosine is clamped, where MoonRay's acos would make NaN of a rounding.
inline Cone combine(const Cone& a, const Cone& b) {
    if (a.empty()) return b;
    if (b.empty()) return a;
    const bool bFirst = b.cosO > a.cosO;  // std::minmax by larger cosine first
    const Cone& smaller = bFirst ? b : a;
    const Cone& larger = bFirst ? a : b;
    const float largerO = larger.thetaO(), smallerO = smaller.thetaO();
    const bool ts = a.twoSided || b.twoSided;
    const float thetaD = dwAcos(std::min(std::max(dot(larger.axis, smaller.axis), -1.f), 1.f));
    const float thetaE = std::max(larger.thetaE(), smaller.thetaE());
    if (std::min(thetaD + smallerO, PiF) <= largerO) return Cone(larger.axis, larger.cosO, std::cos(thetaE), ts);
    const float thetaO = (largerO + thetaD + smallerO) * 0.5f;
    if (thetaO >= PiF) return Cone(larger.axis, -1, std::cos(thetaE), ts);
    const float thetaR = thetaO - largerO;
    V3 rot = surface::cross(larger.axis, smaller.axis);
    const float rotLength = std::sqrt(lengthSq(rot));
    if (rotLength < EpsF) return Cone(larger.axis, std::cos(thetaO), std::cos(thetaE), ts);
    rot = mul(rot, 1.0f / rotLength);
    V3 axis = add(mul(larger.axis, std::cos(thetaR)), mul(surface::cross(rot, larger.axis), std::sin(thetaR)));
    axis = mul(axis, 1.0f / std::sqrt(lengthSq(axis)));
    return Cone(axis, std::cos(thetaO), std::cos(thetaE), ts);
}

// What the tree reads of a light (Light::getRadiance, getBounds, getPosition, getDirection, getThetaO, getThetaE).
struct Item {
    int index;  // among the plan's lights
    float energy;
    Box bounds;
    V3 position;
    Cone cone;
};
inline Item item(const Light& l, int index) {
    Item it;
    it.index = index;
    it.energy = 0.299f * l.radiance.x + 0.587f * l.radiance.y + 0.114f * l.radiance.z;
    it.position = l.position;
    V3 half{0, 0, 0};
    const V3 x = l.local2Render[0], y = l.local2Render[1], z = l.local2Render[2];
    auto sqrtv = [](V3 v) { return V3{std::sqrt(v.x), std::sqrt(v.y), std::sqrt(v.z)}; };
    auto absv = [](V3 v) { return V3{std::fabs(v.x), std::fabs(v.y), std::fabs(v.z)}; };
    auto maxEps = [](V3 v) { return V3{std::max(v.x, EpsF), std::max(v.y, EpsF), std::max(v.z, EpsF)}; };
    float thetaO = 0, thetaE = HalfPiF;
    switch (l.type) {
    case Portal:
    case Rect:
        half = maxEps(add(mul(absv(x), l.halfWidth), mul(absv(y), l.halfHeight)));
        thetaO = PiF * 0.5f * l.spread;
        break;
    case Disk:
        half = maxEps(sqrtv(add(times(x, x), times(y, y))));
        thetaO = PiF * 0.5f * l.spread;
        break;
    case Sphere:
        half = {l.radius, l.radius, l.radius};
        thetaO = PiF;
        break;
    case Spot: {
        const float rcpAspect = l.lensRadiusY / l.lensRadius;
        const V3 yr = mul(y, rcpAspect);
        half = maxEps(mul(sqrtv(add(times(x, x), times(yr, yr))), l.lensRadius));
        thetaO = 0.f;
        thetaE = std::atan(std::max(rcpAspect, 1.f) * (l.focalRadius + l.lensRadius) / l.focalDistance);
        break;
    }
    case Cylinder:
        half = add(mul(sqrtv(add(times(x, x), times(z, z))), l.localRadius), mul(absv(y), l.localHalfHeight));
        thetaO = PiF;
        break;
    default: break;
    }
    it.bounds.lower = sub(l.position, half);
    it.bounds.upper = add(l.position, half);
    // LightTreeCone(const Light*): its sine from the angle, not from the cosine.
    it.cone.axis = l.direction;
    it.cone.cosO = std::min(std::max(std::cos(thetaO), -1.f), 1.f);
    it.cone.sinO = std::min(std::max(std::sin(thetaO), -1.f), 1.f);
    it.cone.cosE = std::min(std::max(std::cos(thetaE), -1.f), 1.f);
    it.cone.twoSided = l.sidedness == TwoSided;
    return it;
}

struct Node {
    U32 begin = 0, count = 0, right = 0;
    Box box;
    Cone cone;
    float energy = 0, variance = 0, mean = 0;
};
struct Bucket {
    float energy = 0;
    Box box;
    Cone cone;
    U32 count = 0;
    void add(const Item& it) {
        energy += it.energy;
        box.extend(it.bounds);
        cone = combine(it.cone, cone);
        ++count;
    }
};
inline float area(const Box& b) {
    const V3 d = b.size();
    return 2 * d.x * d.y + 2 * d.y * d.z + 2 * d.x * d.z;
}
inline float orientation(const Cone& c) {
    if (c.empty()) return 4.0f * PiF;
    const float o = c.thetaO(), e = c.thetaE();
    const float w = std::min(o + e, PiF);
    return 2.f * PiF * (1.f - c.cosO) + 0.5f * PiF * ((2.0f * w * c.sinO) - std::cos(o - 2.0f * w) - (2.0f * o * c.sinO) + c.cosO);
}
struct Split {
    int axis = 0;
    float value = 0.f;
    float leftEnergy = 0, rightEnergy = 0;
    Box leftBox, rightBox;
    Cone leftCone, rightCone;
    bool onLeft(const Item& it) const { return at(it.position, axis) <= value; }
    float cost(const Box& parentBox, const Cone& parentCone) const {
        const V3 ps = parentBox.size();
        const float kr = at(ps, maxDim(ps)) / std::max(at(ps, axis), EpsF);
        const float numL = leftEnergy * area(leftBox) * orientation(leftCone);
        const float numR = rightEnergy * area(rightBox) * orientation(rightCone);
        return kr * ((numL + numR) / (area(parentBox) * orientation(parentCone)));
    }
};

struct Builder {
    std::vector<Item>& items;
    std::vector<U32> order;  // the items' order (mLightIndices)
    std::vector<Node> nodes;
    const Item& itemAt(const Node& n, U32 k) const { return items[order[n.begin + k]]; }
    void variance(Node& n) {
        n.mean = n.energy / float(n.count);
        for (U32 k = 0; k < n.count; ++k) {
            float d = itemAt(n, k).energy - n.mean;
            d *= d;
            n.variance += d;
        }
        n.variance /= float(n.count);
        const float arg = 1.f + std::sqrt(n.variance), arg2 = arg * arg;
        n.variance = 1.0f - (0.5f / (arg2 * arg2));
    }
    Node make(U32 begin, U32 count) {
        Node n;
        n.begin = begin;
        n.count = count;
        for (U32 k = 0; k < count; ++k) {
            const Item& it = itemAt(n, k);
            n.energy += it.energy;
            n.box.extend(it.bounds);
            n.cone = combine(n.cone, it.cone);
        }
        variance(n);
        return n;
    }
    Node make(U32 begin, U32 count, float energy, const Cone& cone, const Box& box) {
        Node n;
        n.begin = begin;
        n.count = count;
        n.energy = energy;
        n.cone = cone;
        n.box = box;
        variance(n);
        return n;
    }
    float splitAxis(Split& best, int axis, const Node& node, float minBound, float range) {
        constexpr int Buckets = 12, Splits = Buckets - 1;
        const float bucketSize = range / Buckets;
        Bucket buckets[Buckets];
        Split splits[Splits];
        for (int i = 0; i < Splits; ++i) {
            splits[i].axis = axis;
            splits[i].value = minBound + bucketSize * float(i + 1);
        }
        for (U32 k = 0; k < node.count; ++k) {
            const Item& it = itemAt(node, k);
            int b = 0;
            for (int j = 0; j < Splits; ++j) {
                if (splits[j].onLeft(it)) {
                    b = j;
                    break;
                }
                b = j + 1;
            }
            buckets[b].add(it);
        }
        // purgeEmptyBuckets
        Bucket fb[Buckets];
        Split fs[Splits];
        int newCount = 0;
        for (int i = 0; i < Buckets; ++i) {
            if (buckets[i].count != 0) {
                fb[newCount] = buckets[i];
                if (i < Splits) {
                    if (i == Splits - 1 && buckets[i + 1].count == 0) break;
                    fs[newCount] = splits[i];
                }
                ++newCount;
            }
        }
        const int splitCount = newCount - 1;
        for (int i = 0; i < splitCount; ++i) {
            if (i == 0) {
                fs[0].leftEnergy = fb[0].energy;
                fs[0].leftBox = fb[0].box;
                fs[0].leftCone = fb[0].cone;
            } else {
                fs[i].leftEnergy = fs[i - 1].leftEnergy + fb[i].energy;
                fs[i].leftBox = fs[i - 1].leftBox;
                fs[i].leftBox.extend(fb[i].box);
                fs[i].leftCone = combine(fs[i - 1].leftCone, fb[i].cone);
            }
        }
        for (int i = splitCount - 1; i >= 0; --i) {
            if (i == splitCount - 1) {
                fs[i].rightEnergy = fb[i + 1].energy;
                fs[i].rightBox = fb[i + 1].box;
                fs[i].rightCone = fb[i + 1].cone;
            } else {
                fs[i].rightEnergy = fs[i + 1].rightEnergy + fb[i + 1].energy;
                fs[i].rightBox = fs[i + 1].rightBox;
                fs[i].rightBox.extend(fb[i + 1].box);
                fs[i].rightCone = combine(fs[i + 1].rightCone, fb[i + 1].cone);
            }
        }
        // getCheapestSplit
        float minCost = std::numeric_limits<float>::max();
        for (int i = 0; i < splitCount; ++i) {
            if (fb[i].count == 0 || fb[i + 1].count == 0) continue;
            const float c = fs[i].cost(node.box, node.cone);
            if (i == 0 || c < minCost) {
                minCost = c;
                best = fs[i];
            }
        }
        return minCost;
    }
    void split(U32 index, Node& left, Node& right) {
        const Node node = nodes[index];
        if (node.count == 2) {
            left = make(node.begin, 1);
            right = make(node.begin + 1, 1);
            return;
        }
        // computeLightDistribution
        const V3 first = itemAt(node, 0).position;
        V3 lo = first, hi = first;
        bool coincident = true;
        for (U32 k = 0; k < node.count; ++k) {
            const V3 p = itemAt(node, k).position;
            auto equal = [](float a, float b) { return std::fabs(a - b) <= std::max(std::fabs(a), 1.0f) * EpsF; };
            if (!(equal(p.x, first.x) && equal(p.y, first.y) && equal(p.z, first.z))) coincident = false;
            lo = {std::min(lo.x, p.x), std::min(lo.y, p.y), std::min(lo.z, p.z)};
            hi = {std::max(hi.x, p.x), std::max(hi.y, p.y), std::max(hi.z, p.z)};
        }
        const V3 range = sub(hi, lo);
        U32 leftCount = node.count / 2;
        if (!coincident) {
            float minCost = -1.f;
            Split best;
            for (int axis = 0; axis < 3; ++axis) {
                Split s;
                const float c = splitAxis(s, axis, node, at(lo, axis), at(range, axis));
                if (axis == 0 || c < minCost) {
                    minCost = c;
                    best = s;
                }
            }
            // performSplit: the lights partitioned about the split, each side with the split's energy, cone and bounds.
            const auto mid = std::partition(order.begin() + node.begin, order.begin() + node.begin + node.count,
                                            [&](U32 i) { return best.onLeft(items[i]); });
            leftCount = U32(mid - (order.begin() + node.begin));
            // A split with an empty side (none in MoonRay's scenes): split evenly instead.
            if (leftCount != 0 && leftCount != node.count) {
                left = make(node.begin, leftCount, best.leftEnergy, best.leftCone, best.leftBox);
                right = make(node.begin + leftCount, node.count - leftCount, best.rightEnergy, best.rightCone, best.rightBox);
                return;
            }
            leftCount = node.count / 2;
        }
        // splitLightsEvenly
        left = make(node.begin, leftCount);
        right = make(node.begin + leftCount, node.count - leftCount);
    }
    void build(U32 index) {
        if (nodes[index].count <= 1) return;
        Node left, right;
        split(index, left, right);
        nodes.push_back(left);
        build(U32(nodes.size() - 1));
        nodes.push_back(right);
        nodes[index].right = U32(nodes.size() - 1);
        build(U32(nodes.size() - 1));
    }
};
}  // namespace treebuild

// LightTree::build over a light set's bounded lights (indices into lights; mesh lights are left out), appended to
// out. Returns the root's index, or -1 when the set has no such light.
inline int buildLightTree(const std::vector<Light>& lights, const std::vector<U32>& set, std::vector<TreeNode>& out) {
    using namespace treebuild;
    std::vector<Item> items;
    for (U32 i : set) {
        const Light& l = lights[i];
        if (inTree(l)) items.push_back(item(l, int(i)));
    }
    if (items.empty()) return -1;
    Builder b{items, {}, {}};
    for (U32 k = 0; k < items.size(); ++k) b.order.push_back(k);
    b.nodes.push_back(b.make(0, U32(items.size())));
    b.build(0);
    const int root = int(out.size());
    for (const Node& n : b.nodes) {
        TreeNode t{};
        t.lower = n.box.lower;
        t.upper = n.box.upper;
        t.axis = n.cone.axis;
        t.cosThetaO = n.cone.cosO;
        t.sinThetaO = n.cone.sinO;
        t.cosThetaE = n.cone.cosE;
        t.twoSided = n.cone.twoSided ? 1u : 0u;
        t.energy = n.energy;
        t.energyVariance = n.variance;
        t.lightCount = n.count;
        t.right = n.count > 1 ? n.right + U32(root) : 0u;
        t.light = n.count == 1 ? items[b.order[n.begin]].index : -1;
        out.push_back(t);
    }
    return root;
}

}  // namespace xpu2::interactive::lights
