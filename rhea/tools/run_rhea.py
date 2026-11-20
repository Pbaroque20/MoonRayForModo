"""Run Rhea on a scene, write its films as PNGs and score them.

run_rhea.py --engine <build_rhea output> --ptx-build <async build> --scene <scene.rdla> --output <new folder>
               [--extra <.rdla over the scene>] [--reference <reference.rgba>] [--runtime <pinned reference>]
               [key=value ...]   (the engine's options: s0, min_stride, tol, probe_spp, n_lo, n_hi, n_bg, m0, tau_r, ...)

The scene gets two light path outputs (/rhea_emission C[<L.>O] and /rhea_direct C[DGS][<L.>O], whose sum is a
path's direct light at its first hit) in an override written into the output folder, after --extra. Never installs or
publishes anything."""
import argparse
import json
import subprocess
from pathlib import Path

from images import errors, read_rgba, write_png
from run_xpu2_baseline import REFERENCE, environment

LPE = ('RenderOutput("/rhea_emission") { ["file_name"]="rhea.exr", ["result"]=8, ["lpe"]="C[<L.>O]", '
       '["channel_name"]="rhea_emission", ["channel_format"]=0 }\n'
       'RenderOutput("/rhea_direct") { ["file_name"]="rhea.exr", ["result"]=8, ["lpe"]="C[DGS][<L.>O]", '
       '["channel_name"]="rhea_direct", ["channel_format"]=0 }\n'
       # The surface's colour at the first hit, for demodulated light (rhea_engine.cc demod).
       'RenderOutput("/rhea_albedo") { ["file_name"]="rhea.exr", ["result"]=7, ["material_aov"]="albedo", '
       '["channel_name"]="rhea_albedo", ["channel_format"]=0 }\n'
       # The nearest and farthest first-hit camera depths at each pixel (state variable 11, math filters min and max):
       # the GPU's verification of persistent probes (persistent.h verify).
       'RenderOutput("/rhea_depth_min") { ["file_name"]="rhea.exr", ["result"]=3, ["state_variable"]=11, ["math_filter"]=2, '
       '["channel_name"]="rhea_depth_min", ["channel_format"]=0 }\n'
       'RenderOutput("/rhea_depth_max") { ["file_name"]="rhea.exr", ["result"]=3, ["state_variable"]=11, ["math_filter"]=3, '
       '["channel_name"]="rhea_depth_max", ["channel_format"]=0 }\n')

FILMS = ('phase1', 'recon', 'phase2', 'direct2', 'final', 'classes', 'cells', 'samples2', 'leaves', 'geomerr')


def run(engine, ptx_build, scene, out, options, extra=None, reference=None, runtime=REFERENCE, assets=None):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    override = out / 'rhea-override.rdla'
    override.write_text((Path(extra).read_text(encoding='utf-8') if extra else '') + LPE, encoding='utf-8')
    exe = json.loads((Path(engine) / 'build.json').read_text(encoding='utf-8'))['exe']
    ptx = json.loads((Path(ptx_build) / 'build.json').read_text(encoding='utf-8'))['ptx']
    # The asset root: textures must lie under it (the scene's folder unless --assets names another).
    args = [exe, Path(scene).resolve(), runtime, ptx, Path(assets).resolve() if assets else Path(scene).resolve().parent, out] + list(options) + ['override=' + str(override)]
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
        raise SystemExit('rhea_engine failed: ' + r.stderr[-3000:])
    report = json.loads(lines[-1])
    report['exit_code'] = r.returncode
    w, h = report['width'], report['height']
    for name in FILMS:
        f = read_rgba(out / (name + '.rgba'), w, h)
        linear = name in ('classes', 'cells', 'samples2', 'leaves', 'geomerr')
        write_png(out / (name + '.png'), f, w, h, linear=linear)
    for name in ('depth', 'depth-true'):
        write_png(out / (name + '.png'), read_rgba(out / (name + '.rgba'), w, h), w, h, linear=True)
    xpu2 = sorted(report.get('xpu2', {}), key=int)
    for n in xpu2:
        write_png(out / f'xpu2-{n}.png', read_rgba(out / f'xpu2-{n}.rgba', w, h), w, h)
    # Timed runs only (run 0 warms up): the median.
    median = lambda v: sorted(v)[len(v) // 2] if v else None
    timed = [r for r in report.get('runs', []) if not r.get('warm_up')]
    report['median_seconds'] = {'engine': median([r['total_seconds'] for r in timed]),
                                'phase1': median([r['phase1_seconds'] for r in timed]),
                                'phase2': median([r['phase2_seconds'] for r in timed]),
                                'region': median([r['region_seconds'] for r in timed]),
                                'geometry': median([r['geometry_seconds'] for r in timed])}
    for n in xpu2:
        report['median_seconds'][f'xpu2-{n}'] = median([r['seconds'] for r in report['xpu2'][n] if not r.get('warm_up')])
    if reference:
        ref = read_rgba(reference, w, h)
        names = ['final', 'phase2', 'recon'] + [f'xpu2-{n}' for n in xpu2]
        if (out / 'sequence-final.rgba').exists():
            names.append('sequence-final')
        # A still camera's running averages (accumulate=1): Rhea's and XPU2's, at 1, 2, 4, ... frames.
        for prefix in ('accum-', 'naive-', 'xpu2-accum-'):
            names += sorted((f.stem for f in out.glob(prefix + '*.rgba') if f.stem[len(prefix):].isdigit()), key=lambda n: int(n.split('-')[-1]))
        report['errors'] = {n: errors(read_rgba(out / (n + '.rgba'), w, h), ref, w, h) for n in names}
    # A moving camera's frames (seq_ref): Rhea's and XPU2's against an XPU2 frame of that camera at many samples.
    for k in report.get('sequence', {}).get('scored', []):
        mref = read_rgba(out / f'move-ref-{k}.rgba', w, h)
        for who in ('rhea', 'xpu2'):
            f = read_rgba(out / f'move-{who}-{k}.rgba', w, h)
            report.setdefault('errors', {})[f'move-{who}-{k}'] = errors(f, mref, w, h)
            write_png(out / f'move-{who}-{k}.png', f, w, h)
        write_png(out / f'move-ref-{k}.png', mref, w, h)
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
    p.add_argument('--assets', type=Path, help='the asset root, where the textures are (default: the folder of the scene)')
    p.add_argument('options', nargs='*')
    a = p.parse_args()
    report = run(a.engine, a.ptx_build, a.scene, a.output, a.options, a.extra, a.reference, a.runtime, a.assets)
    keep = {k: report[k] for k in ('median_seconds', 'probes', 'leaf_states', 'geometric_error', 'piece_bytes', 'classes', 'phase2_samples_per_pixel', 'phase1_probe_samples_per_pixel') if k in report}
    keep['relative_mse'] = {n: round(e['relative_mse'], 7) for n, e in report.get('errors', {}).items()}
    keep['block_error'] = {n: round(e['block_error'], 6) for n, e in report.get('errors', {}).items()}
    keep['mean_ratio'] = {n: round(e['mean_ratio'], 5) for n, e in report.get('errors', {}).items()}
    print(json.dumps(keep, indent=2))


if __name__ == '__main__':
    main()
