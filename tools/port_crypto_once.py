"""Each Cryptomatte sample counted once in vector and XPU modes.

A camera path in vector mode reaches the film as several radiance entries (its bounces and light samples), which can be
added by different threads at once. Film::addSampleBundleHandlerHelper gives the path's surface its Cryptomatte coverage
with the first of them: it reads the path's mIsFirstSample, adds the sample, then clears the flag. Two threads that read
the flag before either clears it both add the coverage, and the pixel's mattes add up to twice its alpha. About one
pixel in eight renders of 480 x 270 at 16 samples showed it, the same with or without the fog patch.

Only when MoonRay is started with MOONRAY_MODO_CRYPTO_ONCE=1 (the plugin's preference): the flag is read and cleared in
one atomic exchange, so one entry alone adds the coverage. Without the variable, MoonRay's own read-then-clear."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDERING = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering'

HEADER = 'pbr/core/ModoCryptoOnce.h'
HEADER_TEXT = '''// Modo: each Cryptomatte sample counted once in vector and XPU modes (tools/port_crypto_once.py).
#pragma once

#include <cstdint>
#include <cstdlib>

namespace moonray {
namespace pbr {

/// True when MoonRay was started with MOONRAY_MODO_CRYPTO_ONCE=1. Read once.
inline bool modoCryptoOnce()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_CRYPTO_ONCE");
        return value && value[0] == '1';
    }();
    return on;
}

/// Whether this is the path's first entry: with the switch on, read and cleared at once, so that only one thread
/// sees it set; without it, read as MoonRay does (the caller clears it).
inline bool modoTakeFirstSample(uint8_t &first)
{
    if (modoCryptoOnce()) {
        return __atomic_exchange_n(&first, uint8_t(0), __ATOMIC_ACQ_REL) != 0;
    }
    return first != 0;
}

} // namespace pbr
} // namespace moonray
'''

EDITS = {
    'rndr/Film.cc': [
        ('''#include <moonray/rendering/pbr/core/PbrTLState.h>
''', '''#include <moonray/rendering/pbr/core/PbrTLState.h>
#include <moonray/rendering/pbr/core/ModoCryptoOnce.h>
''', 1),
        ('''                        if (cryptomatteData->mIsFirstSample) {
''', '''                        if (pbr::modoTakeFirstSample(cryptomatteData->mIsFirstSample)) {
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
            raise RuntimeError('Crypto once anchor missing or ambiguous in %s: %r' % (name, old[:70]))
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
