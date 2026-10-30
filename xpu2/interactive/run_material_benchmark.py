"""The shading library on both renderers (SHADING.md): every material case of a fixture.

run_material_benchmark.py --build <build_async output>/build.json --fixtures <make_material_scenes report> --output <new folder>
                          [--cases ...]

For each case: original XPU (the pinned 0.4.2 runtime, fresh processes) at 1024 samples a pixel as the reference, and
at 64 samples (one warm-up, three timed, MoonRay's MCRT time); the asynchronous renderer at 64 samples (one warm-up,
three timed) and at 1024, twice, with two seeds. The gates are run_paths_benchmark.py's: at 64 samples every XPU2
image's relative MSE against an independent XPU 1024-sample image (frame 1) is at or below XPU's own (alpha within .015); at 1024 samples
XPU2 converges to XPU (8x8 block mean .015, alpha .015, maximum pixel within .08 or 1.25 times XPU2's own noise)."""
import argparse
import json
import shutil
import statistics
from pathlib import Path

from reference_repeatability import save, values, stats
from reference_runtime import verify
from run_m0 import guard
from run_paths_benchmark import GATES, HERE, TR, probe, xpu
from run_speed_comparison import metric


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cases', nargs='+')
    p.add_argument('--threads', type=int, default=12)
    p.add_argument('--reuse', type=Path, nargs='*', default=[],
                   help="earlier benchmarks (with their fixtures' report beside as 'fixtures' in their report) whose MoonRay "
                        "images and times a case takes when its scenes are unchanged")
    p.add_argument('--reference-mode', default='xpu', choices=['xpu', 'scalar', 'vector'],
                   help="MoonRay's execution mode for its images (scalar where XPU cannot render the cases)")
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
    fixtures = json.loads(a.fixtures.read_text())['cases']
    report = {'status': 'incomplete', 'gates': GATES, 'build': str(a.build), 'fixtures': str(a.fixtures),
              'reference_mode': a.reference_mode, 'cases': {}}
    t = a.threads

    # MoonRay's renders do not depend on XPU2: a case whose scenes are the same text as in an earlier benchmark (its
    # fixture folder aside) takes that benchmark's MoonRay images and times.
    def scene_text(path, root):
        return Path(path).read_text(encoding='utf-8').replace(str(root), '<root>').replace(str(root).replace('\\', '/'), '<root>')
    earlier = []
    for folder in a.reuse:
        r = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
        if r.get('reference_mode', 'xpu') != a.reference_mode:
            continue
        old = json.loads(Path(r['fixtures']).resolve().read_text(encoding='utf-8'))['cases']
        earlier.append((folder, Path(r['fixtures']).resolve().parent, old))
    new_root = a.fixtures.resolve().parent

    def reusable(name, fixture):
        for folder, old_root, old in earlier:
            if name not in old or not (folder / name / 'xpu-64-3' / 'beauty.rgba').exists():
                continue
            if all(scene_text(fixture['scenes'][g], new_root) == scene_text(old[name]['scenes'][g], old_root) for g in ('8', '32')):
                return folder / name
        return None

    def moonray(source, scene, settings, folder):
        if source is None:
            return xpu(runtime, scene, settings, folder, t, decoder, a.reference_mode)
        shutil.copytree(source / folder.name, folder)
        return values((folder / 'beauty.rgba').read_bytes()), stats(folder / 'stats.csv')['Mcrt time (s)']
    try:
        for name in a.cases or list(fixtures):
            fixture = fixtures[name]
            width, height = fixture['resolution']
            scenes = {int(k): Path(v) for k, v in fixture['scenes'].items()}
            d = out / name
            d.mkdir()
            settings = d / 'none.rdla'
            settings.write_text('-- the scene as it is\n', encoding='utf-8')
            source = reusable(name, fixture)
            reference, reference_seconds = moonray(source, scenes[32], settings, d / 'xpu-1024')
            # The 64-sample errors are measured against an independent XPU reference (frame 1): XPU's own
            # 1024-sample image shares its random sequences with its 64-sample one and so flatters it.
            frame1 = d / 'frame1.rdla'
            frame1.write_text(settings.read_text(encoding='utf-8') + 'SceneVariables { ["frame"]=1 }\n', encoding='utf-8')
            independent, _ = moonray(source, scenes[32], frame1, d / 'xpu-1024-frame1')
            x = [moonray(source, scenes[8], settings, d / f'xpu-64-{i}') for i in range(4)]
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
                'moonray_reused_from': str(source) if source else None,
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
            print('%s: XPU %.3f s (error %.6f), XPU2 %.4f s (error %.6f): %.1f%% less time; 1024 max pixel %.4f (own noise %.4f) '
                  'block %.5f -> %s' % (name, case['xpu_median'], xpu_error, case['async_median'], errors[1]['relative_mse'],
                                       100 * case['time_saved'], he['max_pixel'], noise, he['max_block_mean'],
                                       case['all_gates_passed']), flush=True)
        report['status'] = 'passed' if all(c['all_gates_passed'] for c in report['cases'].values()) else 'failed'
    except Exception as error:
        report['status'] = 'error'
        report['error'] = str(error)
        raise
    finally:
        save(out / 'report.json', report)


if __name__ == '__main__':
    main()
