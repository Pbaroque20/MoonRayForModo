"""Adaptive render-time comparison of the asynchronous renderer with original XPU.

run_async_adaptive_benchmark.py --build <build_async output>/build.json --output <new folder>
    [--scenes ...] [--threads 12 1] [--min 16] [--max 1024] [--target 10]

MoonRay's adaptive sampling (sampling_mode 2) on both renderers with the same
settings, written to an override read after each fixture scene. For each
fixture: fresh pinned XPU (one warm-up that also writes its per-pixel sample
weights, three timed, MoonRay's own MCRT time) and the asynchronous renderer
(one warm-up, three timed, render wall time to the merged film), at 12 and 1
threads with nothing else rendering. Reported for each: relative MSE against
the 1024-sample reference, alpha, and the mean samples a pixel received.

The asynchronous renderer's error trees, pass schedule and stopping rule are
MoonRay's, but its error estimate reads its own samples, so the same target
need not give the same error. When it does not, the target is lowered in
tenths until the asynchronous renderer's error is at or below XPU's lowest,
and that render's time is reported as the time to XPU's quality. A CPU-only
adaptive render checks the host path: its image must agree with the GPU's
within the device-split gate. The GPU makes its passes on the device (the pass
chain); one render with the passes made on the host instead must give every
pixel exactly the same samples."""
import argparse
import json
import os
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
from xpu2.images import pixels

HERE = Path(__file__).resolve().parent
TR = HERE.parents[1] / 'test-results'
GATES = {'high_spp_max_8x8_block_mean': .015, 'alpha_max': .015}
STEPS = (1.0, .9, .8, .7, .6, .5)  # target multipliers tried for the quality match


def override(folder, minimum, maximum, target):
    path = folder / ('adaptive-%g.rdla' % target)
    path.write_text('SceneVariables {\n    ["sampling_mode"] = 2,\n    ["min_adaptive_samples"] = %d,\n'
                    '    ["max_adaptive_samples"] = %d,\n    ["target_adaptive_error"] = %r,\n}\n' % (minimum, maximum, float(target)))
    return path


def weight_output(folder):
    path = folder / 'weight.rdla'
    path.write_text('RenderOutput("/benchmark_weight") {\n    ["result"] = "weight",\n    ["file_name"] = "weight.exr",\n'
                    '    ["channel_name"] = "weight",\n    ["channel_format"] = "float",\n}\n')
    return path


def xpu(runtime, scene, settings, folder, threads, decoder, weights=None):
    guard()
    folder.mkdir()
    cmd = [str(runtime / 'moonray.exe'), '-in', str(scene), '-in', str(settings)]
    if weights:
        cmd += ['-in', str(weights)]
    cmd += ['-out', str(folder / 'beauty.exr'), '-exec_mode', 'xpu', '-threads', str(threads), '-info',
            '-stats', str(folder / 'stats.csv')]
    with (folder / 'render.log').open('wb') as log:
        p = subprocess.Popen(cmd, cwd=folder, env=environment(runtime, folder), stdout=log, stderr=subprocess.STDOUT,
                             creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            code = p.wait(timeout=1800)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait(timeout=10)
    ex = execution((folder / 'render.log').read_text(errors='replace'), (folder / 'stats.csv').read_text(), threads)
    if code or not ex['passed']:
        raise RuntimeError('Invalid original XPU run: ' + str(ex))
    guard()
    _, raw = decode(decoder, runtime, folder / 'beauty.exr', folder)
    row = {'stats': stats(folder / 'stats.csv'), 'image': values(raw)}
    if weights:
        converted = subprocess.run([str(runtime / 'oiiotool.exe'), str(folder / 'weight.exr'), '--ch', 'weight,weight,weight',
                                    '-o', str(folder / 'weight.pfm')], env=environment(runtime, folder), capture_output=True,
                                   text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        if converted.returncode:
            raise RuntimeError('Weight conversion failed: ' + converted.stderr)
        _, w = pixels(folder / 'weight.pfm')
        row['mean_samples'] = sum(w[::3]) / len(w[::3])
    return row


def probe(build, scene, runtime, out, threads, repeats, mode, settings, seed='-', host_passes=False):
    out.mkdir(parents=True)
    args = [build['exe'], scene, runtime, build['ptx'], scene.parent / 'assets', out, threads, repeats, mode,
            64, 4, 10, seed, '-', settings]
    guard()
    if host_passes:  # XPU2_ASYNC_HOST_PASSES: the passes made on the host between the GPU's renders
        env = environment(runtime, out)
        env['XPU2_ASYNC_HOST_PASSES'] = '1'
        r = subprocess.run(list(map(str, args)), cwd=out, env=env, capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=1800, creationflags=subprocess.CREATE_NO_WINDOW)
        (out / 'async.log').write_text(r.stdout + r.stderr, encoding='utf-8')
        if r.returncode:
            raise RuntimeError('async failed: ' + r.stderr[-1400:])
        row = json.loads(r.stdout)
    else:
        row = json.loads(call(args, runtime, out, 'async', timeout=1800))
    guard()
    if row.get('status') != 'passed':
        raise RuntimeError('Asynchronous render failed: ' + str(row))
    return row


def errors(row, ref, width, height):
    return [metric(values(Path(r['raw_file']).read_bytes()), ref, width, height) for r in row['runs']]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scenes', nargs='+', default=['gallery-dense', 'workshop-detail'])
    p.add_argument('--threads', type=int, nargs='+', default=[12, 1])
    p.add_argument('--min', type=int, default=16)
    p.add_argument('--max', type=int, default=1024)
    p.add_argument('--target', type=float, default=10.0)
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
    fixtures = json.loads((TR / 'interactive-large-scenes-20261022/report.json').read_text())
    prior = json.loads((TR / 'interactive-large-benchmark-20261022/report.json').read_text())
    settings = override(out, a.min, a.max, a.target)
    weights = weight_output(out)
    report = {'status': 'incomplete', 'production_qualified': False, 'gates': GATES, 'build': str(a.build),
              'adaptive': {'min_samples': a.min, 'max_samples': a.max, 'target_error': a.target}, 'cases': {}}
    try:
        for name in a.scenes:
            fixture, old = fixtures['cases'][name], prior['cases'][name]
            width, height = fixture['resolution']
            scene = Path(fixture['scenes']['8'])
            ref = values((Path(old['converged_reference']['folder']) / 'beauty.rgba').read_bytes())
            case = report['cases'][name] = {'timing': {}}
            d = out / name
            d.mkdir()
            for t in a.threads:
                x = [xpu(runtime, scene, settings, d / f'xpu-t{t}-{i}', t, decoder, weights if i == 0 else None) for i in range(4)]
                xe = [metric(r['image'], ref, width, height) for r in x]
                native = probe(build, scene, runtime, d / f'async-t{t}', t, 4, 2, settings)
                ne = errors(native, ref, width, height)
                xpu_best = min(e['relative_mse'] for e in xe[1:])
                entry = case['timing'][str(t)] = {
                    'xpu_mcrt_seconds': [r['stats']['Mcrt time (s)'] for r in x],
                    'xpu_errors': xe, 'xpu_mean_samples': x[0]['mean_samples'],
                    'async_seconds': [r['sampling_seconds'] for r in native['runs']],
                    'async_errors': ne, 'async_mean_samples': native['runs'][0]['mean_samples'],
                    'async_passes': native['runs'][0]['adaptive_passes'],
                    'async_tree_seconds': [r['tree_seconds'] for r in native['runs']]}
                entry['xpu_median'] = statistics.median(entry['xpu_mcrt_seconds'][1:])
                entry['async_median'] = statistics.median(entry['async_seconds'][1:])
                entry['time_saved'] = 1 - entry['async_median'] / entry['xpu_median']
                entry['same_settings_meets_xpu'] = all(e['relative_mse'] <= xpu_best and e['alpha'] <= GATES['alpha_max'] for e in ne[1:])
                print(name, t, 'XPU %.4f s (error %.6f, %.1f spp), async %.4f s (error %.6f, %.1f spp): %.1f%% less time, meets XPU %s' % (
                    entry['xpu_median'], xpu_best, entry['xpu_mean_samples'], entry['async_median'], ne[1]['relative_mse'],
                    entry['async_mean_samples'], 100 * entry['time_saved'], entry['same_settings_meets_xpu']), flush=True)
                # The time to XPU's quality: the first lower target whose every timed render meets it.
                matched = None
                for k, step in enumerate(STEPS):
                    if step == 1.0:
                        row, re_ = native, ne
                    else:
                        tight = override(d, a.min, a.max, a.target * step)
                        row = probe(build, scene, runtime, d / f'async-t{t}-target{k}', t, 4, 2, tight)
                        re_ = errors(row, ref, width, height)
                    if all(e['relative_mse'] <= xpu_best and e['alpha'] <= GATES['alpha_max'] for e in re_[1:]):
                        times = [r['sampling_seconds'] for r in row['runs']]
                        matched = {'target_error': a.target * step, 'async_seconds': times, 'errors': re_,
                                   'async_median': statistics.median(times[1:]), 'mean_samples': row['runs'][0]['mean_samples']}
                        matched['time_saved'] = 1 - matched['async_median'] / entry['xpu_median']
                        break
                entry['quality_matched'] = matched
                save(out / 'report.json', report)
                if matched:
                    print(name, t, 'at XPU quality: target %g, async %.4f s (error %.6f, %.1f spp): %.1f%% less time' % (
                        matched['target_error'], matched['async_median'], matched['errors'][1]['relative_mse'],
                        matched['mean_samples'], 100 * matched['time_saved']), flush=True)
                else:
                    print(name, t, 'no target down to %g met XPU quality' % (a.target * STEPS[-1]), flush=True)
            # The pass chain: passes made on the device give every pixel the samples
            # passes made on the host do.
            host = probe(build, scene, runtime, d / 'host-passes', 12, 1, 2, settings, host_passes=True)
            same = (Path(host['runs'][0]['raw_file']).with_suffix('.counts').read_bytes() ==
                    Path(native['runs'][0]['raw_file']).with_suffix('.counts').read_bytes())
            case['chain_matches_host_passes'] = same
            case['host_passes_seconds'] = host['runs'][0]['sampling_seconds']
            print(name, 'device passes give the same samples as host passes:', same, flush=True)
            # The host path: a CPU-only adaptive frame agrees with the GPU's.
            cpu = probe(build, scene, runtime, d / 'split-cpu', 12, 1, 0, settings)
            gpu = probe(build, scene, runtime, d / 'split-gpu', 12, 1, 1, settings)
            images = [values(Path(r['runs'][0]['raw_file']).read_bytes()) for r in (cpu, gpu)]
            between = metric(images[0], images[1], width, height)
            case['device_split'] = {'cpu_seconds': cpu['runs'][0]['sampling_seconds'], 'gpu_seconds': gpu['runs'][0]['sampling_seconds'],
                                    'cpu_error': metric(images[0], ref, width, height), 'gpu_error': metric(images[1], ref, width, height),
                                    'cpu_mean_samples': cpu['runs'][0]['mean_samples'], 'gpu_mean_samples': gpu['runs'][0]['mean_samples'],
                                    'cpu_vs_gpu': between,
                                    'agree': between['max_block_mean'] <= GATES['high_spp_max_8x8_block_mean'] and between['alpha'] <= GATES['alpha_max']}
            case['all_gates_passed'] = (all(v['quality_matched'] is not None for v in case['timing'].values()) and
                                        case['device_split']['agree'] and case['chain_matches_host_passes'])
            save(out / 'report.json', report)
            print(name, 'device split agree', case['device_split']['agree'], 'cpu %.3f s gpu %.3f s' % (
                case['device_split']['cpu_seconds'], case['device_split']['gpu_seconds']), '-> all gates', case['all_gates_passed'], flush=True)
        report['status'] = 'passed' if all(c['all_gates_passed'] for c in report['cases'].values()) else 'failed'
    except Exception as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        save(out / 'report.json', report)


if __name__ == '__main__':
    main()
