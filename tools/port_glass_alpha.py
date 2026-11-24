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
directly does; the kit's EXR step takes both out of it (environment_background, Premultiplied OpenEXR alpha)."""
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
