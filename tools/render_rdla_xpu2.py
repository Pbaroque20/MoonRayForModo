"""Render RDLA scenes with XPU2's preview session outside Modo (xpu2/interactive/session_harness.py, as
tools/measure_xpu2_load.py starts it), each to the end of its first frame, and write xpu2_<case>.exr beside it. Shader
programs compile into a cache of the caller's own (--cache: OPTIX_CACHE_PATH and XPU2_SHADER_MARKS under it), never
the kit's.

render_rdla_xpu2.py --runtime <MoonRay runtime> --xpu2 <runtime-xpu2> --cache <folder> <folder> <case> [case ...]"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--xpu2', type=Path, required=True)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--timeout', type=float, default=1800)
parser.add_argument('--mode', default='2', help='XPU2_SESSION_MODE: 2 the CPU and GPU, 0 the CPU alone (no GPU programs needed)')
parser.add_argument('folder', type=Path)
parser.add_argument('cases', nargs='+')
args = parser.parse_args()
cache = args.cache.resolve()
for name in ('optix', 'marks', 'modo'):
    (cache / name).mkdir(parents=True, exist_ok=True)
env = {'PATH': os.pathsep.join([str(args.xpu2), str(args.runtime)]), 'RDL2_DSO_PATH': str(args.xpu2), 'REZ_MOONRAY_ROOT': str(args.xpu2),
       'MOONRAY_XPU2_MOONRAY': str(args.runtime / 'moonray.exe'), 'XPU2_SESSION_CHAIN': '0', 'XPU2_SESSION_MODE': args.mode,
       'MOONRAY_MODO_CACHE': str(cache / 'modo'), 'MOONRAY_MODO_OPAQUE_ALPHA': '1',
       'OPTIX_CACHE_PATH': str(cache / 'optix'), 'XPU2_SHADER_MARKS': str(cache / 'marks')}
for case in args.cases:
    out = (args.folder / ('xpu2-' + case)).resolve()
    command = [sys.executable, str(root / 'xpu2/interactive/session_harness.py'), '--exe', str(args.xpu2 / 'moonray_xpu2.exe'),
               '--scene', str((args.folder / (case + '.rdla')).resolve()), '--output', str(out), '--timeout', str(args.timeout)]
    for key, value in env.items():
        command += ['--env', '%s=%s' % (key, value)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=args.timeout + 120)
    try:
        report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        report = {'stdout': done.stdout[-1500:], 'stderr': done.stderr[-1500:]}
    frames = sorted(out.glob('frame-*.pfm'))
    if frames:
        subprocess.run([str(args.runtime / 'oiiotool.exe'), str(frames[-1]), '-d', 'float', '-o', str(args.folder / ('xpu2_%s.exr' % case))],
                       env=dict(os.environ, PATH=str(args.runtime)), check=True)
    print(case, 'frames', len(frames), 'fallback', report.get('fallback'), 'exit', report.get('exit_code'), 'seconds', report.get('seconds'))
