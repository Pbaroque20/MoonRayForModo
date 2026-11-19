"""Run the Bregman engine's prototype on a scene, write its films as PNGs and score them.

run_bregman.py --engine <build_bregman output> --ptx-build <async build> --scene <scene.rdla> --output <new folder>
               [--extra <.rdla over the scene>] [--reference <reference.rgba>] [--runtime <pinned reference>]
               [key=value ...]   (the engine's options: stride, probe_spp, n_lo, n_mid, n_hi, n_bg, m0, tau_d, tau_r, ...)

The scene gets two light path outputs (/bregman_emission C[<L.>O] and /bregman_direct C[DGS][<L.>O], whose sum is a
path's direct light at its first hit) in an override written into the output folder, after --extra. Never installs or
publishes anything."""
import argparse
import json
import subprocess
from pathlib import Path

from images import errors, read_rgba, write_png
from run_xpu2_baseline import REFERENCE, environment

LPE = ('RenderOutput("/bregman_emission") { ["file_name"]="bregman.exr", ["result"]=8, ["lpe"]="C[<L.>O]", '
       '["channel_name"]="bregman_emission", ["channel_format"]=0 }\n'
       'RenderOutput("/bregman_direct") { ["file_name"]="bregman.exr", ["result"]=8, ["lpe"]="C[DGS][<L.>O]", '
       '["channel_name"]="bregman_direct", ["channel_format"]=0 }\n')

FILMS = ('phase1', 'recon', 'phase2', 'direct2', 'final', 'classes', 'cells', 'samples2')


def run(engine, ptx_build, scene, out, options, extra=None, reference=None, runtime=REFERENCE):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    override = out / 'bregman-override.rdla'
    override.write_text((Path(extra).read_text(encoding='utf-8') if extra else '') + LPE, encoding='utf-8')
    exe = json.loads((Path(engine) / 'build.json').read_text(encoding='utf-8'))['exe']
    ptx = json.loads((Path(ptx_build) / 'build.json').read_text(encoding='utf-8'))['ptx']
    args = [exe, Path(scene).resolve(), runtime, ptx, Path(scene).resolve().parent, out] + list(options) + ['override=' + str(override)]
    env = environment(runtime)
    env['XPU2_SESSION_UNIFORM_BUDGET'] = '0'
    # OptiX's disk cache of its own beside the runs: the engine's GPU program (its own build, with OpenQMC) must not
    # crowd the kit's compiled XPU2 programs out of the shared cache (%LOCALAPPDATA%/NVIDIA/OptixCache, pruned by size).
    cache = out.parent / 'optix-cache'
    cache.mkdir(exist_ok=True)
    env['OPTIX_CACHE_PATH'] = str(cache)
    r = subprocess.run(list(map(str, args)), cwd=out, env=env, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=3600)
    (out / 'engine.log').write_text(r.stdout + r.stderr, encoding='utf-8')
    lines = [l for l in r.stdout.splitlines() if l.startswith('{')]
    if not lines:
        raise SystemExit('bregman_engine failed: ' + r.stderr[-3000:])
    report = json.loads(lines[-1])
    report['exit_code'] = r.returncode
    w, h = report['width'], report['height']
    for name in FILMS:
        f = read_rgba(out / (name + '.rgba'), w, h)
        linear = name in ('classes', 'cells', 'samples2')
        write_png(out / (name + '.png'), f, w, h, linear=linear)
    d = read_rgba(out / 'depth.rgba', w, h)
    top = max(d[i * 4] for i in range(w * h)) or 1.0
    write_png(out / 'depth.png', d, w, h, scale=1.0 / top, linear=True)
    xpu2 = sorted(report.get('xpu2', {}), key=int)
    for n in xpu2:
        write_png(out / f'xpu2-{n}.png', read_rgba(out / f'xpu2-{n}.rgba', w, h), w, h)
    # Timed runs only (run 0 warms up): the median.
    median = lambda v: sorted(v)[len(v) // 2] if v else None
    timed = [r for r in report.get('runs', []) if not r.get('warm_up')]
    report['median_seconds'] = {'engine': median([r['total_seconds'] for r in timed]),
                                'phase1': median([r['phase1_seconds'] for r in timed]),
                                'phase2': median([r['phase2_seconds'] for r in timed]),
                                'region': median([r['region_seconds'] for r in timed])}
    for n in xpu2:
        report['median_seconds'][f'xpu2-{n}'] = median([r['seconds'] for r in report['xpu2'][n] if not r.get('warm_up')])
    if reference:
        ref = read_rgba(reference, w, h)
        names = ['final', 'phase2', 'recon'] + [f'xpu2-{n}' for n in xpu2]
        report['errors'] = {n: errors(read_rgba(out / (n + '.rgba'), w, h), ref, w, h) for n in names}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine', type=Path, required=True)
    p.add_argument('--ptx-build', type=Path, required=True)
    p.add_argument('--scene', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--extra', type=Path)
    p.add_argument('--reference', type=Path)
    p.add_argument('--runtime', type=Path, default=REFERENCE)
    p.add_argument('options', nargs='*')
    a = p.parse_args()
    report = run(a.engine, a.ptx_build, a.scene, a.output, a.options, a.extra, a.reference, a.runtime)
    keep = {k: report[k] for k in ('median_seconds', 'classes', 'phase2_samples_per_pixel', 'phase1_probe_samples_per_pixel') if k in report}
    keep['relative_mse'] = {n: round(e['relative_mse'], 7) for n, e in report.get('errors', {}).items()}
    keep['block_error'] = {n: round(e['block_error'], 6) for n, e in report.get('errors', {}).items()}
    keep['mean_ratio'] = {n: round(e['mean_ratio'], 5) for n, e in report.get('errors', {}).items()}
    print(json.dumps(keep, indent=2))


if __name__ == '__main__':
    main()
