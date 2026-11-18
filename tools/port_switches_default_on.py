"""The MoonRay Source Overrides on when their variable is not set.

Each MoonRay Source Override (tools/port_*.py) is read once from MoonRay's environment. The kit always sets every one,
to 1 or 0, from its preference (native.environment), which is on by default. A moonray.exe or denoise.exe started by
hand, a headless render or a farm's, has none of them, and they used to be read as on only when set to 1: such a render
was MoonRay as its source has it, not as Modo renders it (on the 9Spheres test scene the marble floor came out flat
white, without MOONRAY_MODO_OPAQUE_ALPHA). Now each is off only when set to 0; unset, it is on, as the preference is.

The port tools write the new reading themselves. This script turns the old one into it in an upstream tree they patched
before, and in patches/native-windows/*.patch (one line for one, so every hunk keeps its shape), and updates the
patches' checksums in sources.json. On such a tree, run it before running the port tools again: they know an edit by
its new text. Rerunning it changes nothing."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'upstream/openmoonray/moonray'
PATCHES = ROOT / 'patches/native-windows'

SWITCHES = ('TOON_TERMINATOR', 'TOON_ALBEDO', 'DENOISE_CLEAN_GUIDES', 'CRYPTO_VOLUMES', 'CRYPTO_ONCE', 'FOG_ALPHA',
            'CAMERA_LIGHT_LPE', 'MIRRORED_MESHES', 'SCALAR_EMISSION', 'DSO_SEARCH', 'USD_SPECULAR', 'OPAQUE_ALPHA',
            'TRANSMISSION_ROUGHNESS', 'AUTO_XPU')
VARIABLE = '(MOONRAY_MODO_(?:%s))' % '|'.join(SWITCHES)

# Where MoonRay reads each switch, and how many times.
READS = {
    'mcrt_denoise/lib/denoiser/OIDNDenoiserImpl.h': 1,
    'moonray/dso/material/UsdPreviewSurface/UsdPreviewSurface.cc': 1,
    'moonray/lib/rendering/geom/prim/OpenSubdivMesh.cc': 1,
    'moonray/lib/rendering/geom/prim/PolyMesh.cc': 1,
    'moonray/lib/rendering/geom/prim/VdbVolume.cc': 1,
    'moonray/lib/rendering/pbr/core/ModoCryptoOnce.h': 1,
    'moonray/lib/rendering/pbr/core/ModoFogAlpha.h': 1,
    'moonray/lib/rendering/pbr/handlers/RayHandlers.cc': 1,
    'moonray/lib/rendering/pbr/handlers/XPURayHandlers.cc': 1,
    'moonray/lib/rendering/pbr/integrator/ModoCryptoVolumes.h': 1,
    'moonray/lib/rendering/rndr/RenderContext.cc': 1,
    'moonray/lib/rendering/shading/BasicTexture.cc': 1,
    'moonray/lib/rendering/shading/ModoToonTerminator.h': 2,
    'moonray/lib/rendering/shading/UdimTexture.cc': 1,
    'moonshine/lib/material/dwabase/DwaBaseLayerable.cc': 1,
    'scene_rdl2/lib/scene/rdl2/DsoFinder.cc': 1,
    'scene_rdl2/lib/scene/rdl2/SceneContext.cc': 1,
}
# And where only a comment tells a switch's rule.
COMMENTS = ('moonray/lib/rendering/pbr/integrator/PathIntegratorBundled.ispc',)

# Each a line for a line; in a patch, the line may start with the '+' of an added line.
OLD_READ = re.compile(r'''(getenv\("%s"\);\r?\n\+?[ \t]*)return value && value\[0\] == '1';''' % VARIABLE)
NEW_READ = re.compile(r'''getenv\("%s"\);\r?\n\+?[ \t]*return !value \|\| value\[0\] != '0';''' % VARIABLE)
CHANGES = (
    (OLD_READ, r"\1return !value || value[0] != '0';"),
    (re.compile(r'True when (MoonRay|the denoiser) was started with %s=1' % VARIABLE), r'True unless \1 was started with \2=0'),
    (re.compile(r'Only with %s=1\.' % VARIABLE), r'Unless \1=0.'),
    (re.compile(r'without (MOONRAY_MODO_FOG_ALPHA) these are 0 and 1'), r'with \1=0 these are 0 and 1'),
)


def convert(path):
    raw = path.read_bytes().decode('utf-8')
    text = raw
    for pattern, replacement in CHANGES:
        text = pattern.sub(replacement, text)
    if text != raw:
        path.write_bytes(text.encode('utf-8'))
    return text, text != raw


def main():
    reads = 0
    for relative, expected in READS.items():
        text, changed = convert(UPSTREAM / relative)
        found = len(NEW_READ.findall(text))
        if found != expected or OLD_READ.search(text):
            raise SystemExit('%s: expected %d switch reads in the new form, found %d' % (relative, expected, found))
        reads += found
        print('edited:' if changed else 'already on by default:', relative)
    for relative in COMMENTS:
        print('edited:' if convert(UPSTREAM / relative)[1] else 'already on by default:', relative)
    patched = 0
    changed_patches = []
    for path in sorted(PATCHES.glob('*.patch')):
        text, changed = convert(path)
        if OLD_READ.search(text) or re.search(VARIABLE + '=1', text):
            raise SystemExit('%s: a switch read, or a comment, is left in the old form' % path.name)
        patched += len(NEW_READ.findall(text))
        if changed:
            changed_patches.append(path)
            print('edited:', path.relative_to(ROOT))
    if patched != reads:
        raise SystemExit('the patches read %d switches, the tree %d' % (patched, reads))
    sources = PATCHES / 'sources.json'
    manifest = json.loads(sources.read_text(encoding='utf-8'))
    for entry in manifest['repositories'].values():
        if 'patch' in entry and (ROOT / entry['patch']) in changed_patches:
            entry['patch_sha256'] = hashlib.sha256((ROOT / entry['patch']).read_bytes()).hexdigest()
    if changed_patches:
        sources.write_bytes((json.dumps(manifest, indent=2) + '\n').encode('utf-8'))
    print('%d switch reads, each on unless its variable is 0' % reads)


if __name__ == '__main__':
    main()
