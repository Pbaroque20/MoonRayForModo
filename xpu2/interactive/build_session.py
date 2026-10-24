"""Build XPU2's own runtime for the private MoonRay for Modo test kit: its preview session (xpu2_session.cc) as
moonray_xpu2.exe, the GPU programs and sampler tables of an asynchronous build, and the pinned reference runtime's
libraries and scene class proxies it loads, all in one folder (the kit's runtime keeps its own, different builds of
the same libraries).

build_session.py --source <MoonRayForModo development tree> --runtime <pinned reference> --build <async build>
                 --output <new folder>

The GPU programs are the build's own, used only while every source they are made from is as it was then: OptiX's
disk cache keeps a program by its text, so an unchanged program needs no new compile. Never installs or publishes
anything."""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from build_async import HEADERS
from native_build import build
from reference_runtime import sha, verify

HERE = Path(__file__).resolve().parent
PROGRAM_SOURCES = HEADERS + ('async_gpu.cu', 'async_adaptive.cu')


def imports(objdump, path):
    out = subprocess.run([str(objdump), '-p', str(path)], capture_output=True, text=True, errors='replace',
                         creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return re.findall(r'DLL Name:\s*(\S+)', out)


def closure(objdump, runtime, roots):
    """Every library of the runtime folder the roots load, directly or through each other."""
    present = {p.name.lower(): p for p in runtime.iterdir() if p.is_file()}
    seen, todo = {}, list(roots)
    while todo:
        path = todo.pop()
        for name in imports(objdump, path):
            hit = present.get(name.lower())
            if hit and hit.name.lower() not in seen:
                seen[hit.name.lower()] = hit
                todo.append(hit)
    return sorted(seen.values())


def build_session(source, runtime, async_build, out):
    source, runtime, async_build, out = (Path(p).resolve() for p in (source, runtime, async_build, out))
    out.mkdir(parents=True, exist_ok=False)
    verify(runtime, json.loads((HERE / 'reference-lock.json').read_text()))
    built = json.loads((async_build / 'build.json').read_text(encoding='utf-8'))
    if built.get('status') != 'passed':
        raise RuntimeError('The asynchronous build did not pass')
    drift = [n for n in PROGRAM_SOURCES if built['source_hashes'].get(str(HERE / n)) != sha(HERE / n)]
    if drift:
        raise RuntimeError('The GPU programs are made from sources changed since that build: ' + ', '.join(drift))
    files = list(HERE.glob('*.h')) + [HERE / n for n in ('xpu2_session.cc', 'build_session.py', 'native_build.py')]
    files += sorted((HERE.parents[1] / 'native-port').glob('modo_*.h'))
    held = {str(p): sha(p) for p in files}
    report = {'status': 'incomplete', 'source_hashes': held, 'async_build': str(async_build)}
    try:
        include = [source / 'toolchain/xpu/optix-dev/include',
                   source / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
        exe, report['native_build'] = build(source, HERE / 'xpu2_session.cc', out / 'native',
                                            [runtime / 'libembree4.dll', '-lcfgmgr32', '-lwinmm'],
                                            ['-I' + str(v) for v in include])
        rt = out / 'runtime-xpu2'
        (rt / 'adaptive').mkdir(parents=True)
        shutil.copyfile(exe, rt / 'moonray_xpu2.exe')
        for name in ('async_gpu.ptx', 'adaptive/async_gpu.ptx', 'adaptive/async_adaptive.ptx',
                     'bc_1D_integrator_points_4096_sequences_of_1024.bin',
                     'ppd_2D_integrator_points_4096_sequences_of_1024.bin'):
            shutil.copyfile(async_build / name, rt / name)
        objdump = source / 'toolchain/msys64/ucrt64/bin/objdump.exe'
        # The scene classes are read through their proxies (proxy mode): every one, and what they load.
        proxies = sorted(runtime.glob('*.so.proxy'))
        for p in proxies:
            shutil.copyfile(p, rt / p.name)
        libraries = closure(objdump, runtime, [exe] + proxies)
        for p in libraries:
            shutil.copyfile(p, rt / p.name)
        for name in ('MOONRAY_LICENSE.txt', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'RANDOM123_LICENSE.txt', 'ISPC_MATH_LICENSE.txt'):
            if (HERE / name).is_file():
                shutil.copyfile(HERE / name, rt / name)
        if any(sha(Path(k)) != v for k, v in held.items()):
            raise RuntimeError('Build source drift')
        manifest = {'executable_sha256': sha(rt / 'moonray_xpu2.exe'),
                    'programs': {n: sha(rt / n) for n in ('async_gpu.ptx', 'adaptive/async_gpu.ptx', 'adaptive/async_adaptive.ptx')},
                    'libraries': [p.name for p in libraries], 'proxies': len(proxies)}
        (rt / 'xpu2-runtime.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        report.update(status='passed', runtime=str(rt), **manifest)
    except Exception as error:
        report.update(status='failed', error=str(error))
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('source', 'runtime', 'build', 'output'):
        p.add_argument('--' + n, type=Path, required=True)
    a = p.parse_args()
    r = build_session(a.source, a.runtime, a.build, a.output)
    print(json.dumps({k: v for k, v in r.items() if k in ('status', 'error', 'runtime', 'proxies')}, indent=2), flush=True)
    raise SystemExit(r['status'] != 'passed')
