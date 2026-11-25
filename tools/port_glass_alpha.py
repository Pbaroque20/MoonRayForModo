"""Glass in alpha: what the camera sees through glass alone to the sky is see-through in the alpha.

MoonRay's alpha counts a surface the camera ray hits as opaque whatever the surface lets through: a glass ball against
the sky, its windows, a car's windscreen came out as solid as paint (a tester: "Alphas rendered even from glass
materials are completely opaque"), so a render laid over a photo showed the render's sky in every window. Presence
(cut-outs) was right; refraction was not counted at all.

Unless MoonRay is started with MOONRAY_MODO_GLASS_ALPHA=0 (the plugin's preference off; unset is on), a camera path
that has gone only through glossy or mirror transmission (glass, water, thin glass, frosted glass) and then leaves the
scene takes as much out of the pixel's alpha as it carries (its throughput, as a cut-out seen past the camera does):
- each path vertex carries modoSeeThrough (1 for a camera ray; kept by a transmission bounce, lost by any other, and
  by subsurface and volume scattering);
- vector and XPU: a ray past the camera that misses every surface while it holds it adds -throughput to the alpha
  (RayHandlers.cc, XPURayHandlers.cc);
- scalar: such a miss is counted for its camera sample (a thread-local tally) and taken off the sample's alpha
  (PathIntegrator::computeRadiance).
What is reflected stays opaque, as a light seen in glass does: the window of a car seen against the sky is as
transparent as the light through it. The sky seen through the glass stays in the picture's colour, as the sky seen
directly does; the kit's EXR step takes both out of it (environment_background, Premultiplied OpenEXR alpha).

A matte shadow catcher (tools/port_shadow_catcher.py, which runs before this) seen through glass alone is seen as the
camera sees it, not as what it wears: the background past it (modoCatcherBackground, the lights the camera sees there),
darkened by the shadows on it times its strength, times the path's throughput; and, with this switch on, see-through
in alpha as the sky through glass is but for those shadows (throughput x (1 - strength x shadow) taken off). Vector and
XPU: integrateBundled lets such a hit through to the catcher's camera code, its transparency the throughput x
(1 - strength), the unshadowed light samples taking the rest (modoCatcherShare's alpha scale, CPP_modoGlassAlpha);
scalar: computeRadianceRecurse1 does as computeRadianceRecurse0 does, and adds to the sample's modoSeenThrough. Light
path state: the transmissions, the catcher's straight event, the light (C<TS><Ts><L>, which the kit's glass sky
expression counts as Environment background)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering'

HEADER = RENDERING / 'pbr/core/ModoGlassAlpha.h'
HEADER_TEXT = '''// Modo: glass in alpha (tools/port_glass_alpha.py).
#pragma once

#include <cstdlib>

namespace moonray {
namespace pbr {

/// True unless MoonRay was started with MOONRAY_MODO_GLASS_ALPHA=0. Read once.
inline bool modoGlassAlpha()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_GLASS_ALPHA");
        return !value || value[0] != '0';
    }();
    return on;
}

/// Scalar mode: how much of a camera sample went through glass alone and out of the scene.
inline float &modoSeenThrough()
{
    thread_local float held = 0.f;
    return held;
}

} // namespace pbr
} // namespace moonray
'''

MISS_OLD = '''                if (modoFogAlpha() && rs->mRay.getDepth() == 0) {
                    alpha = rs->mPathVertex.modoFogPending;
                }
'''
MISS_NEW = '''                if (modoFogAlpha() && rs->mRay.getDepth() == 0) {
                    alpha = rs->mPathVertex.modoFogPending;
                }
                // Modo: a path seen through glass alone that leaves the scene is see-through in alpha
                // (tools/port_glass_alpha.py).
                if (modoGlassAlpha() && rs->mRay.getDepth() > 0 && rs->mPathVertex.modoSeeThrough) {
                    alpha = -reduceTransparency(rs->mPathVertex.pathThroughput);
                }
'''
HANDLER_EDITS = [
    ('''#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
''', '''#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
#include <moonray/rendering/pbr/core/ModoGlassAlpha.h>
''', 1),
    (MISS_OLD, MISS_NEW, 1),
]

# ---- A matte shadow catcher seen through glass alone (anchored on tools/port_shadow_catcher.py's code) -------------

CATCHER_DEPTH_OLD = '''            if (rayDepth > 0) {
                numRadiances += fillBundledRadiance(pbrTls,
'''
CATCHER_DEPTH_NEW = '''            // Modo: a matte seen through glass alone (a path past the camera that went only through glossy or mirror
            // transmission) is seen as from the camera, below (tools/port_glass_alpha.py).
            const varying bool modoThroughGlass = rayDepth > 0 && modoMatte && rs->mPathVertex.modoSeeThrough != 0;
            if (rayDepth > 0 && !modoThroughGlass) {
                numRadiances += fillBundledRadiance(pbrTls,
'''
CATCHER_ALPHA_OLD = '''                transparency = 1.f - modoCatcher;
                modoShown = modoCatcherBackground('''
CATCHER_ALPHA_NEW = '''                transparency = 1.f - modoCatcher;
                // Modo: seen through glass alone, see-through in alpha as the sky through glass is (-throughput), but
                // for its shadows: -throughput x (1 - strength) here, the unshadowed samples taking the rest
                // (modoCatcherShare); nothing taken with the switch off (tools/port_glass_alpha.py). A path past the
                // camera carries no pixel weight, so this goes as a miss's does, an entry of its own (modoTakeAlpha).
                if (modoThroughGlass) {
                    transparency = 0.f;
                    if (CPP_modoGlassAlpha()) {
                        modoTakeAlpha(pbrTls, *rs, -reduceTransparency(pv.pathThroughput) * (1.f - modoCatcher));
                    }
                }
                modoShown = modoCatcherBackground('''

TAKE_ALPHA_HELPER = '''// Modo: alpha taken off a sample at a hit past the camera, as RayHandlers.cc's miss takes it for glass in alpha: an
// entry of its own, with no colour and no pixel weight (tools/port_glass_alpha.py).
inline void
modoTakeAlpha(uniform PbrTLState * uniform pbrTls, const varying RayState &rs, const varying float alpha)
{
    varying BundledRadiance entry;
    uniform uint32_t indices[programCount + 1];
    entry.mRadiance = Vec4f_ctor(0.f, 0.f, 0.f, alpha);
    entry.mPathPixelWeight = 0.f;
    entry.mPixel = rs.mSubpixel.mPixel;
    entry.mSubPixelIndex = rs.mSubpixel.mSubpixelIndex;
    entry.mDeepDataHandle = rs.mDeepDataHandle;
    entry.mCryptomatteDataHandle = rs.mCryptomatteDataHandle;
    entry.mCryptoRefP = rs.mCryptoRefP;
    entry.mCryptoP0 = rs.mCryptoP0;
    entry.mCryptoRefN = rs.mCryptoRefN;
    entry.mCryptoUV = rs.mCryptoUV;
    PbrTLState_acquireDeepData(pbrTls, entry.mDeepDataHandle);
    PbrTLState_acquireCryptomatteData(pbrTls, entry.mCryptomatteDataHandle);
    entry.mTilePass = rs.mTilePass;
    const uniform uint32_t count = packed_store_active2(indices, programIndex);
    CPP_addRadianceQueueEntries(pbrTls, &entry, count, indices);
}

void
integrateBundled( const uniform PathIntegrator * uniform this,
'''

SHARE_SCALE_OLD = '''        modoCatcherShare(pbrTls, occlRays, occlRayIndices, numOcclRaysFilled, lightSetSampleCount, modoCatcher,
                         modoShown, modoTotal, modoMatte, pv.pathPixelWeight, modoBgLpe);
        modoCatcherShare(pbrTls, presenceShadowsRays, presenceShadowsRayIndices, numPresenceShadowsRaysFilled,
                         lightSetSampleCount, modoCatcher, modoShown, modoTotal, modoMatte, pv.pathPixelWeight,
                         modoBgLpe);
'''
SHARE_SCALE_NEW = '''        // Modo: the alpha a matte's unshadowed samples take back: by the pixel weight at the camera; past it, seen
        // through glass alone, by what the glass lets through, as the sky seen through it is (tools/port_glass_alpha.py).
        const varying float modoAlphaScale = ray.ext.depth == 0 ? pv.pathPixelWeight :
            (CPP_modoGlassAlpha() ? reduceTransparency(pv.pathThroughput) : 0.f);
        modoCatcherShare(pbrTls, occlRays, occlRayIndices, numOcclRaysFilled, lightSetSampleCount, modoCatcher,
                         modoShown, modoTotal, modoMatte, modoAlphaScale, modoBgLpe);
        modoCatcherShare(pbrTls, presenceShadowsRays, presenceShadowsRayIndices, numPresenceShadowsRaysFilled,
                         lightSetSampleCount, modoCatcher, modoShown, modoTotal, modoMatte, modoAlphaScale,
                         modoBgLpe);
'''

SCALAR_EARLY_OLD = '''    if (modoShadowCatcher() && material->getModoShadowCatcher()) {
        return radiance;
    }
'''
SCALAR_EARLY_NEW = '''    // Modo: but a matte seen through glass alone is seen as from the camera, below (tools/port_glass_alpha.py).
    const bool modoThroughGlass = modoShadowCatcher() && material->getModoShadowCatcher() &&
                                  material->getModoShadowMatte() && pv.modoSeeThrough;
    if (modoShadowCatcher() && material->getModoShadowCatcher() && !modoThroughGlass) {
        return radiance;
    }
'''
SCALAR_SAMPLE_OLD = '''    radiance += computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
        doIndirect, indirectFlags, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
        rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
        parentLobeLightSets);

    float minTransparency = reduceTransparency(vt.mTransmittanceMin);
'''
SCALAR_SAMPLE_NEW = '''    if (modoThroughGlass) {
        // Modo: a matte seen through glass alone, as computeRadianceRecurse0 sees one from the camera: the background
        // past it (the lights the camera sees there), (1 - strength) of it outright and the rest as much as its light
        // samples are not shadowed; see-through in alpha as the sky through glass is, but for those shadows
        // (tools/port_glass_alpha.py).
        ModoCatcherTally &tally = modoCatcherTally();
        tally = ModoCatcherTally();
        tally.on = true;
        computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
            false, shading::BsdfLobe::Type::NONE, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
            rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, nullptr, cryptomatteFlags,
            parentLobeLightSets);
        tally.on = false;
        const float strength = scene_rdl2::math::clamp(material->getModoShadowStrength(), 0.f, 1.f);
        const scene_rdl2::math::Color total(tally.total[0], tally.total[1], tally.total[2]);
        const scene_rdl2::math::Color lit(tally.lit[0], tally.lit[1], tally.lit[2]);
        const float whole = scene_rdl2::math::luminance(total);
        const float part = whole > 0.f ? scene_rdl2::math::luminance(lit) / whole : 1.f;
        const scene_rdl2::math::Color share(total.r > 0.f ? lit.r / total.r : part,
                                            total.g > 0.f ? lit.g / total.g : part,
                                            total.b > 0.f ? lit.b / total.b : part);
        radiance -= selfEmission;
        scene_rdl2::math::Color modoBackground(0.f);
        int modoBgLpe = -1;
        mcrt_common::Ray modoPast(isect.getP(), ray.getDirection(), 0.f, sInfiniteLightDistance, ray.getTime(),
                                  ray.getDepth());
        LightIntersection modoPastIsect;
        int modoHits = 0;
        SequenceIDIntegrator modoSid(0, sp.mPixel, sp.mSubpixelIndex, SequenceType::IndexSelection, sequenceID);
        IntegratorSample1D modoChoice(modoSid);
        const Light *modoLight = scene->intersectVisibleLight(modoPast, sInfiniteLightDistance, modoChoice,
                                                              modoPastIsect, modoHits);
        if (modoLight) {
            LightFilterRandomValues modoFilterR = {
                scene_rdl2::math::Vec2f(0.f, 0.f), scene_rdl2::math::Vec3f(0.f, 0.f, 0.f)};
            modoBackground = pv.pathThroughput * modoHits *
                modoLight->eval(pbrTls->mTopLevelTls, ray.getDirection(), isect.getP(), modoFilterR, ray.getTime(),
                                modoPastIsect, true, nullptr, nullptr, ray.getDirFootprint(), nullptr, nullptr);
            if (aovs && pv.lpeStateId >= 0) {
                const int straight = lightAovs.straightEventTransition(pbrTls, pv.lpeStateId);
                if (straight >= 0) {
                    modoBgLpe = lightAovs.lightEventTransition(pbrTls, straight, modoLight);
                }
            }
        }
        const scene_rdl2::math::Color modoSeen = modoBackground * ((1.f - strength) + strength * share);
        radiance += modoSeen;
        if (aovs && modoBgLpe >= 0 && !isBlack(modoSeen)) {
            aovAccumLightAovs(pbrTls, aovSchema, lightAovs, modoSeen, nullptr, AovSchema::sLpePrefixNone,
                              modoBgLpe, aovs);
        }
        if (modoGlassAlpha()) {
            modoSeenThrough() += reduceTransparency(pv.pathThroughput) * (1.f - strength * (1.f - part));
        }
        return radiance;
    }

    radiance += computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
        doIndirect, indirectFlags, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
        rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
        parentLobeLightSets);

    float minTransparency = reduceTransparency(vt.mTransmittanceMin);
'''

CATCHER_EDITS = {
    'pbr/integrator/PathIntegratorBundled.ispc': [(CATCHER_DEPTH_OLD, CATCHER_DEPTH_NEW, 1), (CATCHER_ALPHA_OLD, CATCHER_ALPHA_NEW, 1),
                                                  ('''void
integrateBundled( const uniform PathIntegrator * uniform this,
''', TAKE_ALPHA_HELPER, 1)],
    'pbr/integrator/PathIntegratorMultiSampler.ispc': [(SHARE_SCALE_OLD, SHARE_SCALE_NEW, 1)],
    'pbr/integrator/PathIntegrator.isph': [
        ('''CPP_modoShadowCatcher(uniform int64 material, uniform float * uniform strength, uniform int * uniform matte);
''', '''CPP_modoShadowCatcher(uniform int64 material, uniform float * uniform strength, uniform int * uniform matte);

// Modo: glass in alpha's switch (tools/port_glass_alpha.py)
extern "C" uniform int
CPP_modoGlassAlpha();
''', 1)],
    'pbr/integrator/PathIntegratorUtil.h': [
        ('''void CPP_modoShadowCatcher(int64_t material, float *strength, int *matte);
''', '''void CPP_modoShadowCatcher(int64_t material, float *strength, int *matte);
// Modo: glass in alpha's switch, 1 for on (tools/port_glass_alpha.py)
int CPP_modoGlassAlpha();
''', 1)],
    'pbr/integrator/PathIntegratorUtil.cc': [
        ('''    *matte = held->getModoShadowMatte() ? 1 : 0;
}
''', '''    *matte = held->getModoShadowMatte() ? 1 : 0;
}

// Modo: glass in alpha's switch, 1 for on (tools/port_glass_alpha.py).
int
CPP_modoGlassAlpha()
{
    return modoGlassAlpha() ? 1 : 0;
}
''', 1),
        ('''#include <moonray/rendering/pbr/core/ModoShadowCatcher.h>
''', '''#include <moonray/rendering/pbr/core/ModoShadowCatcher.h>
#include <moonray/rendering/pbr/core/ModoGlassAlpha.h>
''', 1)],
    'pbr/integrator/PathIntegrator.cc': [(SCALAR_EARLY_OLD, SCALAR_EARLY_NEW, 1), (SCALAR_SAMPLE_OLD, SCALAR_SAMPLE_NEW, 1)],
}

TRANSMITS = '(lobe->getType() & shading::BsdfLobe::TRANSMISSION) && (lobe->getType() & (shading::BsdfLobe::GLOSSY | shading::BsdfLobe::MIRROR))'

EDITS = {
    'pbr/core/RayState.hh': [
        ('''    HVD_MEMBER(float, modoFogPending)                                       /*   92  */
''', '''    HVD_MEMBER(float, modoFogPending);                                      /*   92  */\\
    /* Modo: seen through glass alone so far, and a spare int: C++ pads the vertex to 8 (tools/port_glass_alpha.py) */\\
    HVD_MEMBER(int, modoSeeThrough);                                        /*   96  */\\
    HVD_MEMBER(int, modoSpare)                                              /*  100  */
''', 1),
        ('''    HVD_VALIDATE(PathVertex, modoFogPending);       \\
''', '''    HVD_VALIDATE(PathVertex, modoFogPending);       \\
    HVD_VALIDATE(PathVertex, modoSeeThrough);       \\
    HVD_VALIDATE(PathVertex, modoSpare);            \\
''', 1),
        ('''#define RAY_STATE_MEMBERS_PAD   68 /* Modo: 8 bytes to PathVertex (tools/port_fog_alpha.py) */
''', '''#define RAY_STATE_MEMBERS_PAD   60 /* Modo: 8 bytes to PathVertex (tools/port_fog_alpha.py), 8 (tools/port_glass_alpha.py) */
''', 1),
        ('''#define RAY_STATE_MEMBERS_PAD   20 /* Modo: 8 bytes to PathVertex (tools/port_fog_alpha.py) */
''', '''#define RAY_STATE_MEMBERS_PAD   12 /* Modo: 8 bytes to PathVertex (tools/port_fog_alpha.py), 8 (tools/port_glass_alpha.py) */
''', 1),
    ],
    'pbr/integrator/PathIntegrator.cc': [
        ('''#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
''', '''#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
#include <moonray/rendering/pbr/core/ModoGlassAlpha.h>
''', 1),
        ('''    pv.modoFogPending = 0.f;
''', '''    pv.modoFogPending = 0.f;
    pv.modoSeeThrough = 1;      // Modo: tools/port_glass_alpha.py
''', 1),
        # Scalar: a miss past the camera of a path that went through glass alone (computeRadianceRecurse1).
        ('''            aovAccumBackgroundExtraAovs(pbrTls, fs, pv, aovs);
        }
        transparency = reduceTransparency(vt.mTransmittanceAlpha);
        return radiance;
''', '''            aovAccumBackgroundExtraAovs(pbrTls, fs, pv, aovs);
        }
        transparency = reduceTransparency(vt.mTransmittanceAlpha);
        // Modo: seen through glass alone, out of the scene: see-through in alpha (tools/port_glass_alpha.py).
        if (modoGlassAlpha() && pv.modoSeeThrough) {
            modoSeenThrough() += reduceTransparency(pv.pathThroughput);
        }
        return radiance;
''', 1),
        ('''        float transparency;
        radiance = computeRadianceRecurse0(pbrTls, ray, sp, pv, /* lobe = */ nullptr,
                                           transparency, vt,
                                           sequenceID, aovs, depth,
                                           /* deepParams = */ nullptr, cryptomatteFlags,
                                           Rdl2LightSetList());

        alpha = 1.f - transparency;
''', '''        float transparency;
        modoSeenThrough() = 0.f;    // Modo: tools/port_glass_alpha.py
        radiance = computeRadianceRecurse0(pbrTls, ray, sp, pv, /* lobe = */ nullptr,
                                           transparency, vt,
                                           sequenceID, aovs, depth,
                                           /* deepParams = */ nullptr, cryptomatteFlags,
                                           Rdl2LightSetList());

        alpha = 1.f - transparency;
        // Modo: what of this sample went through glass alone and out of the scene (tools/port_glass_alpha.py).
        if (modoGlassAlpha()) {
            alpha = scene_rdl2::math::max(0.f, alpha - modoSeenThrough());
        }
''', 1),
    ],
    'pbr/integrator/PathIntegratorMultiSampler.cc': [
        ('''            pv.lobeType = lobe->getType();
''', '''            pv.lobeType = lobe->getType();
            // Modo: still seen through glass alone (tools/port_glass_alpha.py).
            pv.modoSeeThrough = (parentPv.modoSeeThrough && %s) ? 1 : 0;
''' % TRANSMITS, 1),
    ],
    'pbr/integrator/PathIntegratorMultiSampler.ispc': [
        ('''            pv.lobeType = BsdfLobe_getType(lobe);
''', '''            pv.lobeType = BsdfLobe_getType(lobe);
            // Modo: still seen through glass alone (tools/port_glass_alpha.py).
            pv.modoSeeThrough = (parentPv.modoSeeThrough != 0 &&
                                 (BsdfLobe_getType(lobe) & BSDF_LOBE_TYPE_TRANSMISSION) != 0 &&
                                 (BsdfLobe_getType(lobe) & (BSDF_LOBE_TYPE_GLOSSY | BSDF_LOBE_TYPE_MIRROR)) != 0) ? 1 : 0;
''', 1),
    ],
    'pbr/integrator/PathIntegratorSubsurface.cc': [
        ('''    PathVertex nextPv;
''', '''    PathVertex nextPv;
    nextPv.modoSeeThrough = 0;      // Modo: tools/port_glass_alpha.py
''', 2),
    ],
    'pbr/integrator/PathIntegratorVolume.cc': [
        ('''        PathVertex newPv = pv;
''', '''        PathVertex newPv = pv;
        newPv.modoSeeThrough = 0;   // Modo: scattered in a volume (tools/port_glass_alpha.py)
''', 1),
    ],
    'pbr/handlers/RayHandlers.cc': HANDLER_EDITS,
    'pbr/handlers/XPURayHandlers.cc': HANDLER_EDITS,
}
for _name, _edits in CATCHER_EDITS.items():
    EDITS[_name] = EDITS.get(_name, []) + _edits


def patch_text(name, text, edits):
    for old, new, count in edits:
        for ending in ('\n', '\r\n'):
            o, n = old.replace('\n', ending), new.replace('\n', ending)
            if n in text:
                break
            if text.count(o) == count:
                text = text.replace(o, n)
                break
        else:
            raise RuntimeError('Glass alpha anchor missing or ambiguous in %s: %r' % (name, old[:80]))
    return text


def main():
    if not HEADER.exists() or HEADER.read_text(encoding='utf-8') != HEADER_TEXT:
        HEADER.write_text(HEADER_TEXT, encoding='utf-8')
        print('wrote', HEADER.relative_to(RENDERING))
    for name, edits in EDITS.items():
        source = RENDERING / name
        text = source.read_bytes().decode('utf-8')
        patched = patch_text(name, text, edits)
        if patched != text:
            source.write_bytes(patched.encode('utf-8'))
            print('patched', name)
        else:
            print('already in', name)


if __name__ == '__main__':
    main()
