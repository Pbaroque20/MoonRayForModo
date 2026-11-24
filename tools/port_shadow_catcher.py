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
3. Matte (modo_shadow_matte, the Backplate's "backplate in the render" off): the camera ray adds no colour and an alpha
   of strength; each unshadowed light sample takes its share back off (BundledOcclRay.mModoAlpha, which the occlusion
   handlers write as the result's alpha). The alpha then holds the shadows alone, to lay over the photo.
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
    // outright, the rest as much as its light samples are not shadowed; as a matte, no colour and the shadows in alpha.
    if (modoShadowCatcher() && material->getModoShadowCatcher()) {
        ModoCatcherTally &tally = modoCatcherTally();
        tally = ModoCatcherTally();
        tally.on = true;
        computeRadianceBsdfMultiSampler(pbrTls, sp, pv, ray, isect, *bsdf, slice,
            false, shading::BsdfLobe::Type::NONE, newPriorityList, newPriorityListCount, activeLightSet, normalPtr,
            rayEpsilon, shadowRayEpsilon, ssAov, sequenceID, aovs, cryptomatteFlags,
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
        if (material->getModoShadowMatte()) {
            transparency = 1.f - strength * (1.f - part);
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
RECURSE_NEW = '''    // Modo: a shadow catcher seen past the camera is what it wears (its emission), unlit (tools/port_shadow_catcher.py).
    if (modoShadowCatcher() && material->getModoShadowCatcher()) {
        return radiance;
    }

    shading::BsdfLobe::Type indirectFlags = shading::BsdfLobe::Type::NONE;
    if ((mBsdfSamples > 0) && (ray.getDepth() < mMaxDepth) && lobe) {
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
        // no colour and an alpha of strength, which the unshadowed samples take back off.
        varying float modoCatcher = -1.f;
        varying bool modoMatte = false;
        modoShadowCatcherOf(isect, modoCatcher, modoMatte);
        varying Color modoShown = sBlack;
        if (modoCatcher >= 0.f) {
            if (rayDepth > 0) {
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
                transparency = 1.f - modoCatcher;
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

SHARE_HELPERS = '''// Modo: a shadow catcher seen by the camera (tools/port_shadow_catcher.py). Its light samples' shadow rays (slots below
// lightSlots; above them, its bsdf samples') carry, between them, what it would gather unshadowed (modoCatcherTotal);
// each is given instead the catcher's emission x strength x its share of that, so that unshadowed they add up to the
// emission and a blocked one leaves its share out. As a matte, no colour, and its share of the alpha taken back off.
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

static void
modoCatcherShare(varying BundledOcclRay * uniform rays, const uniform uint32_t * uniform indices,
                 uniform uint32_t count, uniform int lightSlots, const varying float catcher,
                 const varying Color &shown, const varying Color &total, const varying bool matte,
                 const varying float pathPixelWeight)
{
    const varying float whole = luminance(total);
    for (uniform uint32_t k = 0; k < count; ++k) {
        const uniform uint32_t slot = indices[k] / programCount;
        const uniform uint32_t lane = indices[k] % programCount;
        if (programIndex == lane && catcher >= 0.f) {
            if (slot < lightSlots && whole > 0.f) {
                const varying Color r = rays[slot].mRadiance;
                const varying float part = luminance(r) / whole;
                if (matte) {
                    rays[slot].mModoAlpha = -catcher * pathPixelWeight * part;
                    rays[slot].mRadiance = sBlack;
                } else {
                    varying Color share;
                    share.r = total.r > 0.f ? r.r / total.r : part;
                    share.g = total.g > 0.f ? r.g / total.g : part;
                    share.b = total.b > 0.f ? r.b / total.b : part;
                    rays[slot].mRadiance = shown * share * catcher;
                }
            } else {
                rays[slot].mRadiance = sBlack;
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
        modoCatcherShare(occlRays, occlRayIndices, numOcclRaysFilled, lightSetSampleCount, modoCatcher, modoShown,
                         modoTotal, modoMatte, pv.pathPixelWeight);
        modoCatcherShare(presenceShadowsRays, presenceShadowsRayIndices, numPresenceShadowsRaysFilled,
                         lightSetSampleCount, modoCatcher, modoShown, modoTotal, modoMatte, pv.pathPixelWeight);
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
                                     const varying bool modoMatte);

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
                                const varying bool modoMatte)
{
''', 1),
        ('''    MNRY_ASSERT(numOcclRaysFilled <= numOcclRaysToAlloc * VLEN);
''', SHARE_CALL, 1),
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
                                        modoMatte);
    }
''', 1),
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
