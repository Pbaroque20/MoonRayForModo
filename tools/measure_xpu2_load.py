"""How long XPU2's preview session takes from a scene's files to its first picture, run outside Modo with the installed
kit's runtime (session_harness.py), cold (an empty cache folder of its own) and then warm (the same cache folder), as
the kit starts it (shared-memory .rdlb, its environment). measure_xpu2_load.py <scene.rdla> <scene.rdlb> <out folder>
[--mode 2|1|0] [--xpu2 <runtime-xpu2>] [--runs cold,warm]. Writes <out>/<cold|warm>/report.json and prints the times."""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
kit = pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo'
runtime, xpu2 = kit / 'runtime', kit / 'runtime-xpu2'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('rdla', type=pathlib.Path)
parser.add_argument('rdlb', type=pathlib.Path)
parser.add_argument('out', type=pathlib.Path)
parser.add_argument('--mode', default='2')
parser.add_argument('--drain-after', type=float, default=4.0)
parser.add_argument('--xpu2', type=pathlib.Path, help="another XPU2 runtime than the installed kit's (a build's runtime-xpu2)")
parser.add_argument('--runs', default='cold,warm')
args = parser.parse_args()
if args.xpu2:
    xpu2 = args.xpu2
cache = args.out / 'cache'
if cache.exists():
    shutil.rmtree(cache)
cache.mkdir(parents=True)
env = {'PATH': os.pathsep.join([str(xpu2), str(runtime)]), 'RDL2_DSO_PATH': str(xpu2), 'REZ_MOONRAY_ROOT': str(xpu2),
       'MOONRAY_XPU2_MOONRAY': str(runtime / 'moonray.exe'), 'XPU2_SESSION_CHAIN': '0', 'XPU2_SESSION_MODE': args.mode,
       'XPU2_SESSION_GEOMETRY_CACHE': '1', 'MOONRAY_MODO_CACHE': str(cache), 'MOONRAY_MODO_OPAQUE_ALPHA': '1'}
summary = {}
for run in args.runs.split(','):
    out = args.out / run
    if out.exists():
        shutil.rmtree(out)
    command = [sys.executable, str(root / 'xpu2/interactive/session_harness.py'), '--exe', str(xpu2 / 'moonray_xpu2.exe'),
               '--scene', str(args.rdla), '--scene', str(args.rdlb), '--output', str(out), '--memory-binary',
               '--drain-after', str(args.drain_after), '--timeout', '900']
    for key, value in env.items():
        command += ['--env', '%s=%s' % (key, value)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=1000)
    try:
        report = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        report = {'stdout': done.stdout[-2000:], 'stderr': done.stderr[-2000:]}
    frames = report.get('frames') or {}
    first = min((f.get('first_picture') for f in frames.values() if f.get('first_picture') is not None), default=None)
    summary[run] = {'first_picture': first, 'seconds': report.get('seconds'), 'exit_code': report.get('exit_code'),
                    'fallback': report.get('fallback')}
    print(run, json.dumps(summary[run]))
(args.out / 'summary.json').write_text(json.dumps(summary, indent=1), encoding='utf-8')
