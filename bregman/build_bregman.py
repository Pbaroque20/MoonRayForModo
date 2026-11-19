"""Build the Bregman engine's prototype (bregman_engine.exe), host code only, with XPU2's build helpers.

build_bregman.py --source <MoonRayForModo development tree: toolchain, build, upstream> --runtime <pinned reference>
                 --output <new folder>

The engine runs XPU2's GPU program unchanged: point it at an asynchronous build's async_gpu.ptx whose GPU program sources
match this tree's (bregman/tools/run_bregman.py checks). Never installs or publishes anything."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
XPU2 = HERE.parent / 'xpu2' / 'interactive'
sys.path.insert(0, str(XPU2))

from native_build import bc6h_kernels, build_units  # noqa: E402
from reference_runtime import sha  # noqa: E402


def build(source, runtime, out):
    source, runtime, out = (Path(p).resolve() for p in (source, runtime, out))
    out.mkdir(parents=True, exist_ok=False)
    files = list(XPU2.glob('*.h')) + list(HERE.glob('*.h')) + [HERE / 'bregman_engine.cc', HERE / 'build_bregman.py']
    held = {str(p): sha(p) for p in files}
    report = {'status': 'incomplete', 'source_hashes': held}
    try:
        include = [XPU2, HERE,
                   source / 'toolchain/xpu/optix-dev/include',
                   source / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include',
                   source / 'upstream/openmoonray/moonray/moonray/lib/rendering/lpe',
                   source / 'upstream/openmoonray/moonray/moonray/lib/rendering/displayfilter',
                   source / 'build/native-renderer-avx/moonray/lib/rendering/displayfilter']
        kernels, kernel_flags = bc6h_kernels(source, out / 'bc6h')
        exe, report['native_build'] = build_units(
            source, [HERE / 'bregman_engine.cc', XPU2 / 'xpu2_meshopt.cc', XPU2 / 'xpu2_bc6h.cc'], out / 'native',
            [runtime / 'libembree4.dll', runtime / 'librendering_lpe.dll', runtime / 'librendering_displayfilter.dll',
             *kernels, '-lcfgmgr32', '-lwinmm'],
            ['-I' + str(v) for v in include] + ['-I' + str(source / 'upstream/meshoptimizer/src')] + kernel_flags)
        target = out / 'bregman_engine.exe'
        target.write_bytes(Path(exe).read_bytes())
        if any(sha(Path(k)) != v for k, v in held.items()):
            raise RuntimeError('Build source drift')
        report.update(status='passed', exe=str(target), exe_sha256=sha(target))
    except Exception as error:
        report.update(status='failed', error=str(error))
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('source', 'runtime', 'output'):
        p.add_argument('--' + n, type=Path, required=True)
    a = p.parse_args()
    r = build(a.source, a.runtime, a.output)
    print(json.dumps({k: v for k, v in r.items() if k in ('status', 'error', 'exe')}, indent=2), flush=True)
    raise SystemExit(r['status'] != 'passed')
