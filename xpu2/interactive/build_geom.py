"""Builds xpu2_geom.dll (xpu2_geom.cc): MoonRay's own subdivision surface tessellation for XPU2, compiled with the very
flags MoonRay's build compiles its OpenSubdivMesh with, and linked against MoonRay's geometry library and what it links.

build_geom.py --source <MoonRayForModo checkout> --output <folder>   (writes <folder>/xpu2_geom.dll and build.json)"""
import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tools'))
from xpu2_rdl_index_probe import block  # noqa: E402
from fallback import environment  # noqa: E402
from reference_runtime import sha  # noqa: E402


def build_geom(source, out):
    source, out = Path(source).resolve(), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = source / 'build/native-renderer-avx'
    ninja = (root / 'build.ninja').read_text(encoding='utf-8')
    compiled = block(ninja, 'build moonray/lib/rendering/geom/CMakeFiles/rendering_geom.dir/prim/OpenSubdivMesh.cc.obj:')
    linked = block(ninja, 'build bin/librendering_geom.dll moonray/lib/rendering/geom/librendering_geom.dll.a:')
    compiler = source / 'toolchain/msys64/ucrt64/bin/g++.exe'
    flags = [f for f in shlex.split(' '.join(compiled[k] for k in ('DEFINES', 'FLAGS', 'INCLUDES'))) if f != '-Drendering_geom_EXPORTS']
    libs = [str(root / 'moonray/lib/rendering/geom/librendering_geom.dll.a')]
    libs += [v if v.startswith('-') else str((root / v).resolve()) for v in shlex.split(linked['LINK_LIBRARIES'])]
    dll = out / 'xpu2_geom.dll'
    cmd = [str(compiler), *flags, '-shared', str(HERE / 'xpu2_geom.cc'), '-o', str(dll), *libs]
    r = subprocess.run(cmd, env=environment(compiler.parent, out), capture_output=True, text=True, timeout=900,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    (out / 'compile.log').write_text(r.stdout + r.stderr, encoding='utf-8')
    report = {'status': 'passed' if r.returncode == 0 and dll.is_file() else 'failed',
              'sources': {str(p): sha(p) for p in (HERE / 'xpu2_geom.cc', HERE / 'xpu2_geom.h')}}
    if report['status'] == 'passed':
        report['dll_sha256'] = sha(dll)
    else:
        report['error'] = (r.stderr or r.stdout)[-2000:]
    (out / 'build.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    print(json.dumps(build_geom(a.source, a.output), indent=2))
