"""Build the Bregman engine's prototype: bregman_engine.exe and, with --gpu, its own copy of XPU2's GPU program.

build_bregman.py --source <MoonRayForModo development tree: toolchain, build, upstream> --runtime <pinned reference>
                 --output <new folder> [--gpu]

With --gpu the GPU program (async_gpu.ptx and its modules, laid out as build_async.py lays them out) is compiled from
this tree with XPU2_OPENQMC: phase 2's frame cache and OpenQMC draws (async_integrator.h) are in it, off unless the
engine's phase 2 turns them on. build.json's "ptx" then names it; without --gpu, pass the engine an asynchronous build
whose GPU program sources match this tree's. The host is always built with XPU2_OPENQMC and OpenQMC's headers
(moonlightipr/third_party/openqmc). Never installs or publishes anything."""
import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
XPU2 = HERE.parent / 'xpu2' / 'interactive'
OPENQMC = HERE.parent / 'moonlightipr' / 'third_party' / 'openqmc' / 'include'
NVRTC_STD = HERE.parent / 'moonlightipr' / 'third_party' / 'nvrtc-std'
sys.path.insert(0, str(XPU2))

from build_async import FAST_FLAGS, HEADERS  # noqa: E402
from gpu_build import compile_ptx  # noqa: E402
from native_build import bc6h_kernels, build_units  # noqa: E402
from reference_runtime import sha  # noqa: E402

QMC = ['-DXPU2_OPENQMC=1', '-I' + str(OPENQMC), '-I' + str(NVRTC_STD)]


def build_gpu(source, out, report):
    """XPU2's GPU program as build_async.py makes it, with OpenQMC."""
    for d in ('adaptive', 'material', 'maps', 'lights', 'lobes', 'volumes', 'volumemaps', 'dwa', 'dwalobes', 'extras'):
        (out / d).mkdir()
    calls = ['-DXPU2_MATERIAL_MODULE=1', '-DXPU2_LIGHT_MODULE=1', '-DXPU2_LOBE_MODULE=1', '-DXPU2_EXTRAS_MODULE=1']
    rdc = ['--relocatable-device-code=true']
    jobs = {
        'ptx': ('async_gpu.cu', out, FAST_FLAGS + calls + ['-DXPU2_VOLUME_MODULE=1']),
        'ptx_material': ('async_material.cu', out / 'material', FAST_FLAGS + rdc + ['-DXPU2_MAP_MODULE=1', '-DXPU2_DWA_MODULE=1']),
        'ptx_dwa': ('async_dwa.cu', out / 'dwa', FAST_FLAGS + rdc),
        'ptx_dwalobes': ('async_dwalobes.cu', out / 'dwalobes', FAST_FLAGS + rdc),
        'ptx_extras': ('async_extras.cu', out / 'extras', FAST_FLAGS + rdc),
        'ptx_maps': ('async_maps.cu', out / 'maps', FAST_FLAGS + rdc),
        'ptx_lights': ('async_lights.cu', out / 'lights', FAST_FLAGS + rdc),
        'ptx_lobes': ('async_lobes.cu', out / 'lobes', FAST_FLAGS + rdc),
        'ptx_volumes': ('async_volumes.cu', out / 'volumes', FAST_FLAGS + calls + rdc),
        'ptx_volumemaps': ('async_volumes.cu', out / 'volumemaps', FAST_FLAGS + calls + rdc + ['-DXPU2_VOLUME_MAPS_MODULE=1']),
        'ptx_chain': ('async_adaptive.cu', out / 'adaptive', FAST_FLAGS),
    }
    with ThreadPoolExecutor(len(jobs)) as pool:
        futures = {k: pool.submit(compile_ptx, source, d, unit, HEADERS, flags + QMC) for k, (unit, d, flags) in jobs.items()}
        for k, f in futures.items():
            ptx, log = f.result()
            report[k] = str(ptx)
            report['cuda_' + k] = {'ptx_sha256': log['ptx_sha256']}
    # MoonRay's sampler tables (a random walk's sequences) beside the GPU program, as build_async.py puts them.
    sampler = source / 'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/sampler'
    for name in ('bc_1D_integrator_points_4096_sequences_of_1024.bin', 'ppd_2D_integrator_points_4096_sequences_of_1024.bin'):
        shutil.copyfile(sampler / name, out / name)


def build(source, runtime, out, gpu=False):
    source, runtime, out = (Path(p).resolve() for p in (source, runtime, out))
    out.mkdir(parents=True, exist_ok=False)
    files = list(XPU2.glob('*.h')) + list(XPU2.glob('async_*.cu')) + list(HERE.glob('*.h')) + list(OPENQMC.rglob('*.h')) + \
        [HERE / 'bregman_engine.cc', HERE / 'build_bregman.py']
    held = {str(p): sha(p) for p in files}
    report = {'status': 'incomplete', 'source_hashes': held, 'gpu': gpu}
    try:
        if gpu:
            build_gpu(source, out, report)
        include = [XPU2, HERE, OPENQMC,
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
            ['-I' + str(v) for v in include] + ['-I' + str(source / 'upstream/meshoptimizer/src'), '-DXPU2_OPENQMC=1'] + kernel_flags)
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
    p.add_argument('--gpu', action='store_true', help="compile XPU2's GPU program with OpenQMC into the output")
    a = p.parse_args()
    r = build(a.source, a.runtime, a.output, a.gpu)
    print(json.dumps({k: v for k, v in r.items() if k in ('status', 'error', 'exe', 'ptx')}, indent=2), flush=True)
    raise SystemExit(r['status'] != 'passed')
