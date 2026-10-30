"""The plugin's change to MoonRay's denoiser (mcrt_denoise, which denoise.exe and the plugin's denoising use), behind a
switch of its own (MoonRay Source Overrides in the plugin's preferences, on by default); off, the denoiser is MoonRay's
own.

MOONRAY_MODO_DENOISE_CLEAN_GUIDES: Open Image Denoise cleans the albedo and normal guides first, each with a filter of
its own, and is told they are clean (cleanAux), as its documentation advises for the best quality. MoonRay's own hands
the guides over as rendered and has Open Image Denoise treat them as noisy, so it trusts them less and keeps more of the
beauty's noise. OptiX has no such mode; with it the switch changes nothing.

Tried and left out (16 samples a pixel against 1,024, on the gl-base glass scene and the dragon scene): pulling down
fireflies before denoising helped only by flattening bright highlights' edges, which would dim a thin rim light as well;
giving OptiX's HDR model the picture's brightness (optixDenoiserComputeIntensity) and OptiX's AOV model each gave a
picture identical to MoonRay's own, as OptiX measures the brightness itself when it is not given.

The switch is read once, from the denoiser's environment (the plugin starts denoise.exe as it starts MoonRay).
Rerunning this script leaves edited files alone; the files keep their line endings."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DENOISER = ROOT / 'upstream/openmoonray/moonray/mcrt_denoise/lib/denoiser'
MARK = 'MOONRAY_MODO_DENOISE_CLEAN_GUIDES'

SWITCH = '''
// Modo: Open Image Denoise cleans the albedo and normal guides first and is told they are clean (cleanAux)
// (tools/port_denoise_overrides.py). True when the denoiser was started with MOONRAY_MODO_DENOISE_CLEAN_GUIDES=1; read
// once. Off, the denoiser is MoonRay's own.
inline bool modoCleanGuides()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_DENOISE_CLEAN_GUIDES");
        return value && value[0] == '1';
    }();
    return on;
}
'''

EDITS = {
    DENOISER / 'OIDNDenoiserImpl.h': [
        ('''#include <OpenImageDenoise/oidn.h>
''', '''#include <OpenImageDenoise/oidn.h>
#include <cstdlib>
''', 1),
        ('''namespace moonray {
namespace denoiser {
''', '''namespace moonray {
namespace denoiser {
''' + SWITCH, 1),
        # (After the last member, whose line ends in a space.)
        ('''
};
''', '''
    // Modo: the guides' own filters, which clean them first (MOONRAY_MODO_DENOISE_CLEAN_GUIDES).
    OIDNFilter mModoAlbedoFilter = nullptr;
    OIDNFilter mModoNormalFilter = nullptr;
};
''', 1),
    ],
    DENOISER / 'OIDNDenoiserImpl.cc': [
        # (After the guides are set: the line before is blank but for spaces.)
        ('''    oidnCommitFilter(mFilter);
''', '''    // Modo: with MOONRAY_MODO_DENOISE_CLEAN_GUIDES each guide is cleaned first by a filter of its own, in place, and
    // the beauty's filter is told the guides are clean (cleanAux). Off, as MoonRay's source: the guides as rendered.
    if (modoCleanGuides() && (mUseAlbedo || mUseNormals)) {
        if (mUseAlbedo) {
            mModoAlbedoFilter = oidnNewFilter(mDevice, "RT");
            oidnSetFilterImage(mModoAlbedoFilter, "albedo", mInputAlbedo3, OIDN_FORMAT_FLOAT3, mWidth, mHeight, 0, 0, 0);
            oidnSetFilterImage(mModoAlbedoFilter, "output", mInputAlbedo3, OIDN_FORMAT_FLOAT3, mWidth, mHeight, 0, 0, 0);
            oidnCommitFilter(mModoAlbedoFilter);
        }
        if (mUseNormals) {
            mModoNormalFilter = oidnNewFilter(mDevice, "RT");
            oidnSetFilterImage(mModoNormalFilter, "normal", mInputNormals3, OIDN_FORMAT_FLOAT3, mWidth, mHeight, 0, 0, 0);
            oidnSetFilterImage(mModoNormalFilter, "output", mInputNormals3, OIDN_FORMAT_FLOAT3, mWidth, mHeight, 0, 0, 0);
            oidnCommitFilter(mModoNormalFilter);
        }
        oidnSetFilter1b(mFilter, "cleanAux", true);
        scene_rdl2::logging::Logger::info("Open Image Denoise cleans the guides first");
    }

    oidnCommitFilter(mFilter);
''', 1),
        ('''    if (mFilter) oidnReleaseFilter(mFilter);''', '''    if (mModoAlbedoFilter) oidnReleaseFilter(mModoAlbedoFilter);
    if (mModoNormalFilter) oidnReleaseFilter(mModoNormalFilter);
    if (mFilter) oidnReleaseFilter(mFilter);''', 1),
        ('''    oidnExecuteFilter(mFilter);
''', '''    // Modo: the guides cleaned first (MOONRAY_MODO_DENOISE_CLEAN_GUIDES).
    if (mModoAlbedoFilter) oidnExecuteFilter(mModoAlbedoFilter);
    if (mModoNormalFilter) oidnExecuteFilter(mModoNormalFilter);

    oidnExecuteFilter(mFilter);
''', 1),
    ],
}

for path, edits in EDITS.items():
    data = path.read_bytes().decode('utf-8')
    crlf = '\r\n' in data
    text = data.replace('\r\n', '\n')
    if MARK in text:
        print('already edited:', path.relative_to(ROOT))
        continue
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            raise SystemExit('%s: expected %d of %r, found %d' % (path.relative_to(ROOT), count, old[:70], found))
        text = text.replace(old, new)
    path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
    print('edited:', path.relative_to(ROOT))
