"""Shadow catchers in MoonRay (the kit's Backplate item, and Make as Shadow Catcher on a MoonRay Object).

MoonRay has no shadow catcher. A catcher is a surface the scene stands on, wearing the backplate photo as its emission
(backplate.plate_material): the camera is to see the photo, darkened only where the scene shades it; reflections and
refractions are to see the photo as it is.

Unless MoonRay is started with MOONRAY_MODO_SHADOW_CATCHER=0 (the kit's Backplate Source Override off; unset is on):

1. scene_rdl2: every Material has modo_shadow_catcher (off), modo_shadow_strength (1) and modo_shadow_matte (off).
2. Vector and XPU (PathIntegratorBundled.ispc): a ray of any depth past the camera that hits a catcher takes its
   emission alone, unlit, and goes no further. A camera ray takes (1 - strength) of the emission outright; the rest
   comes back through the shadow rays of its light samples: each carries emission x strength x its share of all the
   light samples' unshadowed contributions (PathIntegratorMultiSampler.ispc, modoCatcherShare). Unshadowed, the shares
   add up to the whole emission, the photo itself; a shadow ray that is blocked leaves its share out. The catcher
   spawns no indirect rays, and its bsdf-sampled shadow rays carry nothing.
3. Matte (modo_shadow_matte: a MoonRay Object's Make as Shadow Catcher, the Backplate's "backplate in the render" off):
   the surface itself is not seen. The camera sees what it would see past it, the background: the lights it sees
   along the ray beyond the hit, as a camera ray that hits nothing sees them (modoCatcherBackground, one chosen among
   those met times their number), darkened by the shadows exactly as the emission is above, (1 - strength) of it
   outright and the rest through the light samples' shadow rays. Its alpha is strength at the camera ray, each
   unshadowed light sample taking its share back off (BundledOcclRay.mModoAlpha, which the occlusion handlers write as
   the result's alpha): the alpha holds the shadows alone, as the background's (a light's) is 0. With no environment
   visible to the camera the background is black: no colour, the shadows in alpha. In the light path outputs, the
   background shown goes through the camera's straight event at the catcher then the light's (C<Ts><L>, so
   Environment background holds it), the catcher's own lighting not at all (modoCatcherLpe; a matte's light samples
   keep a data block for it, modoMatteCatcherAt). A matte reached by any ray past the camera (a reflection, a bounce)
   is seen the same way, not as its emission: the lights of the hit's light set that ray's kind sees past it, darkened
   by its shadows, its alpha left as it is (tools/port_glass_alpha.py, which runs after this, has a path through
   glass alone see the camera's lights and be see-through in alpha).
4. Scalar (PathIntegrator.cc, computeRadianceRecurse): the same, its light samples' shadow rays traced as they are
   drawn (PathIntegratorMultiSampler.cc).

With it 0, or a material not a catcher, MoonRay renders as before."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOONRAY = ROOT / 'upstream/openmoonray/moonray'
RENDERING = MOONRAY / 'moonray/lib/rendering'
RDL2 = MOONRAY / 'scene_rdl2/lib/scene/rdl2'

HEADER = RENDERING / 'pbr/core/ModoShadowCatcher.h'
HEADER_TEXT = '''// Modo: shadow catchers (tools/port_shadow_catcher.py).
#pragma once

#include <cstdlib>

namespace moonray {
namespace pbr {

/// True unless MoonRay was started with MOONRAY_MODO_SHADOW_CATCHER=0. Read once.
inline bool modoShadowCatcher()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_SHADOW_CATCHER");
        return !value || value[0] != '0';
    }();
    return on;
}

/// Scalar mode: a shadow catcher's light samples counted as they are traced (PathIntegratorMultiSampler.cc), the
/// whole of their unshadowed contributions and what of it is not shadowed.
struct ModoCatcherTally
{
    bool on = false;
    float total[3] = {0.f, 0.f, 0.f};
    float lit[3] = {0.f, 0.f, 0.f};
};

inline ModoCatcherTally &modoCatcherTally()
{
    thread_local ModoCatcherTally tally;
    return tally;
}

} // namespace pbr
} // namespace moonray
'''

PRIMARY_OLD = '''    radiance += computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
        doIndirect, indirectFlags, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
        rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
        parentLobeLightSets);

    // -------------------------------------------------------------------
    // Cryptomatte handling
'''
PRIMARY_NEW = '''    // Modo: a shadow catcher seen by the camera (tools/port_shadow_catcher.py): (1 - strength) of its emission
    // outright, the rest as much as its light samples are not shadowed; as a matte, the background in its place, darkened
    // the same way, and the shadows in alpha.
    if (modoShadowCatcher() && material->getModoShadowCatcher()) {
        const bool modoMatte = material->getModoShadowMatte();
        ModoCatcherTally &tally = modoCatcherTally();
        tally = ModoCatcherTally();
        tally.on = true;
        // A matte's own lighting is in no light path output: what it shows is the background (below).
        computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
            false, shading::BsdfLobe::Type::NONE, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
            rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, modoMatte ? nullptr : aovs, cryptomatteFlags,
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
        if (modoMatte) {
            transparency = 1.f - strength * (1.f - part);
            // What the camera would see past it: the lights it sees along the ray beyond the hit, as a camera ray that
            // hits nothing sees them; in the light path outputs through the camera's straight event at the catcher.
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
        } else {
            radiance += selfEmission * ((1.f - strength) + strength * share);
        }
    } else {
    radiance += computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
        doIndirect, indirectFlags, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
        rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
        parentLobeLightSets);
    }

    // -------------------------------------------------------------------
    // Cryptomatte handling
'''

RECURSE_OLD = '''    shading::BsdfLobe::Type indirectFlags = shading::BsdfLobe::Type::NONE;
    if ((mBsdfSamples > 0) && (ray.getDepth() < mMaxDepth) && lobe) {
'''
RECURSE_NEW = '''    // Modo: a shadow catcher seen past the camera is what it wears (its emission), unlit; a matte, what the ray sees of
    // the lights past it, darkened by its shadows (below) (tools/port_shadow_catcher.py).
    const bool modoPastMatte = modoShadowCatcher() && material->getModoShadowCatcher() && material->getModoShadowMatte();
    if (modoShadowCatcher() && material->getModoShadowCatcher() && !modoPastMatte) {
        return radiance;
    }

    shading::BsdfLobe::Type indirectFlags = shading::BsdfLobe::Type::NONE;
    if ((mBsdfSamples > 0) && (ray.getDepth() < mMaxDepth) && lobe) {
'''

RECURSE_SAMPLE_OLD = '''    radiance += computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
        doIndirect, indirectFlags, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
        rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
        parentLobeLightSets);

    float minTransparency = reduceTransparency(vt.mTransmittanceMin);
'''
RECURSE_SAMPLE_NEW = '''    if (modoPastMatte) {
        // Modo: a matte seen past the camera (a reflection, a refraction, a bounce), as computeRadianceRecurse0 sees one
        // from the camera: what the ray sees of the lights past it, (1 - strength) of it outright and the rest as much
        // as its light samples are not shadowed; nothing bounces off it, and its alpha is left as it is
        // (tools/port_shadow_catcher.py). The lights: those of its active set the ray's kind sees, or, where
        // modoCameraSees, those the camera sees.
        const bool modoCameraSees = false;
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
        LightIntersection modoPastIsect;
        int modoHits = 0;
        SequenceIDIntegrator modoSid(0, sp.mPixel, sp.mSubpixelIndex, SequenceType::IndexSelection, sequenceID);
        IntegratorSample1D modoChoice(modoSid);
        const Light *modoLight = nullptr;
        if (modoCameraSees) {
            mcrt_common::Ray modoPast(isect.getP(), ray.getDirection(), 0.f, sInfiniteLightDistance, ray.getTime(),
                                      ray.getDepth());
            modoLight = scene->intersectVisibleLight(modoPast, sInfiniteLightDistance, modoChoice, modoPastIsect, modoHits);
        } else {
            const int modoIndex = activeLightSet.intersect(isect.getP(), nullptr, ray.getDirection(), ray.getTime(),
                sInfiniteLightDistance, false, modoChoice, ray.getDepth(), lobeTypeToRayMask(pv.lobeType),
                modoPastIsect, modoHits, nullptr, Rdl2LightSetList());
            modoLight = modoIndex >= 0 ? activeLightSet.getLight(modoIndex) : nullptr;
        }
        if (modoLight) {
            LightFilterRandomValues modoFilterR = {
                scene_rdl2::math::Vec2f(0.f, 0.f), scene_rdl2::math::Vec3f(0.f, 0.f, 0.f)};
            modoBackground = pv.pathThroughput * modoHits *
                modoLight->eval(pbrTls->mTopLevelTls, ray.getDirection(), isect.getP(), modoFilterR, ray.getTime(),
                                modoPastIsect, modoCameraSees, nullptr, nullptr, ray.getDirFootprint(), nullptr, nullptr);
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
        return radiance;
    }

    radiance += computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
        doIndirect, indirectFlags, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
        rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
        parentLobeLightSets);

    float minTransparency = reduceTransparency(vt.mTransmittanceMin);
'''

TALLY_TOTAL_OLD = '''        scene_rdl2::math::Color lightT = lsmp[i].t;
        if (isBlack(lightT)) {
            continue;
        }
'''
TALLY_TOTAL_NEW = '''        scene_rdl2::math::Color lightT = lsmp[i].t;
        if (isBlack(lightT)) {
            continue;
        }
        // Modo: a shadow catcher's light samples, counted unshadowed (tools/port_shadow_catcher.py).
        ModoCatcherTally &modoTally = modoCatcherTally();
        if (modoTally.on) {
            modoTally.total[0] += lightT.r;
            modoTally.total[1] += lightT.g;
            modoTally.total[2] += lightT.b;
        }
'''
# The source line ends in two spaces: anchored without its line's end.
TALLY_FALLOFF_OLD = '''                radiance += calculateShadowFalloff(light, tfar, tr * lightT);'''
TALLY_FALLOFF_NEW = '''                const scene_rdl2::math::Color modoFalloff = calculateShadowFalloff(light, tfar, tr * lightT);
                radiance += modoFalloff;
                if (modoTally.on) {
                    modoTally.lit[0] += modoFalloff.r;
                    modoTally.lit[1] += modoFalloff.g;
                    modoTally.lit[2] += modoFalloff.b;
                }'''
TALLY_LIT_OLD = '''            radiance += tr * lightT;

            // LPE
'''
TALLY_LIT_NEW = '''            radiance += tr * lightT;
            if (modoTally.on) {
                modoTally.lit[0] += (tr * lightT).r;
                modoTally.lit[1] += (tr * lightT).g;
                modoTally.lit[2] += (tr * lightT).b;
            }

            // LPE
'''

CATCHER_BLOCK = '''        //---------------------------------------------------------------------
        // Modo: a shadow catcher (tools/port_shadow_catcher.py). Seen past the camera, it is what it wears (its
        // emission) unlit, and the path ends. Seen by the camera, (1 - strength) of its emission is taken outright and
        // the rest comes back through its light samples' shadow rays, each its share (modoCatcherShare); as a matte,
        // the background in place of the emission (modoCatcherBackground) and an alpha of strength, which the
        // unshadowed samples take back off. A matte reached by any ray past the camera (a reflection, a bounce) is
        // seen the same way, by what that ray sees of the lights past it, its alpha left as it is.
        varying float modoCatcher = -1.f;
        varying bool modoMatte = false;
        modoShadowCatcherOf(isect, modoCatcher, modoMatte);
        varying Color modoShown = sBlack;
        varying int modoBgLpe = -1;
        // Whether the lights past the matte are those the camera sees (the camera's own ray), or those the ray's kind
        // sees in the hit's light set (any other).
        varying bool modoCameraSees = rayDepth == 0;
        if (modoCatcher >= 0.f) {
            if (rayDepth > 0 && !modoMatte) {
                numRadiances += fillBundledRadiance(pbrTls,
                                                    radiances + i,
                                                    &radianceIndices[numRadiances],
                                                    rayIndices,
                                                    rayDepth,
                                                    radiance,
                                                    pv.pathPixelWeight,
                                                    transparency,
                                                    *rs);
                continue;
            }
            modoShown = selfEmission;
            if (modoMatte) {
                radiance = radiance - selfEmission;
                transparency = rayDepth > 0 ? 0.f : 1.f - modoCatcher;
                modoShown = modoCatcherBackground(pbrTls, shadingTls, visibleLightSet, lightSet, modoCameraSees, lightAovs,
                                                  aovs, *rs, ray, isect, modoBgLpe);
                const varying Color modoOutright = modoShown * (1.f - modoCatcher);
                radiance = radiance + modoOutright;
                if (aovs && modoBgLpe > 0 && !isBlack(modoOutright)) {
                    aovAccumLightAovs(pbrTls, aovSchema, lightAovs, modoOutright, modoBgLpe, sp.mPixel,
                                      rs->mDeepDataHandle);
                }
            } else {
                radiance = radiance - selfEmission * modoCatcher;
            }
        }

        //---------------------------------------------------------------------
        // Early out if we don't have any Bsdf lobes nor Bssrdf
'''

CATCHER_HELPER = '''
// Modo: whether a hit's material is a shadow catcher (tools/port_shadow_catcher.py): its strength (-1 for none) and
// whether it is a matte. Asked once for each material in the bundle.
inline void
modoShadowCatcherOf(const varying Intersection &isect, varying float &strength, varying bool &matte)
{
    strength = -1.f;
    matte = false;
    const varying intptr_t address = Address64_get(isect.mMaterial);
    foreach_unique (material in address) {
        uniform float held = -1.f;
        uniform int asMatte = 0;
        if (material != 0) {
            CPP_modoShadowCatcher((uniform int64)material, &held, &asMatte);
        }
        strength = held;
        matte = asMatte != 0;
    }
}
'''

BACKGROUND_HELPER = '''// Modo: what a ray would see past a matte shadow catcher (tools/port_shadow_catcher.py): the lights it meets along its
// way beyond the hit, one chosen among them, times their number; black where it meets none. cameraSees: those the camera
// sees (visibleLightSet), as a camera ray that hits nothing sees them (RayHandlers.cc); otherwise those of the hit's
// light set (lightSet) visible to the ray's kind (its lobe's ray mask), as its parent's BSDF sample would have met them
// had the catcher not been in the way. lpeStateId: the light path state of that, the ray's straight event through the
// catcher then the light's (-1 for none), with which Environment background (C<Ts>*<L>) holds what the camera sees.
inline varying Color
modoCatcherBackground(      uniform PbrTLState *     uniform pbrTls,
                            uniform ShadingTLState * uniform shadingTls,
                      const uniform LightSet *       uniform visibleLightSet,
                      const uniform LightSet *       uniform lightSet,
                      const varying bool                     cameraSees,
                      const uniform LightAovs &              lightAovs,
                      const uniform bool                     aovs,
                      const varying RayState &               rs,
                      const varying RayDifferential &        ray,
                      const varying Intersection &           isect,
                            varying int &                    lpeStateId)
{
    lpeStateId = -1;
    const uniform FrameState &fs = *pbrTls->mFs;
    varying SequenceID sid;
    SequenceID_init(sid, rs.mSubpixel.mPixel, rs.mSubpixel.mSubpixelIndex, fs.mInitialSeed);
    varying IntegratorSample1D lightChoiceSamples;
    IntegratorSample1D_init(lightChoiceSamples, sid);
    varying Vec3f cullingNormal;
    setInvalidCullingNormal(&cullingNormal);
    const varying Vec3f origin = getP(isect);
    varying LightIntersection hitLightIsect;
    varying int numHits = 0;
    varying Color background = sBlack;
    const uniform Light * varying hitLight = nullptr;
    // light filters don't apply to camera rays, nor here (what lies past the catcher is not lit by the light)
    varying LightFilterRandomValues lightFilterR = { Vec2f_ctor(0.f, 0.f), Vec3f_ctor(0.f, 0.f, 0.f) };
    if (cameraSees) {
        const varying int lightIdx = LightSet_intersect(pbrTls, visibleLightSet, origin, cullingNormal,
                                                        Ray_getDirection(ray), Ray_getTime(ray), sInfiniteLightDistance,
                                                        false, lightChoiceSamples, 0, -1, hitLightIsect, numHits, 0, 0);
        if (lightIdx >= 0) {
            hitLight = LightSet_getLight(visibleLightSet, lightIdx);
            background = rs.mPathVertex.pathThroughput * numHits *
                Light_eval(hitLight, shadingTls, Ray_getDirection(ray), origin, lightFilterR, Ray_getTime(ray),
                           hitLightIsect, true, nullptr, nullptr, Ray_getDirFootprint(ray), nullptr, nullptr);
        }
    } else {
        const varying int lightIdx = LightSet_intersect(pbrTls, lightSet, origin, cullingNormal,
                                                        Ray_getDirection(ray), Ray_getTime(ray), sInfiniteLightDistance,
                                                        false, lightChoiceSamples, ray.ext.depth,
                                                        lobeTypeToRayMask(rs.mPathVertex.lobeType), hitLightIsect,
                                                        numHits, 0, 0);
        if (lightIdx >= 0) {
            hitLight = LightSet_getLight(lightSet, lightIdx);
            background = rs.mPathVertex.pathThroughput * numHits *
                Light_eval(hitLight, shadingTls, Ray_getDirection(ray), origin, lightFilterR, Ray_getTime(ray),
                           hitLightIsect, false, nullptr, nullptr, Ray_getDirFootprint(ray), nullptr, nullptr);
        }
    }
    if (hitLight != nullptr) {
        if (aovs && LightAovs_hasEntries(&lightAovs) && rs.mPathVertex.lpeStateId >= 0) {
            const varying int straight = LpeStateMachine_transition(&lightAovs.mLpeStateMachine,
                rs.mPathVertex.lpeStateId, LPE_EVENT_TYPE_TRANSMISSION, LPE_EVENT_SCATTERING_TYPE_STRAIGHT, LPE_noLabel);
            lpeStateId = LightAovs_lightEventTransition(&lightAovs, straight, hitLight);
        }
    }
    return background;
}

void
integrateBundled( const uniform PathIntegrator * uniform this,
'''

MATTE_AT_HELPER = '''// Modo: whether a hit is on a matte shadow catcher (tools/port_shadow_catcher.py).
static varying bool
modoMatteCatcherAt(const varying Intersection &isect)
{
    varying bool matte = false;
    const varying intptr_t address = Address64_get(isect.mMaterial);
    foreach_unique (material in address) {
        uniform float held = -1.f;
        uniform int asMatte = 0;
        if (material != 0) {
            CPP_modoShadowCatcher((uniform int64)material, &held, &asMatte);
        }
        matte = held >= 0.f && asMatte != 0;
    }
    return matte;
}

void addDirectVisibleLightSampleContributionsBundled(       uniform PbrTLState *     uniform pbrTls,
'''

KEEP_OLD = '''                if (numItems > 0) {
                    data = PbrTLState_allocList(pbrTls, sizeof(uniform BundledOcclRayData), numItems);
                }
'''
KEEP_NEW = '''                // Modo: a matte shadow catcher's samples keep a block with no expression of their own to carry, for
                // the background they bring (modoCatcherLpe, tools/port_shadow_catcher.py).
                const varying bool modoKeep = numItems == 0 && modoMatteCatcherAt(isect);
                if (numItems > 0 || modoKeep) {
                    data = PbrTLState_allocList(pbrTls, sizeof(uniform BundledOcclRayData), numItems > 0 ? numItems : 1);
                }
                if (modoKeep) {
                    uniform BundledOcclRayData * varying b =
                        (uniform BundledOcclRayData * varying) PbrTLState_getListItem(pbrTls, data, 0);
                    b->mFlags = LPE | LIGHT_SAMPLE;
                    b->mLpeStateId = 0;
                }
'''

SHARE_HELPERS = '''// Modo: a shadow catcher seen by the camera (tools/port_shadow_catcher.py). Its light samples' shadow rays (slots below
// lightSlots; above them, its bsdf samples') carry, between them, what it would gather unshadowed (modoCatcherTotal);
// each is given instead the catcher's emission x strength x its share of that, so that unshadowed they add up to the
// emission and a blocked one leaves its share out. As a matte, the same of the background (shown), its share of the
// alpha taken back off, and in the light path outputs that share of the background (modoCatcherLpe).
static void
modoCatcherTotal(const varying BundledOcclRay * uniform rays, const uniform uint32_t * uniform indices,
                 uniform uint32_t count, uniform int lightSlots, varying Color &total)
{
    for (uniform uint32_t k = 0; k < count; ++k) {
        const uniform uint32_t slot = indices[k] / programCount;
        const uniform uint32_t lane = indices[k] % programCount;
        if (slot < lightSlots && programIndex == lane) {
            total = total + rays[slot].mRadiance;
        }
    }
}

// A matte's shadow ray: its light path expressions carry the share of the background it brings (value), under bgLpe
// (modoCatcherBackground's state; none for -1), in place of the catcher's own lighting.
static void
modoCatcherLpe(uniform PbrTLState * uniform pbrTls, varying BundledOcclRay &ray, const varying int bgLpe,
               const varying Color &value)
{
    if (ray.mDataPtrHandle == PBR_nullHandle) {
        return;
    }
    const varying unsigned int items = PbrTLState_getNumListItems(pbrTls, ray.mDataPtrHandle);
    for (varying unsigned int j = 0; j < items; ++j) {
        uniform BundledOcclRayData * varying b =
            (uniform BundledOcclRayData * varying) PbrTLState_getListItem(pbrTls, ray.mDataPtrHandle, j);
        if (j == 0 && bgLpe > 0) {
            b->mFlags |= LPE;
            b->mLpeStateId = bgLpe;
            b->mLpeRadiance = value;
        } else if (b->mFlags & LPE) {
            b->mLpeStateId = 0;     // no more valid items in the list
        }
    }
}

static void
modoCatcherShare(uniform PbrTLState * uniform pbrTls,
                 varying BundledOcclRay * uniform rays, const uniform uint32_t * uniform indices,
                 uniform uint32_t count, uniform int lightSlots, const varying float catcher,
                 const varying Color &shown, const varying Color &total, const varying bool matte,
                 const varying float pathPixelWeight, const varying int bgLpe)
{
    const varying float whole = luminance(total);
    for (uniform uint32_t k = 0; k < count; ++k) {
        const uniform uint32_t slot = indices[k] / programCount;
        const uniform uint32_t lane = indices[k] % programCount;
        if (programIndex == lane && catcher >= 0.f) {
            if (slot < lightSlots && whole > 0.f) {
                const varying Color r = rays[slot].mRadiance;
                const varying float part = luminance(r) / whole;
                varying Color share;
                share.r = total.r > 0.f ? r.r / total.r : part;
                share.g = total.g > 0.f ? r.g / total.g : part;
                share.b = total.b > 0.f ? r.b / total.b : part;
                rays[slot].mRadiance = shown * share * catcher;
                if (matte) {
                    rays[slot].mModoAlpha = -catcher * pathPixelWeight * part;
                    modoCatcherLpe(pbrTls, rays[slot], bgLpe, rays[slot].mRadiance);
                }
            } else {
                rays[slot].mRadiance = sBlack;
                if (matte) {
                    const varying Color none = sBlack;
                    modoCatcherLpe(pbrTls, rays[slot], -1, none);
                }
            }
        }
    }
}

void
computeRadianceBsdfMultiSampler(const uniform PathIntegrator * uniform this,
'''

SHARE_CALL = '''    // Modo: a shadow catcher seen by the camera: its shadow rays carry its emission's shares (tools/port_shadow_catcher.py).
    if (any(modoCatcher >= 0.f)) {
        varying Color modoTotal = sBlack;
        modoCatcherTotal(occlRays, occlRayIndices, numOcclRaysFilled, lightSetSampleCount, modoTotal);
        modoCatcherTotal(presenceShadowsRays, presenceShadowsRayIndices, numPresenceShadowsRaysFilled,
                         lightSetSampleCount, modoTotal);
        // The alpha a matte's unshadowed samples take back: by the pixel weight at the camera, none past it.
        const varying float modoAlphaScale = ray.ext.depth == 0 ? pv.pathPixelWeight : 0.f;
        modoCatcherShare(pbrTls, occlRays, occlRayIndices, numOcclRaysFilled, lightSetSampleCount, modoCatcher,
                         modoShown, modoTotal, modoMatte, modoAlphaScale, modoBgLpe);
        modoCatcherShare(pbrTls, presenceShadowsRays, presenceShadowsRayIndices, numPresenceShadowsRaysFilled,
                         lightSetSampleCount, modoCatcher, modoShown, modoTotal, modoMatte, modoAlphaScale,
                         modoBgLpe);
    }

    MNRY_ASSERT(numOcclRaysFilled <= numOcclRaysToAlloc * VLEN);
'''

CPP_DEFINITION = '''// Modo: whether a hit's material is a shadow catcher, its strength (-1 for none) and whether it is a matte
// (tools/port_shadow_catcher.py).
void
CPP_modoShadowCatcher(int64_t material, float *strength, int *matte)
{
    *strength = -1.f;
    *matte = 0;
    const auto *held = reinterpret_cast<const scene_rdl2::rdl2::Material *>(material);
    if (!held || !modoShadowCatcher() || !held->getModoShadowCatcher()) {
        return;
    }
    *strength = scene_rdl2::math::clamp(held->getModoShadowStrength(), 0.f, 1.f);
    *matte = held->getModoShadowMatte() ? 1 : 0;
}

} // namespace pbr
} // namespace moonray
'''

EDITS = {
    RDL2 / 'Material.h': [
        ('''    static AttributeKey<Bool> sRecordRefractedCryptomatte;
''', '''    static AttributeKey<Bool> sRecordRefractedCryptomatte;
    // Modo: shadow catchers (tools/port_shadow_catcher.py)
    static AttributeKey<Bool> sModoShadowCatcher;
    static AttributeKey<Float> sModoShadowStrength;
    static AttributeKey<Bool> sModoShadowMatte;
''', 1),
        ('''    finline bool getRecordRefractedCryptomatte() const
    {
        return get(sRecordRefractedCryptomatte);
    }
''', '''    finline bool getRecordRefractedCryptomatte() const
    {
        return get(sRecordRefractedCryptomatte);
    }

    // Modo: shadow catchers (tools/port_shadow_catcher.py)
    finline bool getModoShadowCatcher() const { return get(sModoShadowCatcher); }
    finline float getModoShadowStrength() const { return get(sModoShadowStrength); }
    finline bool getModoShadowMatte() const { return get(sModoShadowMatte); }
''', 1),
    ],
    RDL2 / 'Material.cc': [
        ('''AttributeKey<Bool> Material::sRecordRefractedCryptomatte;
''', '''AttributeKey<Bool> Material::sRecordRefractedCryptomatte;
AttributeKey<Bool> Material::sModoShadowCatcher;
AttributeKey<Float> Material::sModoShadowStrength;
AttributeKey<Bool> Material::sModoShadowMatte;
''', 1),
        ('''    return interface | INTERFACE_MATERIAL;
''', '''    // Modo: shadow catchers (tools/port_shadow_catcher.py)
    sModoShadowCatcher = sceneClass.declareAttribute<Bool>("modo_shadow_catcher", false);
    sceneClass.setMetadata(sModoShadowCatcher, "comment", "Modo: the surface is a shadow catcher. The camera sees what "
        "it wears (its emission) darkened where the scene shades it; other rays see it unlit.");
    sModoShadowStrength = sceneClass.declareAttribute<Float>("modo_shadow_strength", 1.0f);
    sceneClass.setMetadata(sModoShadowStrength, "comment", "Modo: how dark a shadow catcher's shadows are, 0 to 1.");
    sModoShadowMatte = sceneClass.declareAttribute<Bool>("modo_shadow_matte", false);
    sceneClass.setMetadata(sModoShadowMatte, "comment", "Modo: a shadow catcher shows no colour to the camera, its "
        "alpha holding the shadows alone.");

    return interface | INTERFACE_MATERIAL;
''', 1),
    ],
    RENDERING / 'pbr/Types.hh': [
        ('''#define BUNDLED_OCCL_RAY_MEMBERS_PAD (60+60) /*Alignment: 128, Total size: 136, Padded size: 256*/
''', '''#define BUNDLED_OCCL_RAY_MEMBERS_PAD (60+56) /*Alignment: 128, Total size: 140, Padded size: 256 (Modo: mModoAlpha)*/
''', 1),
        ('''#define BUNDLED_OCCL_RAY_MEMBERS_PAD  56 /*Alignment: 64, Total size: 136, Padded size: 192*/
''', '''#define BUNDLED_OCCL_RAY_MEMBERS_PAD  52 /*Alignment: 64, Total size: 140, Padded size: 192 (Modo: mModoAlpha)*/
''', 1),
        ('''    HVD_MEMBER(float, mLsmpVisibility);                             /*  136   */\\
''', '''    HVD_MEMBER(float, mLsmpVisibility);                             /*  136   */\\
    /* Modo: a shadow catcher matte's alpha (tools/port_shadow_catcher.py) */           \\
    HVD_MEMBER(float, mModoAlpha);                                  /*  140   */\\
''', 1),
        ('''    HVD_VALIDATE(BundledOcclRay, mLsmpVisibility);          \\
''', '''    HVD_VALIDATE(BundledOcclRay, mLsmpVisibility);          \\
    HVD_VALIDATE(BundledOcclRay, mModoAlpha);               \\
''', 1),
    ],
    RENDERING / 'pbr/Types.ispc': [
        ('''    this->mLsmpVisibility = lsmpVisibility;
''', '''    this->mLsmpVisibility = lsmpVisibility;
    this->mModoAlpha = 0.f;     // Modo: a shadow catcher matte's (tools/port_shadow_catcher.py)
''', 1),
    ],
    RENDERING / 'pbr/handlers/RayHandlerUtils.cc': [
        ('''                                 radiance.b,
                                 0.f);
''', '''                                 radiance.b,
                                 occlRay.mModoAlpha); // Modo: 0 but for a shadow catcher matte (tools/port_shadow_catcher.py)
''', 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegratorUtil.h': [
        ('''bool CPP_isIntegratorAccumulatorRunning(pbr::TLState *pbrTls);
''', '''bool CPP_isIntegratorAccumulatorRunning(pbr::TLState *pbrTls);

// Modo: shadow catchers (tools/port_shadow_catcher.py)
void CPP_modoShadowCatcher(int64_t material, float *strength, int *matte);
''', 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegratorUtil.cc': [
        ('''} // namespace pbr
} // namespace moonray
''', CPP_DEFINITION, 1),
        ('''namespace moonray {
namespace pbr {
''', '''#include <moonray/rendering/pbr/core/ModoShadowCatcher.h>
#include <scene_rdl2/scene/rdl2/Material.h>

namespace moonray {
namespace pbr {
''', 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegrator.cc': [
        ('''#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
''', '''#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
#include <moonray/rendering/pbr/core/ModoShadowCatcher.h>
''', 1),
        (RECURSE_OLD, RECURSE_NEW, 1),
        (RECURSE_SAMPLE_OLD, RECURSE_SAMPLE_NEW, 1),
        (PRIMARY_OLD, PRIMARY_NEW, 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegratorMultiSampler.cc': [
        ('''#include <moonray/rendering/pbr/core/Cryptomatte.h>
''', '''#include <moonray/rendering/pbr/core/Cryptomatte.h>
#include <moonray/rendering/pbr/core/ModoShadowCatcher.h>
''', 1),
        (TALLY_TOTAL_OLD, TALLY_TOTAL_NEW, 1),
        (TALLY_FALLOFF_OLD, TALLY_FALLOFF_NEW, 1),
        (TALLY_LIT_OLD, TALLY_LIT_NEW, 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegrator.isph': [
        ('''                                     varying uint32_t &sequenceID,
                                     const varying Rdl2LightSetList * uniform parentLobeLightSets);
''', '''                                     varying uint32_t &sequenceID,
                                     const varying Rdl2LightSetList * uniform parentLobeLightSets,
                                     const varying float modoCatcher,
                                     const varying Color &modoShown,
                                     const varying bool modoMatte,
                                     const varying int modoBgLpe);

// Modo: shadow catchers (tools/port_shadow_catcher.py)
extern "C" void
CPP_modoShadowCatcher(uniform int64 material, uniform float * uniform strength, uniform int * uniform matte);
''', 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegratorMultiSampler.ispc': [
        ('''void
computeRadianceBsdfMultiSampler(const uniform PathIntegrator * uniform this,
''', SHARE_HELPERS, 1),
        ('''                                varying uint32_t &sequenceID,
                                const varying Rdl2LightSetList * uniform parentLobeLightSets)
{
''', '''                                varying uint32_t &sequenceID,
                                const varying Rdl2LightSetList * uniform parentLobeLightSets,
                                const varying float modoCatcher,
                                const varying Color &modoShown,
                                const varying bool modoMatte,
                                const varying int modoBgLpe)
{
''', 1),
        ('''    MNRY_ASSERT(numOcclRaysFilled <= numOcclRaysToAlloc * VLEN);
''', SHARE_CALL, 1),
        ('''void addDirectVisibleLightSampleContributionsBundled(       uniform PbrTLState *     uniform pbrTls,
''', MATTE_AT_HELPER, 1),
        (KEEP_OLD, KEEP_NEW, 1),
    ],
    RENDERING / 'pbr/integrator/PathIntegratorBundled.ispc': [
        ('''extern "C" void
CPP_addRadianceQueueEntries(''', CATCHER_HELPER.lstrip('\n') + '''
extern "C" void
CPP_addRadianceQueueEntries(''', 1),
        ('''        //---------------------------------------------------------------------
        // Early out if we don't have any Bsdf lobes nor Bssrdf
''', CATCHER_BLOCK, 1),
        ('''                                        slice,
                                        doIndirect,
                                        indirectFlags,''', '''                                        slice,
                                        doIndirect && !(modoCatcher >= 0.f),
                                        indirectFlags,''', 1),
        ('''                                        sequenceID,
                                        parentLobeLightSets);
    }
''', '''                                        sequenceID,
                                        parentLobeLightSets,
                                        modoCatcher,
                                        modoShown,
                                        modoMatte,
                                        modoBgLpe);
    }
''', 1),
        ('''#include <moonray/rendering/pbr/core/Aov.isph>
''', '''#include <moonray/rendering/pbr/core/Aov.isph>
#include <moonray/rendering/lpe/StateMachine.isph>   // Modo: tools/port_shadow_catcher.py
#include "PathIntegratorUtil.isph"                    // Modo: lobeTypeToRayMask (tools/port_shadow_catcher.py)
''', 1),
        ('''void
integrateBundled( const uniform PathIntegrator * uniform this,
''', BACKGROUND_HELPER, 1),
    ],
}


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
            raise RuntimeError('Shadow catcher anchor missing or ambiguous in %s: %r' % (name, old[:80]))
    return text


def main():
    if not HEADER.exists() or HEADER.read_text(encoding='utf-8') != HEADER_TEXT:
        HEADER.write_text(HEADER_TEXT, encoding='utf-8')
        print('wrote', HEADER.relative_to(MOONRAY))
    for source, edits in EDITS.items():
        text = source.read_bytes().decode('utf-8')
        patched = patch_text(source.name, text, edits)
        if patched != text:
            source.write_bytes(patched.encode('utf-8'))
            print('patched', source.relative_to(MOONRAY))
        else:
            print('already in', source.relative_to(MOONRAY))


if __name__ == '__main__':
    main()
