"""Fog in a camera ray's alpha past a see-through (presence) surface.

MoonRay's alpha forgets the fog in front of a partly see-through surface. In scalar mode, computeRadiancePresence sets
the transparency to (1 - presence) * what shows through behind the surface, where its own cutout branch just above
multiplies by the volume's transmittance alpha as well. In vector and XPU modes a camera ray's alpha is added up entry
by entry; a surface after fog counts its weight in full and the fog's opacity is counted only for a ray that misses.
So fog of 0.60 in front of a pane of presence 0.4 against the sky gives an alpha of 0.40, where the two hide 0.76.

Only when MoonRay is started with MOONRAY_MODO_FOG_ALPHA=1 (the plugin's preference):

1. Scalar: the presence transparency is multiplied by the transmittance alpha of the volumes before the surface.
2. Vector and XPU: each camera ray carries, in two new PathVertex floats, how much of what lies behind the volumes it
   has passed shows through (modoFogFront, 1 at the camera) and the opacity of those volumes not yet counted
   (modoFogPending, 0 at the camera). After a camera ray's volumes are marched, the volumes' opacity at the ray's pixel
   weight is added to what is pending and what shows through is reduced. A camera ray's alpha entry is then what is
   pending plus MoonRay's own alpha for it scaled by what shows through; a ray that misses, or hits a light or
   geometry with no material, counts what is pending alone. A presence continuation takes the pending opacity only
   when the surface it leaves was not counted (presence 0). A cutout counts what is pending and nothing behind it.
   RayState's ISPC padding gives up the 8 bytes.

Without the variable both floats stay 1 and 0, and MoonRay's alpha is its own."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering'

HEADER = 'pbr/core/ModoFogAlpha.h'
HEADER_TEXT = '''// Modo: fog in a camera ray's alpha past a see-through surface (tools/port_fog_alpha.py).
#pragma once

#include <cstdlib>

namespace moonray {
namespace pbr {

/// True when MoonRay was started with MOONRAY_MODO_FOG_ALPHA=1. Read once.
inline bool modoFogAlpha()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_FOG_ALPHA");
        return value && value[0] == '1';
    }();
    return on;
}

} // namespace pbr
} // namespace moonray
'''

AFTER_VOLUME_OLD = '''        rs.mVolTm = vt.mTransmittanceMin;
        rs.mVolumeSurfaceT = volumeSurfaceT;
'''
AFTER_VOLUME_NEW = '''        rs.mVolTm = vt.mTransmittanceMin;
        rs.mVolumeSurfaceT = volumeSurfaceT;
        // Modo: the volumes a camera ray passed are counted in its alpha once, and what lies behind them as much as
        // shows through (tools/port_fog_alpha.py).
        if (modoFogAlpha() && ray.getDepth() == 0) {
            const float shown = rs.mVolHit ? reduceTransparency(vt.mTransmittanceAlpha) : 1.f;
            pv.modoFogPending += pv.pathPixelWeight * pv.modoFogFront * (1.f - shown);
            pv.modoFogFront *= shown;
        }
'''

HANDLER_EDITS = [
    ('''#include <moonray/rendering/pbr/core/PbrTLState.h>
''', '''#include <moonray/rendering/pbr/core/PbrTLState.h>
#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
''', 1),
    (AFTER_VOLUME_OLD, AFTER_VOLUME_NEW, 1),
    ('''                        rs.mPathVertex.pathPixelWeight * (1.0f - reduceTransparency(rs.mVolTalpha)) : 0.f;
''', '''                        (modoFogAlpha() ? rs.mPathVertex.modoFogPending :
                         rs.mPathVertex.pathPixelWeight * (1.0f - reduceTransparency(rs.mVolTalpha))) : 0.f;
''', 1),
    ('''                // add in any volume radiance
''', '''                // Modo: a camera ray that hits nothing counts the volumes it passed, as much as shows through
                // those before them (tools/port_fog_alpha.py).
                if (modoFogAlpha() && rs->mRay.getDepth() == 0) {
                    alpha = rs->mPathVertex.modoFogPending;
                }

                // add in any volume radiance
''', 1),
]

EDITS = {
    'pbr/core/RayState.hh': [
        ('''    HVD_MEMBER(int, lobeType)                                               /*   84  */
''', '''    HVD_MEMBER(int, lobeType);                                              /*   84  */\\
    /* Modo: fog in a camera ray's alpha (tools/port_fog_alpha.py) */                  \\
    HVD_MEMBER(float, modoFogFront);                                        /*   88  */\\
    HVD_MEMBER(float, modoFogPending)                                       /*   92  */
''', 1),
        ('''    HVD_VALIDATE(PathVertex, lobeType);             \\
''', '''    HVD_VALIDATE(PathVertex, lobeType);             \\
    HVD_VALIDATE(PathVertex, modoFogFront);         \\
    HVD_VALIDATE(PathVertex, modoFogPending);       \\
''', 1),
        ('''#define RAY_STATE_MEMBERS_PAD   76
''', '''#define RAY_STATE_MEMBERS_PAD   68 /* Modo: 8 bytes to PathVertex (tools/port_fog_alpha.py) */
''', 1),
        ('''#define RAY_STATE_MEMBERS_PAD   28
''', '''#define RAY_STATE_MEMBERS_PAD   20 /* Modo: 8 bytes to PathVertex (tools/port_fog_alpha.py) */
''', 1),
    ],
    'pbr/integrator/PathIntegrator.cc': [
        ('''    pv.accumOpacity = 0;
''', '''    pv.accumOpacity = 0;
    pv.modoFogFront = 1.f;
    pv.modoFogPending = 0.f;
''', 1),
        ('''#include "ModoCryptoVolumes.h"
''', '''#include "ModoCryptoVolumes.h"
#include <moonray/rendering/pbr/core/ModoFogAlpha.h>
''', 1),
        ('''    transparency = (1 - presence) * presenceTransparency;
''', '''    // Modo: the volumes before this surface hide what is behind it too, as MoonRay's cutout above has it
    // (tools/port_fog_alpha.py).
    transparency = (modoFogAlpha() ? reduceTransparency(vt.mTransmittanceAlpha) : 1.f) *
                   (1 - presence) * presenceTransparency;
''', 1),
    ],
    'pbr/handlers/RayHandlers.cc': HANDLER_EDITS,
    'pbr/handlers/XPURayHandlers.cc': HANDLER_EDITS,
    'pbr/handlers/ShadeBundleHandler.cc': [
        ('''                        presenceRay->mPathVertex.totalPresence = totalPresence;
''', '''                        presenceRay->mPathVertex.totalPresence = totalPresence;
                        // Modo: the fog's opacity not yet counted goes with the continuation only when this surface,
                        // which counts it, is not shaded (tools/port_fog_alpha.py).
                        if (presences[i] > 0.f) {
                            presenceRay->mPathVertex.modoFogPending = 0.f;
                        }
''', 1),
    ],
    'pbr/integrator/PathIntegratorBundled.ispc': [
        ('''    const varying float alpha = (depth ? 0.f : pathPixelWeight) - transparency * pathPixelWeight;
''', '''    varying float alpha = (depth ? 0.f : pathPixelWeight) - transparency * pathPixelWeight;
    // Modo: a camera ray's alpha counts the volumes it passed once, and the rest as much as shows through them
    // (tools/port_fog_alpha.py); without MOONRAY_MODO_FOG_ALPHA these are 0 and 1.
    if (depth == 0) {
        alpha = rayState.mPathVertex.modoFogPending + rayState.mPathVertex.modoFogFront * alpha;
    }
''', 1),
        ('''                transparency = reduceTransparency(rs->mVolTalpha);
''', '''                transparency = reduceTransparency(rs->mVolTalpha);
                // Modo: with the volumes counted as pending (tools/port_fog_alpha.py), a cutout adds nothing more.
                if (pv.modoFogFront < 1.f || pv.modoFogPending > 0.f) {
                    transparency = 1.f;
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
            raise RuntimeError('Fog alpha anchor missing or ambiguous in %s: %r' % (name, old[:70]))
    return text


def main():
    header = RENDERING / HEADER
    if not header.exists() or header.read_text(encoding='utf-8') != HEADER_TEXT:
        header.write_text(HEADER_TEXT, encoding='utf-8')
        print('wrote', HEADER)
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
