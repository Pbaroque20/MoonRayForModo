"""MoonRay's lights and path tracer on both renderers (PATH_TRACER.md, phase 1).

run_paths_benchmark.py --build <build_async output>/build.json --output <new folder> [--cases ...]

Each case is a fixture of the published benchmark with lights and integrator settings read from an override after
the scene. For each: original XPU (the pinned 0.4.2 runtime, fresh processes) at 1024 samples a pixel as the
reference, and at 64 samples (one warm-up, three timed, MoonRay's MCRT time); the asynchronous renderer at 64
samples (one warm-up, three timed) and at 1024, twice, with two seeds. Gates: at 64 samples every XPU2 image's
relative MSE against XPU's 1024-sample image is at or below XPU's own 64-sample error (and alpha within .015); at
1024 samples XPU2 converges to XPU: maximum 8x8 block mean .015, alpha .015, and a maximum pixel difference within
.08 or, where lights make pixels bright and noisy, within 1.25 times the difference between XPU2's two seeds (its
own noise at 1024 samples)."""
import argparse
import json
import statistics
import subprocess
from pathlib import Path

from fallback import environment, execution
from prototype_wire import decode
from reference_repeatability import save, values, stats
from reference_runtime import verify
from run_speed_comparison import metric
from run_material_progressive import call
from run_m0 import guard

HERE = Path(__file__).resolve().parent
TR = HERE.parents[1] / 'test-results'
GATES = {'high_spp_max_pixel': .08, 'high_spp_max_8x8_block_mean': .015, 'alpha_max': .015}

ENV = 'EnvLight("/sky")'
RECT = 'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 2,2,6,1), ["width"]=3.0, ["height"]=3.0, ["intensity"]=0.05 }'
DISK = 'DiskLight("/fill") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, -2,-1,5,1), ["radius"]=1.0, ["intensity"]=0.05, ["color"]=Rgb(0.6,0.8,1.0) }'
SPHERE = 'SphereLight("/bulb") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,3,3,1), ["radius"]=0.5, ["intensity"]=0.05, ["color"]=Rgb(1.0,0.7,0.4) }'
# Turned 40 degrees about X: it shines down and toward +Y.
DISTANT = 'DistantLight("/sun") { ["node_xform"]=Mat4(1,0,0,0, 0,0.766044,0.642788,0, 0,-0.642788,0.766044,0, 0,0,0,1), ["angular_extent"]=5.0, ["intensity"]=1.0 }'
TWO_SIDED = 'RectLight("/panel") { ["node_xform"]=Mat4(1,0,0,0, 0,0,1,0, 0,-1,0,0, 0,1.5,1.5,1), ["width"]=2.0, ["height"]=1.0, ["intensity"]=0.05, ["sidedness"]=2 }'

SPOT = 'SpotLight("/spot") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, -2,2,8,1), ["lens_radius"]=0.5, ["outer_cone_angle"]=40.0, ["inner_cone_angle"]=20.0, ["intensity"]=0.05 }'


def lights(*defs):
    names = [d.split(' {')[0] if ' {' in d else d for d in defs]
    return '\n'.join(d for d in defs if ' {' in d) + '\nLightSet("/lights") { ' + ', '.join(names) + ' }\n'


CASES = {
    'rect': lights(ENV, RECT),
    'disk': lights(ENV, DISK),
    'sphere': lights(ENV, SPHERE),
    'distant': lights(DISTANT),
    'two-sided': lights(ENV, TWO_SIDED),
    'spot': lights(ENV, SPOT),
    'all': lights(ENV, RECT, DISK, SPHERE, DISTANT, SPOT),
    # The Cornell box (make_paths_scenes.py) brings its own light: bounces, then MoonRay's default settings.
    'bounces': '',
    'bounces-defaults': 'SceneVariables { ["light_samples"]=2, ["bsdf_samples"]=2, ["max_depth"]=5, ["max_diffuse_depth"]=2,'
                        ' ["russian_roulette_threshold"]=0.0375, ["sample_clamping_value"]=10.0 }\n',
    'all-defaults': lights(ENV, RECT, DISK, SPHERE, DISTANT, SPOT) +
                    'SceneVariables { ["light_samples"]=2, ["bsdf_samples"]=2 }\n',
}


def xpu(runtime, scene, settings, folder, threads, decoder, mode='xpu'):
    """MoonRay's render of a scene: XPU (checked to have run on the GPU), or another execution mode where XPU cannot
    render the scene (MoonRay's vector glitter overflows a Windows thread's stack)."""
    guard()
    folder.mkdir()
    cmd = [str(runtime / 'moonray.exe'), '-in', str(scene), '-in', str(settings), '-out', str(folder / 'beauty.exr'),
           '-exec_mode', mode, '-threads', str(threads), '-info', '-stats', str(folder / 'stats.csv')]
    with (folder / 'render.log').open('wb') as log:
        p = subprocess.Popen(cmd, cwd=folder, env=environment(runtime, folder), stdout=log, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            code = p.wait(timeout=3600)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
    ex = execution((folder / 'render.log').read_text(errors='replace'), (folder / 'stats.csv').read_text(), threads)
    if mode != 'xpu':
        ex = {'requested_mode': mode, 'threads': ex['threads'], 'passed': ex['threads'] == threads}
    if code or not ex['passed']:
        raise RuntimeError('Invalid original %s run (exit %#x): %s' % (mode, code & 0xffffffff, ex))
    guard()
    _, raw = decode(decoder, runtime, folder / 'beauty.exr', folder)
    (folder / 'beauty.rgba').write_bytes(raw)
    return values(raw), stats(folder / 'stats.csv')['Mcrt time (s)']


def probe(build, scene, runtime, out, threads, repeats, settings, seed='-'):
    out.mkdir(parents=True)
    args = [build['exe'], scene, runtime, build['ptx'], scene.parent / 'assets', out, threads, repeats, 2,
            64, 4, 10, seed, '-', settings]
    guard()
    row = json.loads(call(args, runtime, out, 'async', timeout=3600))
    guard()
    if row.get('status') != 'passed':
        raise RuntimeError('Asynchronous render failed: ' + str(row))
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scene', default='gallery-dense')
    p.add_argument('--fixtures', type=Path, default=TR / 'interactive-large-scenes-20261022/report.json')
    p.add_argument('--cases', nargs='+', default=[c for c in CASES if not c.startswith('bounces')])
    p.add_argument('--threads', type=int, default=12)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runtime = TR / 'interactive-reference-042'
    verify(runtime, json.loads((HERE / 'reference-lock.json').read_text()))
    guard()
    build = json.loads(a.build.read_text())
    if build['status'] != 'passed':
        raise SystemExit('Build did not pass')
    decoder = Path(json.loads((TR / 'interactive-prototype-build-20261022qmc/build.json').read_text())['exe'])
    fixtures = json.loads(a.fixtures.read_text())
    fixture = fixtures['cases'][a.scene]
    width, height = fixture['resolution']
    scenes = {int(k): Path(v) for k, v in fixture['scenes'].items()}
    report = {'status': 'incomplete', 'gates': GATES, 'build': str(a.build), 'scene': a.scene, 'cases': {}}
    t = a.threads
    try:
        for name in a.cases:
            d = out / name
            d.mkdir()
            settings = d / 'lights.rdla'
            settings.write_text(CASES[name], encoding='utf-8')
            reference, reference_seconds = xpu(runtime, scenes[32], settings, d / 'xpu-1024', t, decoder)
            # The 64-sample errors are measured against an independent XPU reference (frame 1): XPU's own
            # 1024-sample image shares its random sequences with its 64-sample one and so flatters it.
            frame1 = d / 'frame1.rdla'
            frame1.write_text(settings.read_text(encoding='utf-8') + 'SceneVariables { ["frame"]=1 }\n', encoding='utf-8')
            independent, _ = xpu(runtime, scenes[32], frame1, d / 'xpu-1024-frame1', t, decoder)
            x = [xpu(runtime, scenes[8], settings, d / f'xpu-64-{i}', t, decoder) for i in range(4)]
            xpu_error = min(metric(img, independent, width, height)['relative_mse'] for img, _ in x[1:])
            xpu_error_own = min(metric(img, reference, width, height)['relative_mse'] for img, _ in x[1:])
            native = probe(build, scenes[8], runtime, d / 'xpu2-64', t, 4, settings)
            errors = [metric(values(Path(r['raw_file']).read_bytes()), independent, width, height) for r in native['runs']]
            high = probe(build, scenes[32], runtime, d / 'xpu2-1024', t, 1, settings)
            other = probe(build, scenes[32], runtime, d / 'xpu2-1024-seed17', t, 1, settings, 17)
            first = values(Path(high['runs'][0]['raw_file']).read_bytes())
            he = metric(first, reference, width, height)
            noise = metric(first, values(Path(other['runs'][0]['raw_file']).read_bytes()), width, height)['max_pixel']
            case = report['cases'][name] = {
                'xpu_reference_seconds': reference_seconds,
                'xpu_mcrt_seconds': [s for _, s in x], 'xpu_median': statistics.median([s for _, s in x][1:]),
                'xpu_error': xpu_error, 'xpu_error_own_reference': xpu_error_own,
                'reference_noise': metric(reference, independent, width, height)['relative_mse'],
                'async_seconds': [r['sampling_seconds'] for r in native['runs']],
                'async_errors': errors, 'async_1024_error': he, 'async_1024_seconds': high['runs'][0]['sampling_seconds'],
                'async_1024_noise_max_pixel': noise,
                'gpu_share': [r['gpu_share'] for r in native['runs']]}
            case['async_median'] = statistics.median(case['async_seconds'][1:])
            case['time_saved'] = 1 - case['async_median'] / case['xpu_median']
            case['meets_xpu'] = all(e['relative_mse'] <= xpu_error and e['alpha'] <= GATES['alpha_max'] for e in errors[1:])
            case['converges'] = (he['max_pixel'] <= max(GATES['high_spp_max_pixel'], 1.25 * noise) and
                                 he['max_block_mean'] <= GATES['high_spp_max_8x8_block_mean'] and he['alpha'] <= GATES['alpha_max'])
            case['all_gates_passed'] = case['meets_xpu'] and case['converges']
            save(out / 'report.json', report)
            print('%s: XPU %.3f s (error %.6f), XPU2 %.4f s (error %.6f): %.1f%% less time; 1024 max pixel %.4f (own noise %.4f) block %.5f -> %s' % (
                name, case['xpu_median'], xpu_error, case['async_median'], errors[1]['relative_mse'], 100 * case['time_saved'],
                he['max_pixel'], noise, he['max_block_mean'], case['all_gates_passed']), flush=True)
        report['status'] = 'passed' if all(c['all_gates_passed'] for c in report['cases'].values()) else 'failed'
    except Exception as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        save(out / 'report.json', report)


if __name__ == '__main__':
    main()
