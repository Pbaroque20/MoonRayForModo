// MoonRay's adaptive light sampling (light_sampling_mode 1): a tree over each light set's bounded lights (mesh lights
// aside), which picks the lights a shading point samples by importance and adaptive tree splitting (Estevez and
// Kulla 2018), each with the probability it was picked. Shared by the CPU and CUDA lanes; built by light_tree_build.h.
//
// Adapted from MoonRay pbr/light/LightTree.ispc and LightTreeUtil.ispc (the vector renderer's), Apache-2.0,
// copyright 2024 DreamWorks Animation LLC; see MOONRAY_LICENSE.txt.
#pragma once
#include "light_core.h"

namespace xpu2::interactive::lights {

// A LightTreeNode: its bounds, orientation cone and energy; a leaf's light (its index among the lights), else -1.
// A node's left child is the next node.
struct TreeNode {
    V3 lower, upper;
    V3 axis;
    float cosThetaO, sinThetaO, cosThetaE;
    float energy, energyVariance;  // energyVariance as LightTreeNode::calcEnergyVariance leaves it
    U32 lightCount, right, twoSided;
    int light;
};

// The lights a tree holds: the bounded ones but mesh lights (getThetaO and getThetaE not negative).
X2_HD inline bool inTree(const Light& l) {
    return l.type == Rect || l.type == Disk || l.type == Sphere || l.type == Spot || l.type == Cylinder || l.type == Portal;
}
X2_HD inline V3 treeCenter(const TreeNode& n) { return mul(add(n.lower, n.upper), 0.5f); }
// cosSubClamped: the cosine of the difference of two angles, 1 when the second is the larger.
X2_HD inline float cosSubClamped(float sinA, float cosA, float sinB, float cosB) {
    if (cosB < cosA) return 1.f;
    return cosA * cosB + sinA * sinB;
}
// LightTreeNode_importance: energy times the geometric (cone), material (shading normal) and distance terms.
X2_HD inline float treeImportance(const TreeNode& node, V3 p, V3 n, const TreeNode& sibling, bool cull) {
    if (node.lightCount == 0) return 0.f;
    const V3 center = treeCenter(node);
    const V3 bboxToPt = sub(p, center);
    const float dSqr = lengthSq(bboxToPt);
    const V3 dirToPt = mul(bboxToPt, 1.0f / sqrtf(dSqr));
    const float rSqr = lengthSq(sub(node.upper, center));
    float sinU, cosU;
    if (dSqr < rSqr) {
        cosU = -1.f;
        sinU = 0.f;
    } else {
        const float s2 = rSqr / dSqr;
        sinU = sqrtf(s2);
        cosU = sqrtf(1.f - s2);
    }
    // calcDistanceTerm: 1/d^2 (normalized by the diagonal) only when outside both nodes by their diagonals.
    const float diagLenSqr = 4.f * rSqr;
    const float diagLenSqrSibling = lengthSq(sub(sibling.upper, sibling.lower));
    const float dSqrSibling = lengthSq(sub(p, treeCenter(sibling)));
    const float distanceTerm = (dSqr > diagLenSqr && dSqrSibling > diagLenSqrSibling) ? diagLenSqr / dSqr : 1.f;
    // calcGeometricTerm
    float cosTheta = fminf(fmaxf(dot(node.axis, dirToPt), -1.f), 1.f);
    if (node.twoSided) cosTheta = fabsf(cosTheta);
    const float sinTheta = sqrtf(1.f - cosTheta * cosTheta);
    const float cosSub = cosSubClamped(sinTheta, cosTheta, node.sinThetaO, node.cosThetaO);
    const float sinSub = sqrtf(1.f - cosSub * cosSub);
    const float cosPrime = cosSubClamped(sinSub, cosSub, sinU, cosU);
    const float geometricTerm = cosPrime <= node.cosThetaE ? 0.f : cosPrime;
    // calcMaterialTerm
    const float cosI = fminf(fmaxf(-dot(n, dirToPt), -1.f), 1.f);
    const float sinI = sqrtf(1.f - cosI * cosI);
    const float cosIPrime = cosSubClamped(sinI, cosI, sinU, cosU);
    const float materialTerm = (cull && cosIPrime < 0.f) ? 0.f : fabsf(cosIPrime);
    return node.energy * geometricTerm * materialTerm * distanceTerm;
}
// splittingHeuristic (LightTree.ispc): the node's spread seen from p, biased by its energy variance.
X2_HD inline float treeSplitting(const TreeNode& node, V3 p) {
    const V3 center = treeCenter(node);
    const float radius = sqrtf(lengthSq(sub(center, node.lower)));
    const float distance = sqrtf(lengthSq(sub(p, center)));
    if (distance <= radius) return 0.f;
    const float spread = fminf(asinf(radius / distance) * 0.63661977236758134308f, 1.f);
    const float spreadSqrt = sqrtf(spread);
    const float arg = 1.f + sqrtf(node.energyVariance);
    const float mapped = 1.f - (1.f / (2.f * arg * arg * arg * arg));
    // bias_Schlick
    float bias;
    if (mapped <= 0.0f) bias = 0.0f;
    else if (mapped >= 1.0f) bias = 1.0f;
    else {
        const float bv = mapped * spreadSqrt;
        bias = bv / ((1.0f - mapped) * (1.0f - spreadSqrt) + bv);
    }
    return 1.f - bias;
}
// LightTree_sampleBranch: down from a node by importance; the leaf's light and the probability of reaching it, or -1
// at a dead branch.
X2_HD inline int treeSampleBranch(const TreeNode* nodes, U32 index, V3 p, V3 n, bool cull, float r, float& pdf) {
    for (;;) {
        const TreeNode& node = nodes[index];
        if (node.lightCount == 1) return node.light;
        const U32 iL = index + 1, iR = node.right;
        const float wL = treeImportance(nodes[iL], p, n, nodes[iR], cull);
        const float wR = treeImportance(nodes[iR], p, n, nodes[iL], cull);
        if (wL + wR == 0.f) return -1;
        const float pdfL = wL / (wL + wR);
        if (r < pdfL || pdfL == 1.f) {
            r = r / pdfL;
            pdf *= pdfL;
            index = iL;
        } else {
            const float pdfR = 1.f - pdfL;
            r = (r - pdfL) / pdfR;
            pdf *= pdfR;
            index = iR;
        }
    }
}
// LightTree_sampleRecurse: from the root, a node that splitting does not open picks one light by importance
// (a fresh random number each); one it opens hands both children on. choose(light, pdf) receives each light picked.
constexpr U32 TreeStack = 64;
template <class Random, class Choose>
X2_HD inline void treeSample(const TreeNode* nodes, int root, float threshold, V3 p, V3 n, Random&& random, Choose&& choose) {
    if (root < 0) return;
    U32 stack[TreeStack];
    U32 top = 0;
    stack[top++] = U32(root);
    while (top) {
        const U32 index = stack[--top];
        const TreeNode& node = nodes[index];
        if (node.lightCount == 0) continue;
        if (node.lightCount == 1) {
            choose(node.light, 1.f);
            continue;
        }
        if (threshold == 0.0f || treeSplitting(node, p) > threshold || top + 2 > TreeStack) {
            float pdf = 1.f;
            const int light = treeSampleBranch(nodes, index, p, n, true, random(), pdf);
            if (light >= 0) choose(light, pdf);
            continue;
        }
        stack[top++] = node.right;
        stack[top++] = index + 1;
    }
}

}  // namespace xpu2::interactive::lights
