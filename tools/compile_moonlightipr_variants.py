"""Compile MoonLightIPR's kernel once for each set of its heavy features, beside the full kernel.

A scene that uses no fog, hair, subsurface scattering, toon or fuzz is rendered by a kernel made without them, which
is a third faster or more (each feature's code and state cost every ray, used or not). The renderer chooses the kernel
for the features its materials use (renderer.cpp, Impl::specialize), from MoonLightIPRKernel_fNN.ptx, NN being the
features (shared.h, FEATURE_*) as a number; MoonLightIPRKernel.ptx is all of them.

compile_moonlightipr_variants.py <kernel.cu> <shaders folder>     (only the variants older than the sources are compiled)"""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Variants 0 to 63: every set of the heavy features, procedural layers (FEATURE_PROCEDURAL, 32) among them, so that a
# scene is compiled with only the code it uses (the full kernel took a minute and a half to compile the first time).
ALL = 64


def main():
    source, folder = Path(sys.argv[1]), Path(sys.argv[2])
    folder.mkdir(parents=True, exist_ok=True)
    # The procedural patterns the kernel shares with MoonRay's ModoProceduralMap count among its sources too.
    sources = [source] + sorted(source.parent.glob('*.h')) + [ROOT / 'tools/compile_moonlightipr_ptx.py', ROOT / 'native-port/maps/ModoProcedural/modo_patterns.h']
    newest = max(path.stat().st_mtime for path in sources)
    wanted = [features for features in range(ALL) if not (folder / ('MoonLightIPRKernel_f%02d.ptx' % features)).is_file()
              or (folder / ('MoonLightIPRKernel_f%02d.ptx' % features)).stat().st_mtime < newest]
    if not wanted:
        print('Kernel variants are up to date', flush=True)
        return

    def compile_one(features):
        target = folder / ('MoonLightIPRKernel_f%02d.ptx' % features)
        done = subprocess.run([sys.executable, str(ROOT / 'tools/compile_moonlightipr_ptx.py'), str(source), str(target), '-DML_FEATURES=%du' % features],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return features, done.returncode, done.stdout.decode('utf-8', errors='replace')

    failed = []
    with ThreadPoolExecutor(max_workers=max(1, min(8, (os.cpu_count() or 2) - 1))) as pool:
        for features, code, log in pool.map(compile_one, wanted):
            if code:
                failed.append(features)
                print('Kernel variant %02d failed:\n%s' % (features, log[-2000:]), flush=True)
    print('Compiled %d kernel variant(s)%s' % (len(wanted) - len(failed), '; failed: %s' % failed if failed else ''), flush=True)
    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
