"""Four of the plugin's changes to MoonRay, each behind a switch of its own (MoonRay Source Overrides in the plugin's
preferences, each on by default); off, MoonRay behaves as its source does.

1. MOONRAY_MODO_USD_SPECULAR: UsdPreviewSurface's specular workflow reflects its specularColor, by Schlick's
   Fresnel. MoonRay's source gives that workflow no highlight at all ("We can't support this until we implement
   Schlick fresnel").
2. MOONRAY_MODO_OPAQUE_ALPHA: an image with no alpha channel reads as opaque in a texture's alpha. MoonRay leaves the
   missing channel at OpenImageIO's fill, 0.
3. MOONRAY_MODO_TRANSMISSION_ROUGHNESS (moonshine): DwaBase's independent transmission roughness is kept when the
   surface itself is mirror smooth. MoonRay's source then makes the transmission mirror sharp as well.
4. MOONRAY_MODO_AUTO_XPU: the Auto execution mode starts with XPU, falling back where the scene has what XPU does not
   support (upstream's own commented branch). MoonRay's source starts Auto in vector mode.

Each switch is read once, from MoonRay's environment, in the file that uses it; the vector (ISPC) code is told as its
library loads. Rerunning this script leaves edited files alone."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOONRAY = ROOT / 'upstream/openmoonray/moonray/moonray'
MOONSHINE = ROOT / 'upstream/openmoonray/moonray/moonshine'


def switch_function(name, variable, comment):
    return '''// Modo: %s (tools/port_source_switches.py). True when MoonRay was started with %s=1; read once.
inline bool %s()
{
    static const bool on = [] {
        const char *value = std::getenv("%s");
        return value && value[0] == '1';
    }();
    return on;
}
''' % (comment, variable, name, variable)


EDITS = {
    # 1. UsdPreviewSurface's specular workflow.
    MOONRAY / 'dso/material/UsdPreviewSurface/UsdPreviewSurface.cc': [
        ('''#include <moonray/rendering/shading/MaterialApi.h>
''', '''#include <moonray/rendering/shading/MaterialApi.h>

#include <cstdlib>
''', 1),
        ('''namespace {
''', '''namespace {

''' + switch_function('modoUsdSpecular', 'MOONRAY_MODO_USD_SPECULAR', "UsdPreviewSurface's specular workflow reflects its specularColor") + '''
// The vector code is told once, as the material's library loads.
const bool sModoUsdSpecularSet = (ispc::UsdPreviewSurface_setModoSpecular(modoUsdSpecular()), true);
''', 1),
        ('''    if (specularWorkflow == ispc::SPECULAR_WORKFLOW_SPECULAR) {
        const auto value = evalColor(me, attrSpecularColor, tls, state);''', '''    if (specularWorkflow == ispc::SPECULAR_WORKFLOW_SPECULAR) {
        // Modo: with MOONRAY_MODO_USD_SPECULAR the specular colour is reflected by Schlick's Fresnel. Off, as
        // MoonRay's source: we can't support this until we implement Schlick fresnel so do nothing for now.
        if (modoUsdSpecular()) {
        const auto value = evalColor(me, attrSpecularColor, tls, state);''', 1),
        ('''                                            scene_rdl2::math::isZero(roughness), aovSpecular);
        }
    } else { // SPECULAR_WORKFLOW_METALNESS''', '''                                            scene_rdl2::math::isZero(roughness), aovSpecular);
        }
        }
    } else { // SPECULAR_WORKFLOW_METALNESS''', 1),
    ],
    MOONRAY / 'dso/material/UsdPreviewSurface/UsdPreviewSurface.ispc': [
        ('''#include <moonray/rendering/shading/ispc/MaterialApi.isph>
''', '''#include <moonray/rendering/shading/ispc/MaterialApi.isph>

// Modo: the specular workflow reflects its specularColor (MOONRAY_MODO_USD_SPECULAR, tools/port_source_switches.py).
uniform bool gModoUsdSpecular = false;

export void
UsdPreviewSurface_setModoSpecular(uniform bool on)
{
    gModoUsdSpecular = on;
}
''', 1),
        ('''    if (specularWorkflow == SPECULAR_WORKFLOW_SPECULAR) {
        const Color value = evalAttrSpecularColor(me, tls, state);''', '''    if (specularWorkflow == SPECULAR_WORKFLOW_SPECULAR) {
        // Modo: off, as MoonRay's source: we can't support this until we implement Schlick fresnel so do nothing.
        if (gModoUsdSpecular) {
        const Color value = evalAttrSpecularColor(me, tls, state);''', 1),
        ('''                BsdfBuilder_addSchlickReflection(bsdfBuilder, N, specular, roughness, false, aovSpecular);
            }
        }
    } else { // SPECULAR_WORKFLOW_METALNESS''', '''                BsdfBuilder_addSchlickReflection(bsdfBuilder, N, specular, roughness, false, aovSpecular);
            }
        }
        }
    } else { // SPECULAR_WORKFLOW_METALNESS''', 1),
    ],
    # 2. A texture's missing alpha channel.
    MOONRAY / 'lib/rendering/shading/BasicTexture.cc': [
        ('''#include <OpenImageIO/texture.h>
''', '''#include <OpenImageIO/texture.h>

#include <cstdlib>

namespace {
''' + switch_function('modoOpaqueAlpha', 'MOONRAY_MODO_OPAQUE_ALPHA', 'an image with no alpha channel reads as opaque') + '''}
''', 1),
        ('''            // TextureSampler expands grayscale to RGB; a missing fourth channel
            // must be opaque, matching ImageMap's documented alpha-only behavior.
            mTextureOpt[i].fill = 1.0f;''', '''            // Modo: with MOONRAY_MODO_OPAQUE_ALPHA, a missing fourth channel is opaque, matching ImageMap's
            // documented alpha-only behaviour (TextureSampler expands grayscale to RGB). Off, as MoonRay's source:
            // OpenImageIO's fill, 0.
            if (modoOpaqueAlpha()) {
                mTextureOpt[i].fill = 1.0f;
            }''', 1),
    ],
    # 4. The Auto execution mode.
    MOONRAY / 'lib/rendering/rndr/RenderContext.cc': [
        ('''            // MoonRayForModo: Auto prioritizes feature support, then XPU > Vector > Scalar.
            executionModeString = "Executing an XPU render since execution mode was set to auto.";
            allowUnsupportedXPUFeatures = false;
            mExecutionMode = ExecutionMode::XPU;''', '''            // Modo: with MOONRAY_MODO_AUTO_XPU, Auto starts with XPU (upstream's own commented branch), falling back
            // where the scene has what XPU does not support: XPU > Vector > Scalar. Off, as MoonRay's source.
            static const bool modoAutoXpu = [] {
                const char *value = std::getenv("MOONRAY_MODO_AUTO_XPU");
                return value && value[0] == '1';
            }();
            if (modoAutoXpu) {
                executionModeString = "Executing an XPU render since execution mode was set to auto.";
                allowUnsupportedXPUFeatures = false; // want to fall back if unsupported
                mExecutionMode = ExecutionMode::XPU;
            } else {
                // Uncomment the following to have AUTO mode start with XPU:
                //   executionModeString = "Executing an XPU render since execution mode was set to auto.";
                //   allowUnsupportedXPUFeatures = false; // want to fall back if unsupported
                //   mExecutionMode = ExecutionMode::XPU;
                // If there is an error setting up the GPU, we will fall back to vector mode
                // in GeometryManager::updateGPUAccelerator().

                // AUTO mode starts with vector mode
                executionModeString = "Executing a vectorized render since execution mode was set to auto.";
                mExecutionMode = ExecutionMode::VECTORIZED;
            }''', 1),
    ],
    # 3. DwaBase's transmission roughness under a mirror smooth surface.
    MOONSHINE / 'lib/material/dwabase/DwaBaseLayerable.cc': [
        ('''namespace {
''', '''namespace {

''' + switch_function('modoTransmissionRoughness', 'MOONRAY_MODO_TRANSMISSION_ROUGHNESS',
                      "DwaBase's independent transmission roughness kept under a mirror smooth surface") + '''
// The vector code is told once, as the library loads.
const bool sModoTransmissionRoughnessSet = (ispc::DwaBaseLayerable_setModoTransmissionRoughness(modoTransmissionRoughness()), true);
''', 1),
        ('''        if (roughnessClamped < scene_rdl2::math::sEpsilon &&
            (scene_rdl2::math::isZero(transmissionWeight) || transmissionRoughnessClamped < scene_rdl2::math::sEpsilon)) {''',
         '''        // Modo: with MOONRAY_MODO_TRANSMISSION_ROUGHNESS, a rough transmission keeps its roughness under a mirror smooth
        // surface. Off, as MoonRay's source: the surface's roughness alone decides, and the transmission is mirror sharp.
        if (roughnessClamped < scene_rdl2::math::sEpsilon &&
            (!modoTransmissionRoughness() ||
             scene_rdl2::math::isZero(transmissionWeight) || transmissionRoughnessClamped < scene_rdl2::math::sEpsilon)) {''', 1),
    ],
    MOONSHINE / 'lib/material/dwabase/ispc/DwaBaseLayerable.ispc': [
        ('''#include "DwaBaseLayerable.isph"
''', '''#include "DwaBaseLayerable.isph"

// Modo: DwaBase's transmission roughness kept under a mirror smooth surface (MOONRAY_MODO_TRANSMISSION_ROUGHNESS,
// tools/port_source_switches.py).
uniform bool gModoTransmissionRoughness = false;

export void
DwaBaseLayerable_setModoTransmissionRoughness(uniform bool on)
{
    gModoTransmissionRoughness = on;
}
''', 1),
        ('''        if (roughnessClamped < sEpsilon &&
            (isZero(transmissionWeight) || transmissionRoughnessClamped < sEpsilon)) {''',
         '''        if (roughnessClamped < sEpsilon &&
            (!gModoTransmissionRoughness || isZero(transmissionWeight) || transmissionRoughnessClamped < sEpsilon)) {''', 1),
    ],
}

MARK = 'tools/port_source_switches.py'
for path, edits in EDITS.items():
    text = path.read_text(encoding='utf-8')
    if MARK in text or 'MOONRAY_MODO_AUTO_XPU' in text:
        print('already edited:', path.relative_to(ROOT))
        continue
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            raise SystemExit('%s: expected %d of %r, found %d' % (path.relative_to(ROOT), count, old[:70], found))
        text = text.replace(old, new)
    path.write_text(text, encoding='utf-8', newline='\n')
    print('edited:', path.relative_to(ROOT))
