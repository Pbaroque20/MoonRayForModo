"""Render a scene with XPU2's benchmark worker (async_probe.exe) for a baseline: time and image.

run_xpu2_baseline.py --build <async build folder> --scene <scene.rdla> --output <new folder>
                     [--runtime <pinned reference>] [--threads 12] [--repeats 3] [--mode 2] [--override <.rdla>]

Writes the worker's JSON report (report.json), each run's raw RGBA and a PNG of the first run (run-0.png).
Never installs or publishes anything."""
import argparse
import json
import os
import subprocess
from pathlib import Path

from images import read_rgba, write_png

REFERENCE = Path(r'C:\Users\Raphael Tobar\MoonRayForModo-xpu2\test-results\interactive-reference-042')


def environment(runtime):
    env = dict(os.environ)
    env['PATH'] = str(runtime) + os.pathsep + env.get('PATH', '')
    env['RDL2_DSO_PATH'] = str(runtime)
    env['REZ_MOONRAY_ROOT'] = str(runtime)
    return env


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--runtime', type=Path, default=REFERENCE)
    p.add_argument('--threads', type=int, default=12)
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--mode', type=int, default=2)
    p.add_argument('--override', type=Path)
    a = p.parse_args()
    build = json.loads((a.build / 'build.json').read_text(encoding='utf-8'))
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    # The asset root: every texture the scene reads must be under it (host_texture.h admittedPath); read only.
    args = [build['exe'], a.scene.resolve(), a.runtime, build['ptx'], a.scene.resolve().parent, out, a.threads, a.repeats, a.mode]
    if a.override:
        args += ['-', '-', '-', '-', '-', a.override.resolve()]
    env = environment(a.runtime)
    # Exact uniform sampling (the scene's pixel_samples), not uniform's budget spent by generations: the engine's
    # phases sample by per-pixel counts, which turn generations off, so the baseline must too.
    env.setdefault('XPU2_SESSION_UNIFORM_BUDGET', '0')
    r = subprocess.run(list(map(str, args)), cwd=out, env=env, capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=3600)
    (out / 'probe.log').write_text(r.stdout + r.stderr, encoding='utf-8')
    # The worker prints its report, then may end with "terminate called without an active exception" in its
    # teardown (seen 2026-11-19 with async-build-handoff1): the frames are whole by then; trust the report.
    lines = [l for l in r.stdout.splitlines() if l.startswith('{')]
    if not lines:
        raise SystemExit('async_probe failed: ' + r.stderr[-2000:])
    report = json.loads(lines[-1])
    if report.get('status') != 'passed':
        raise SystemExit('async_probe report: ' + lines[-1][:2000])
    report['exit_code'] = r.returncode
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    w, h = report['width'], report['height']
    rgba = read_rgba(Path(report['runs'][0]['raw_file']), w, h)
    write_png(out / 'run-0.png', rgba, w, h)
    print(json.dumps({'prepare_seconds': report['prepare_seconds'],
                      'sampling_seconds': [run['sampling_seconds'] for run in report['runs']],
                      'gpu_share': [run['gpu_share'] for run in report['runs']]}, indent=2))


if __name__ == '__main__':
    main()
