"""A toon material's lit band follows its smooth shading normals, not the flat faces of the mesh under them (issue 129).

MoonRay cuts the light of a smooth-shaded mesh along its faces in two ways. It drops the light from behind a face's
geometric normal before a material sees it (light culling), and fades the rest by that normal (every shadow terminator
fix mode). And its shadow rays start on the flat face, so near the terminator they hit the neighbouring faces. A plain
diffuse is nearly black there and hides both; a toon ramp is lit to its edge, and its edge comes out in steps, one per
face, finer under subdivision but still there.

Only when MoonRay is started with MOONRAY_MODO_TOON_TERMINATOR=1 (the plugin's preference), and only for DwaToonMaterial:

1. The toon diffuse lobe is "spherical", as the material's own prevent_light_culling makes it, so light is not culled by
   the geometric normal; the lobe cuts light off itself where its shading normal turns from the light, and is not
   faded by the geometric normal. Scalar (C++) and vector (ISPC).
2. At a hit on a toon material, the triangle, quad and subdivision meshes record how far the smooth surface the vertex
   normals describe lies above the flat face there (Hanika, "Hacking the Shadow Terminator", Ray Tracing Gems II, 2021):
   the hit moved up to the tangent planes at the triangle's corners, weighted by its barycentric coordinates. Shadow
   rays toward a light near the terminator start from there, fully when the light is at or behind the face, fading out
   by the time it is 0.1 (in cosine) above it. Other materials record nothing, and their shadow rays are MoonRay's.
   Instanced copies are left as MoonRay has them.

Without the variable, MoonRay renders exactly as its source does.

And, only with MOONRAY_MODO_TOON_ALBEDO=1 (a preference of its own): the "albedo" material AOV, which the denoisers take
as their albedo guide, gives a toon diffuse lobe its own albedo. MoonRay's averages f / pdf over the lobe's samples,
which is the albedo for a lobe with the cosine in f, but the toon lobe is flat (no cosine) and sampled by the cosine,
so each sample is albedo / (2 cos) and the AOV is full of fireflies far above 1: the denoiser takes them for detail and
leaves the toon surface as noisy as it was (Aov.cc and Aov.ispc, computeAlbedo)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering'

HEADER = 'shading/ModoToonTerminator.h'
HEADER_TEXT = '''// Modo: toon materials lit by their smooth shading normals, not by the faces under them (tools/port_toon_terminator.py).
#pragma once

#include <cstdlib>

namespace moonray {
namespace shading {

/// True when MoonRay was started with MOONRAY_MODO_TOON_TERMINATOR=1. Read once.
inline bool modoToonTerminator()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_TOON_TERMINATOR");
        return value && value[0] == '1';
    }();
    return on;
}

/// True when MoonRay was started with MOONRAY_MODO_TOON_ALBEDO=1: the albedo AOV gives a toon diffuse lobe its own
/// albedo, a clean guide for the denoisers. Read once.
inline bool modoToonAlbedo()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_TOON_ALBEDO");
        return value && value[0] == '1';
    }();
    return on;
}

} // namespace shading
} // namespace moonray
'''

LIFT = ('    // Modo: shadow rays of a toon material start from the smooth surface (shading/ModoToonTerminator.h).\n'
        '    if (shading::modoToonTerminator() && !ray.isInstanceHit()) {\n')

EDITS = {
    'shading/ispc/Intersection.hh': [
        ("    HVD_MEMBER(uint32_t, mIdHi);                                            \\\n"
         "    HVD_ISPC_PAD(mPad2, 44)\n",
         "    HVD_MEMBER(uint32_t, mIdHi);                                            \\\n"
         "    /* Modo: where a toon material's shadow rays start, from the hit */     \\\n"
         "    HVD_MEMBER(HVD_NAMESPACE(scene_rdl2::math, Vec3f), mModoSmoothOffset);  \\\n"
         "    HVD_ISPC_PAD(mPad2, 32)\n"),
        ("    HVD_VALIDATE(Intersection, mIdHi);                                      \\\n",
         "    HVD_VALIDATE(Intersection, mIdHi);                                      \\\n"
         "    HVD_VALIDATE(Intersection, mModoSmoothOffset);                          \\\n"),
    ],
    'shading/Intersection.h': [
        ("#include <moonray/rendering/shading/MipSelector.h>\n",
         "#include <moonray/rendering/shading/MipSelector.h>\n"
         "#include <moonray/rendering/shading/ModoToonTerminator.h>\n"),
        ("#include <scene_rdl2/scene/rdl2/Material.h>\n",
         "#include <scene_rdl2/scene/rdl2/Material.h>\n"
         "#include <scene_rdl2/scene/rdl2/SceneClass.h>\n"),
        ("    // Set shadow epsilon hint\n    finline void setShadowEpsilonHint(float value) {\n        mShadowEpsilonHint = value;\n    }\n",
         "    // Set shadow epsilon hint\n    finline void setShadowEpsilonHint(float value) {\n        mShadowEpsilonHint = value;\n    }\n\n"
         "    // Modo: on a toon material, how far the smooth surface the corner normals describe lies above the flat\n"
         "    // face at P: P moved up to the tangent planes at the corners, weighted by its barycentric coordinates\n"
         "    // (Hanika, \"Hacking the Shadow Terminator\", 2021). Shadow rays near the terminator start there.\n"
         "    void setModoSmoothOffset(const scene_rdl2::math::Vec3f &P,\n"
         "                             const scene_rdl2::math::Vec3f &p1, const scene_rdl2::math::Vec3f &p2,\n"
         "                             const scene_rdl2::math::Vec3f &p3, const scene_rdl2::math::Vec3f &n1,\n"
         "                             const scene_rdl2::math::Vec3f &n2, const scene_rdl2::math::Vec3f &n3,\n"
         "                             float w1, float w2, float w3)\n"
         "    {\n"
         "        if (!mMaterial || mMaterial->getSceneClass().getName() != \"DwaToonMaterial\") return;\n"
         "        scene_rdl2::math::Vec3f offset(0.0f);\n"
         "        const auto lift = [&](const scene_rdl2::math::Vec3f &corner, const scene_rdl2::math::Vec3f &n, float weight) {\n"
         "            const scene_rdl2::math::Vec3f unit = scene_rdl2::math::normalize(n);\n"
         "            const float below = scene_rdl2::math::dot(P - corner, unit);\n"
         "            if (below < 0.0f) offset = offset - (weight * below) * unit;\n"
         "        };\n"
         "        lift(p1, n1, w1); lift(p2, n2, w2); lift(p3, n3, w3);\n"
         "        if (scene_rdl2::math::isFinite(offset)) mModoSmoothOffset = offset;\n"
         "    }\n"
         "    finline const scene_rdl2::math::Vec3f &getModoSmoothOffset() const { return mModoSmoothOffset; }\n"),
    ],
    'shading/ispc/State.isph': [
        ("    uIntersection.mWo.z = extract(vState.mWo.z, lane);\n",
         "    uIntersection.mWo.z = extract(vState.mWo.z, lane);\n\n"
         "    uIntersection.mModoSmoothOffset.x = extract(vState.mModoSmoothOffset.x, lane);\n"
         "    uIntersection.mModoSmoothOffset.y = extract(vState.mModoSmoothOffset.y, lane);\n"
         "    uIntersection.mModoSmoothOffset.z = extract(vState.mModoSmoothOffset.z, lane);\n"),
    ],
    'geom/prim/QuadMesh.cc': [
        ("    intersection.setDifferentialGeometry(Ng,\n",
         LIFT +
         "        Vec3f n1, n2, n3;\n"
         "        getQuadNormal(baseFaceId, tessFaceId, n1, n2, n3, ray.time, isFirst);\n"
         "        const auto at = [&](uint32_t id) {\n"
         "            return isMotionBlurOn() ? Vec3f(lerp(Vec3f(mVertices(id, 0)), Vec3f(mVertices(id, 1)), ray.time))\n"
         "                                    : Vec3f(mVertices(id));\n"
         "        };\n"
         "        intersection.setModoSmoothOffset(intersection.getP(), at(isecId1), at(isecId2), at(isecId3),\n"
         "                                         n1, n2, n3, w, u, v);\n"
         "    }\n\n"
         "    intersection.setDifferentialGeometry(Ng,\n"),
    ],
    'geom/prim/TriMesh.cc': [
        ("    intersection.setDifferentialGeometry(Ng,\n",
         LIFT +
         "        Vec3f n1, n2, n3;\n"
         "        getTriangleNormal(baseFaceId, tessFaceId, n1, n2, n3, ray.time, isFirst);\n"
         "        const auto at = [&](uint32_t id) {\n"
         "            return isMotionBlurOn() ? Vec3f(lerp(Vec3f(mVertices(id, 0)), Vec3f(mVertices(id, 1)), ray.time))\n"
         "                                    : Vec3f(mVertices(id));\n"
         "        };\n"
         "        intersection.setModoSmoothOffset(intersection.getP(), at(isecId1), at(isecId2), at(isecId3),\n"
         "                                         n1, n2, n3, w, u, v);\n"
         "    }\n\n"
         "    intersection.setDifferentialGeometry(Ng,\n"),
    ],
    'geom/prim/OpenSubdivMesh.cc': [
        ("    intersection.setDifferentialGeometry(Ng,\n",
         LIFT +
         "        intersection.setModoSmoothOffset(intersection.getP(),\n"
         "            Vec3f(mTessellatedVertices(isecId1)), Vec3f(mTessellatedVertices(isecId2)), Vec3f(mTessellatedVertices(isecId3)),\n"
         "            mSurfaceNormal(isecId1), mSurfaceNormal(isecId2), mSurfaceNormal(isecId3), w, u, v);\n"
         "    }\n\n"
         "    intersection.setDifferentialGeometry(Ng,\n"),
    ],
    'pbr/integrator/PathIntegratorMultiSampler.cc': [
        ("finline void\nPathIntegrator::addDirectVisibleBsdfLobeSampleContribution(",
         "// Modo: a toon material's shadow ray toward a light near the terminator starts from the smooth surface, not the\n"
         "// flat face, whose neighbours would otherwise shadow it (shading/ModoToonTerminator.h). Fully when the light is at\n"
         "// or behind the face, fading out by the time it is 0.1 (in cosine) above it.\n"
         "static finline scene_rdl2::math::Vec3f\n"
         "modoShadowOrigin(const shading::Intersection &isect, const scene_rdl2::math::Vec3f &P, const scene_rdl2::math::Vec3f &wi)\n"
         "{\n"
         "    const scene_rdl2::math::Vec3f &offset = isect.getModoSmoothOffset();\n"
         "    const scene_rdl2::math::Vec3f &N = isect.getN();\n"
         "    if (scene_rdl2::math::dot(offset, offset) == 0.0f || scene_rdl2::math::dot(N, wi) <= 0.0f ||\n"
         "        scene_rdl2::math::dot(offset, N) < 0.0f) return P;\n"
         "    scene_rdl2::math::Vec3f Ng = isect.getNg();\n"
         "    if (scene_rdl2::math::dot(N, Ng) < 0.0f) Ng = -Ng;\n"
         "    const float amount = scene_rdl2::math::clamp(1.0f - scene_rdl2::math::dot(Ng, wi) / 0.1f, 0.0f, 1.0f);\n"
         "    return P + offset * amount;\n"
         "}\n\n"
         "finline void\nPathIntegrator::addDirectVisibleBsdfLobeSampleContribution("),
        ("    const scene_rdl2::math::Vec3f& P = parentRay.getOrigin();\n    float tfar = bsmp.distance * sHitEpsilonEnd;\n",
         "    const scene_rdl2::math::Vec3f P = modoShadowOrigin(isect, parentRay.getOrigin(), bsmp.wi);\n"
         "    float tfar = bsmp.distance * sHitEpsilonEnd;\n"),
        ("        const scene_rdl2::math::Vec3f &P = parentRay.getOrigin();\n        float tfar = lsmp[i].distance * sHitEpsilonEnd;\n",
         "        const scene_rdl2::math::Vec3f P = modoShadowOrigin(isect, parentRay.getOrigin(), lsmp[i].wi);\n"
         "        float tfar = lsmp[i].distance * sHitEpsilonEnd;\n"),
    ],
    'pbr/integrator/PathIntegratorMultiSampler.ispc': [
        ("// fill out occlusion or presence shadow ray based on light attribute\n",
         "// Modo: a toon material's shadow ray toward a light near the terminator starts from the smooth surface, not the\n"
         "// flat face (as modoShadowOrigin in PathIntegratorMultiSampler.cc).\n"
         "inline varying Vec3f\n"
         "modoShadowOrigin(const varying Intersection &isect, const varying Vec3f &P, const varying Vec3f &wi)\n"
         "{\n"
         "    const varying Vec3f offset = isect.mModoSmoothOffset;\n"
         "    const varying Vec3f N = isect.mN;\n"
         "    varying Vec3f Ng = isect.mNg;\n"
         "    if (dot(offset, offset) == 0.0f || dot(N, wi) <= 0.0f || dot(offset, N) < 0.0f) {\n"
         "        return P;\n"
         "    }\n"
         "    if (dot(N, Ng) < 0.0f) {\n"
         "        Ng = Ng * -1.0f;\n"
         "    }\n"
         "    const varying float amount = clamp(1.0f - dot(Ng, wi) / 0.1f, 0.0f, 1.0f);\n"
         "    return P + offset * amount;\n"
         "}\n\n"
         "// fill out occlusion or presence shadow ray based on light attribute\n"),
        ("    int32_t assignmentId = isect.mLayerAssignmentId;\n\n    // pass in light for shadow linking purpose\n",
         "    int32_t assignmentId = isect.mLayerAssignmentId;\n\n"
         "    // Modo: the shadow ray's start, moved up to the smooth surface for a toon material.\n"
         "    varying RayDifferential shadowParent = parentRay;\n"
         "    shadowParent.org = modoShadowOrigin(isect, parentRay.org, wi);\n\n"
         "    // pass in light for shadow linking purpose\n"),
        ("            &dstPresenceShadowsRayIndices[numPresenceShadowsRays],\n            srcRayIndices,\n            parentRay, wi,\n",
         "            &dstPresenceShadowsRayIndices[numPresenceShadowsRays],\n            srcRayIndices,\n            shadowParent, wi,\n"),
        ("            &dstOcclRayIndices[numOcclRays],\n            srcRayIndices,\n            parentRay, wi,\n",
         "            &dstOcclRayIndices[numOcclRays],\n            srcRayIndices,\n            shadowParent, wi,\n"),
    ],
    'shading/BsdfBuilder.cc': [
        ('#include "bsdf/npr/BsdfToon.h"\n',
         '#include "bsdf/npr/BsdfToon.h"\n#include "ModoToonTerminator.h"\n'),
        ("            component.getExtendRamp());\n\n        if (mPreventLightCulling) {\n",
         "            component.getExtendRamp());\n\n"
         "        // Modo: under MOONRAY_MODO_TOON_TERMINATOR, as if prevent_light_culling were on (ModoToonTerminator.h).\n"
         "        if (mPreventLightCulling || modoToonTerminator()) {\n"),
    ],
    'shading/ispc/BsdfBuilder.ispc': [
        ("                      brdf.mExtendRamp);\n\n    if (me.mPreventLightCulling) {\n",
         "                      brdf.mExtendRamp);\n\n"
         "    // Modo: under MOONRAY_MODO_TOON_TERMINATOR, as if prevent_light_culling were on (ModoToonTerminator.h).\n"
         "    if (me.mPreventLightCulling || gModoToonTerminator) {\n"),
    ],
    'shading/ispc/bsdf/npr/BsdfToon.isph': [
        ("#include <moonray/rendering/shading/ispc/bsdf/hair/BsdfHairLobes.isph>\n",
         "#include <moonray/rendering/shading/ispc/bsdf/hair/BsdfHairLobes.isph>\n\n"
         "// Modo: set once from C++ (BsdfToon.cc) to MOONRAY_MODO_TOON_TERMINATOR (ModoToonTerminator.h).\n"
         "extern uniform bool gModoToonTerminator;\n"),
    ],
    'shading/bsdf/npr/BsdfToon.cc': [
        ("#include <moonray/rendering/shading/Util.h>\n",
         "#include <moonray/rendering/shading/Util.h>\n"
         "#include <moonray/rendering/shading/ModoToonTerminator.h>\n"
         "#include <moonray/rendering/shading/ispc/bsdf/npr/BsdfToon_ispc_stubs.h>\n"),
        ("scene_rdl2::math::Color\nToonBsdfLobe::eval(const BsdfSlice &slice,\n",
         "// Modo: the vector code is told once, as the library loads.\n"
         "namespace {\n"
         "const bool sModoToonTerminatorSet = (ispc::BsdfToon_setModoToonTerminator(modoToonTerminator()), true);\n"
         "}\n\n"
         "scene_rdl2::math::Color\nToonBsdfLobe::eval(const BsdfSlice &slice,\n"),
        ("    // Soften hard shadow terminator due to shading normals\n    const float Gs = slice.computeShadowTerminatorFix(N, wi);\n",
         "    // Soften hard shadow terminator due to shading normals\n"
         "    // Modo: under MOONRAY_MODO_TOON_TERMINATOR, cut off by the shading normal alone, not faded by the faces'.\n"
         "    const float Gs = modoToonTerminator() ? (cosThetaWi > 0.0f ? 1.0f : 0.0f)\n"
         "                                          : slice.computeShadowTerminatorFix(N, wi);\n"),
    ],
    'pbr/core/Aov.cc': [
        ("#include <moonray/rendering/shading/bsdf/BsdfSlice.h>\n",
         "#include <moonray/rendering/shading/bsdf/BsdfSlice.h>\n"
         "#include <moonray/rendering/shading/bsdf/npr/BsdfToon.h>\n"
         "#include <moonray/rendering/shading/ModoToonTerminator.h>\n"),
        ("static void\ncomputeAlbedo(const MaterialAovs::ComputeParams &p, float *dest)\n",
         "// Modo: the vector code is told once, as the library loads.\n"
         "namespace {\n"
         "const bool sModoToonAlbedoSet = (ispc::Aov_setModoToonAlbedo(shading::modoToonAlbedo()), true);\n"
         "}\n\n"
         "static void\ncomputeAlbedo(const MaterialAovs::ComputeParams &p, float *dest)\n"),
        ("                        ++numContributions;\n"
         "                        for (int i = 0; i < ni; ++i) {\n"
         "                            const BsdfSample &bsmp = p.mBsmps[s + i];\n",
         "                        ++numContributions;\n"
         "                        // Modo: under MOONRAY_MODO_TOON_ALBEDO, a toon diffuse lobe's own albedo. Its samples are\n"
         "                        // albedo / (2 cos): the lobe is flat and sampled by the cosine (ModoToonTerminator.h).\n"
         "                        if (shading::modoToonAlbedo() && dynamic_cast<const shading::ToonBsdfLobe *>(lobe)) {\n"
         "                            result += lobe->albedo(p.mBSampler->getBsdfSlice());\n"
         "                        } else\n"
         "                        for (int i = 0; i < ni; ++i) {\n"
         "                            const BsdfSample &bsmp = p.mBsmps[s + i];\n"),
    ],
    'pbr/core/Aov.ispc': [
        ("#include <moonray/rendering/shading/ispc/bssrdf/Bssrdf.isph>\n",
         "#include <moonray/rendering/shading/ispc/bssrdf/Bssrdf.isph>\n\n"
         "// Modo: MOONRAY_MODO_TOON_ALBEDO, set once from C++ (Aov.cc).\n"
         "uniform bool gModoToonAlbedo = false;\n\n"
         "export void\nAov_setModoToonAlbedo(uniform bool on)\n{\n    gModoToonAlbedo = on;\n}\n"),
        ("                        ++numContributions;\n"
         "                        uniform int s = bSampler->mLobeToSampleIndex[lobeIdx];\n"
         "                        for (int i = 0; i < lobeSampleCount; ++i, ++s) {\n"
         "                            const varying BsdfSample &bsmp = bsmps[s];\n"
         "                            if (BsdfSample_isValid(&bsmp)) {\n"
         "                                MNRY_ASSERT(!isSampleInvalid(bsmp.f, bsmp.pdf));\n"
         "                                result = result + bsmp.f * (1.0f / (floatLobeSampleCount * bsmp.pdf));\n"
         "                            }\n"
         "                        }\n",
         "                        ++numContributions;\n"
         "                        // Modo: under MOONRAY_MODO_TOON_ALBEDO, a toon diffuse lobe's own albedo (as in Aov.cc).\n"
         "                        if (gModoToonAlbedo && lobe->mName == BSDF_LOBE_TOON) {\n"
         "                            result = result + BsdfLobe_albedo(lobe, *bSampler->mSlice);\n"
         "                        } else {\n"
         "                        uniform int s = bSampler->mLobeToSampleIndex[lobeIdx];\n"
         "                        for (int i = 0; i < lobeSampleCount; ++i, ++s) {\n"
         "                            const varying BsdfSample &bsmp = bsmps[s];\n"
         "                            if (BsdfSample_isValid(&bsmp)) {\n"
         "                                MNRY_ASSERT(!isSampleInvalid(bsmp.f, bsmp.pdf));\n"
         "                                result = result + bsmp.f * (1.0f / (floatLobeSampleCount * bsmp.pdf));\n"
         "                            }\n"
         "                        }\n"
         "                        }\n"),
    ],
    'shading/ispc/bsdf/npr/BsdfToon.ispc': [
        ("varying Color\nToonBsdfLobe_eval(",
         "// Modo: MOONRAY_MODO_TOON_TERMINATOR, set once from C++ (BsdfToon.cc).\n"
         "uniform bool gModoToonTerminator = false;\n\n"
         "export void\nBsdfToon_setModoToonTerminator(uniform bool on)\n{\n    gModoToonTerminator = on;\n}\n\n"
         "varying Color\nToonBsdfLobe_eval("),
        ("    // Soften hard shadow terminator due to shading normals\n    const float Gs = BsdfSlice_computeShadowTerminatorFix(&slice, N, wi);\n",
         "    // Soften hard shadow terminator due to shading normals\n"
         "    // Modo: under MOONRAY_MODO_TOON_TERMINATOR, cut off by the shading normal alone, not faded by the faces'.\n"
         "    const float Gs = gModoToonTerminator ? (cosThetaWi > 0.0f ? 1.0f : 0.0f)\n"
         "                                         : BsdfSlice_computeShadowTerminatorFix(&slice, N, wi);\n"),
    ],
}


def patch_text(name, text):
    """Each edit is matched as the file has it, with LF or CRLF line ends (some files mix them)."""
    for old, new in EDITS[name]:
        for ending in ('\n', '\r\n'):
            o, n = old.replace('\n', ending), new.replace('\n', ending)
            if n in text:
                break
            if text.count(o) == 1:
                text = text.replace(o, n, 1)
                break
        else:
            raise RuntimeError('Toon terminator anchor missing or ambiguous in %s: %r' % (name, old[:70]))
    return text


def main():
    header = RENDERING / HEADER
    if not header.exists() or header.read_text(encoding='utf-8') != HEADER_TEXT:
        header.write_text(HEADER_TEXT, encoding='utf-8')
        print('wrote', HEADER)
    for name in EDITS:
        source = RENDERING / name
        text = source.read_bytes().decode('utf-8')
        patched = patch_text(name, text)
        if patched != text:
            source.write_bytes(patched.encode('utf-8'))
            print('patched', name)
        else:
            print('already in', name)


if __name__ == '__main__':
    main()
