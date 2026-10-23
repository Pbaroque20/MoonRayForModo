"""Render-time comparison of the asynchronous renderer with original XPU (spec VER-11).

run_async_benchmark.py --build <build_async output>/build.json --output <new folder> [--scenes ...]

For each synthetic fixture: fresh pinned XPU (one warm-up, three timed, MoonRay's
own MCRT time) and the asynchronous renderer (one warm-up, three timed, render
wall time from first claim to the merged film), paired at 12 and 1 threads with
nothing else rendering. A timing counts only if every image passes the frozen
quality gates: relative MSE at or below XPU's own 64-sample error against the
1024-sample reference, alpha within .015, held-out seeds, a 1024-sample
convergence check (.08 pixel / .015 8x8 block / .015 alpha), and the device
split (VER-3): CPU-only and GPU-only renders each pass, and agree with each
other."""
import argparse
import json
import statistics
import time
from pathlib import Path

from reference_runtime import verify
from reference_repeatability import save, values, run_reference
from run_speed_comparison import metric
from run_material_progressive import call
from run_m0 import guard

HERE = Path(__file__).resolve().parent
TR = HERE.parents[1] / 'test-results'
SEEDS = (17, 47, 101, 151)
GATES = {'high_spp_max_pixel': .08, 'high_spp_max_8x8_block_mean': .015, 'alpha_max': .015}


def probe(build, scene, runtime, out, threads, repeats, mode, seed=None):
    out.mkdir(parents=True)
    args = [build['exe'], scene, runtime, build['ptx'], scene.parent / 'assets', out, threads, repeats, mode]
    if seed is not None:
        args += [64, 4, 6, seed, 3]
    guard()
    row = json.loads(call(args, runtime, out, 'async', timeout=1800))
    guard()
    if row.get('status') != 'passed':
        raise RuntimeError('Asynchronous render failed: ' + str(row))
    return row


def score(row, ref, width, height, target):
    for run in row['runs']:
        run['error'] = metric(values(Path(run['raw_file']).read_bytes()), ref, width, height)
        run['meets_target'] = run['error']['relative_mse'] <= target and run['error']['alpha'] <= GATES['alpha_max']
    return all(run['meets_target'] for run in row['runs'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--scenes', nargs='+', default=['gallery-dense', 'workshop-detail'])
    p.add_argument('--threads', type=int, nargs='+', default=[12, 1])
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
    report = {'status': 'incomplete', 'production_qualified': False, 'gates': GATES, 'build': str(a.build),
              'cases': {}}
    try:
        for name in a.scenes:
            fixture, old = fixtures['cases'][name], prior['cases'][name]
            width, height = fixture['resolution']
            scenes = {int(k): Path(v) for k, v in fixture['scenes'].items()}
            ref = values((Path(old['converged_reference']['folder']) / 'beauty.rgba').read_bytes())
            target = old['target']
            case = report['cases'][name] = {'target': target, 'timing': {}}
            d = out / name
            d.mkdir()
            for t in a.threads:
                xpu = []
                for i in range(4):
                    _, row = run_reference(runtime, scenes[8], d / f'xpu-t{t}-{i}', t, decoder, timeout=900)
                    xpu.append(row['stats']['Mcrt time (s)'])
                native = probe(build, scenes[8], runtime, d / f'async-t{t}', t, 4, 2)
                passed = score(native, ref, width, height, target)
                times = [r['sampling_seconds'] for r in native['runs']]
                entry = case['timing'][str(t)] = {
                    'xpu_mcrt_seconds': xpu, 'xpu_median': statistics.median(xpu[1:]),
                    'async_seconds': times, 'async_cold_seconds': times[0], 'async_median': statistics.median(times[1:]),
                    'gpu_share': [r['gpu_share'] for r in native['runs']],
                    'errors': [r['error'] for r in native['runs']], 'meets_target': passed,
                    'prepare_seconds': native['prepare_seconds']}
                entry['time_saved'] = 1 - entry['async_median'] / entry['xpu_median']
                save(out / 'report.json', report)
                print(name, t, 'XPU %.4f s, async %.4f s (cold %.4f s): %.1f%% less time, quality %s' % (
                    entry['xpu_median'], entry['async_median'], times[0], 100 * entry['time_saved'], passed), flush=True)
            # Device split: each device alone renders the same image statistically.
            split = case['device_split'] = {}
            images = {}
            for mode, label in ((0, 'cpu'), (1, 'gpu')):
                row = probe(build, scenes[8], runtime, d / f'split-{label}', 12, 1, mode)
                split[label + '_meets_target'] = score(row, ref, width, height, target)
                split[label + '_error'] = row['runs'][0]['error']
                images[label] = values(Path(row['runs'][0]['raw_file']).read_bytes())
            between = metric(images['cpu'], images['gpu'], width, height)
            split['cpu_vs_gpu'] = between
            split['agree'] = between['max_block_mean'] <= GATES['high_spp_max_8x8_block_mean'] and between['alpha'] <= GATES['alpha_max']
            # Held-out seeds.
            seeds = case['heldout_seeds'] = {}
            for seed in SEEDS:
                row = probe(build, scenes[8], runtime, d / f'seed-{seed}', 12, 1, 2, seed)
                seeds[str(seed)] = {'meets_target': score(row, ref, width, height, target), 'error': row['runs'][0]['error']}
            # Convergence at 1024 samples.
            row = probe(build, scenes[32], runtime, d / 'high-1024', 12, 1, 2)
            e = metric(values(Path(row['runs'][0]['raw_file']).read_bytes()), ref, width, height)
            case['high_spp'] = {'error': e, 'seconds': row['runs'][0]['sampling_seconds'],
                                'passed': e['max_pixel'] <= GATES['high_spp_max_pixel'] and
                                e['max_block_mean'] <= GATES['high_spp_max_8x8_block_mean'] and e['alpha'] <= GATES['alpha_max']}
            case['all_gates_passed'] = (all(v['meets_target'] for v in case['timing'].values()) and
                                        split['cpu_meets_target'] and split['gpu_meets_target'] and split['agree'] and
                                        all(v['meets_target'] for v in seeds.values()) and case['high_spp']['passed'])
            save(out / 'report.json', report)
            print(name, 'device split', split['agree'], 'seeds', all(v['meets_target'] for v in seeds.values()),
                  '1024 spp', case['high_spp']['passed'], '-> all gates', case['all_gates_passed'], flush=True)
        report['status'] = 'passed' if all(c['all_gates_passed'] for c in report['cases'].values()) else 'failed'
    except Exception as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        save(out / 'report.json', report)


if __name__ == '__main__':
    main()
