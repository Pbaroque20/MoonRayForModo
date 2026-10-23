"""Build the asynchronous renderer's worker (async_probe.exe) and its OptiX program.

build_async.py --source <MoonRayForModo development tree> --runtime <pinned reference> --output <new folder>

The OptiX program is compiled for speed (contraction allowed); the parity
pipeline's program keeps its exact flags (gpu_build.PARITY_FLAGS). Never installs
or publishes anything."""
import argparse
import json
from pathlib import Path

from gpu_build import compile_ptx
from native_build import build
from reference_runtime import sha, verify

HERE = Path(__file__).resolve().parent
HEADERS = ('async_gpu_abi.h', 'async_adaptive_core.h', 'async_integrator.h', 'light_core.h', 'gpu_jobs.h', 'resume_core.h', 'triangle_hit.h',
           'texture_core.h', 'surface_core.h', 'sample_stream.h', 'path_stage.h', 'shade_math.h', 'shade_tables.h',
           'shade_fresnel.h', 'shade_color.h', 'shade_lobes.h', 'shade_lobes_eval.h', 'shade_hair.h', 'shade_flakes.h', 'shade_glitter.h', 'shade_glitter_tables.h', 'shade_state.h', 'shade_builder.h',
           'shade_colorcorrect.h', 'shade_dwabase.h', 'shade_dwalayer.h', 'shade_maps.h', 'shade_noise.h', 'shade_bssrdf.h', 'shade_mapnodes.h', 'curve_core.h', 'curve_embree.h', 'volume_core.h', 'shade_material.h',
           'dwa_admission.h', 'map_admission.h')
FAST_FLAGS = ['--std=c++17', '--gpu-architecture=compute_75', '--fmad=true', '--prec-div=true',
              '--prec-sqrt=true', '--ftz=false', '-DXPU2_PATHS_ONLY']


def build_all(source, runtime, out):
    source, runtime, out = (Path(p).resolve() for p in (source, runtime, out))
    out.mkdir(parents=True, exist_ok=False)
    verify(runtime, json.loads((HERE / 'reference-lock.json').read_text()))
    files = list(HERE.glob('*.h')) + [HERE / n for n in ('async_probe.cc', 'async_gpu.cu', 'async_adaptive.cu', 'build_async.py',
                                                         'gpu_build.py', 'native_build.py')]
    held = {str(p): sha(p) for p in files}
    report = {'status': 'incomplete', 'source_hashes': held}
    try:
        # One program for uniform frames, one for adaptive frames (async_gpu.cu).
        ptx, report['cuda_build'] = compile_ptx(source, out, 'async_gpu.cu', HEADERS, FAST_FLAGS + ['-DXPU2_ADAPTIVE=0'])
        (out / 'adaptive').mkdir()
        adaptive, report['cuda_build_adaptive'] = compile_ptx(source, out / 'adaptive', 'async_gpu.cu', HEADERS,
                                                              FAST_FLAGS + ['-DXPU2_ADAPTIVE=1'])
        # The adaptive pass chain's CUDA kernels, beside the adaptive program.
        chain, report['cuda_build_chain'] = compile_ptx(source, out / 'adaptive', 'async_adaptive.cu', HEADERS, FAST_FLAGS)
        include = [source / 'toolchain/xpu/optix-dev/include',
                   source / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
        exe, report['native_build'] = build(source, HERE / 'async_probe.cc', out / 'native',
                                            [runtime / 'libembree4.dll', '-lcfgmgr32', '-lwinmm'],
                                            ['-I' + str(v) for v in include])
        if any(sha(Path(k)) != v for k, v in held.items()):
            raise RuntimeError('Build source drift')
        report.update(status='passed', exe=str(exe), ptx=str(ptx), ptx_adaptive=str(adaptive), ptx_chain=str(chain),
                      binary_hashes={'exe': sha(exe), 'ptx': sha(ptx), 'ptx_adaptive': sha(adaptive), 'ptx_chain': sha(chain)})
    except Exception as error:
        report.update(status='failed', error=str(error))
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('source', 'runtime', 'output'):
        p.add_argument('--' + n, type=Path, required=True)
    a = p.parse_args()
    r = build_all(a.source, a.runtime, a.output)
    print(json.dumps({k: v for k, v in r.items() if k in ('status', 'error', 'exe', 'ptx')}, indent=2), flush=True)
    raise SystemExit(r['status'] != 'passed')
