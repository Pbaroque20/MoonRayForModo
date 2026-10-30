"""Isolate one GPU algebra change. Numerical differences remain failures, not new tolerances."""
import argparse
import datetime
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from xpu2.reference import digest_file, inventory, verify
from xpu2.images import read_rgba, compare_rgba
from xpu2_repeatability import successful, gpu_identity
from xpu2_native_light_lazy_probe import competing_renderers
from xpu2_native_resident_probe import configuration, profiles
from xpu2_native_material_admission_probe import require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('build', 'reference', 'exact-ptx', 'shortcut-ptx', 'light-ptx', 'scene', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=0, choices=range(0, 6),
                        help='Zero: correctness only; positive: warmup then rotated rounds.')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='incomplete', runs=[], threads=1,
                  gate=dict(absolute=1e-6, relative=1e-6),
                  scope='Rough diffuse angle round-trip only; unchanged sampling directions, scheduling and transport. No full material or multiworker qualification.')
    def save():
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    try:
        build = args.build.resolve()
        runtime, reference = build / 'runtime', args.reference.resolve()
        manifest = json.loads((build / 'report.json').read_text())
        require(manifest['status'] == 'built', 'Incomplete native build')
        require(digest_file(runtime / 'librendering_rndr.dll') == manifest['dll_sha256'], 'Native DLL drift')
        sources = {**manifest['source_hashes'], **manifest['native_hashes']}
        pinned = [build / 'report.json', Path(__file__), args.scene.resolve(), args.light_ptx.resolve()]
        kernels = dict(exact=args.exact_ptx.resolve(), shortcut=args.shortcut_ptx.resolve())
        for label, ptx in kernels.items():
            record = json.loads((ptx.parent / 'report.json').read_text())
            require(record['status'] == 'built' and digest_file(ptx) == record['ptx_sha256'], 'PTX drift')
            expected = 'rough diffuse clamped-dot' if label == 'shortcut' else 'unchanged native math'
            require(record['experiment'] == expected, 'Wrong math variant')
            for name, sha in record['sources'].items():
                require(digest_file(ROOT / 'xpu2' / name) == sha, 'Kernel source drift')
                sources[str(ROOT / 'xpu2' / name)] = sha
            require(digest_file(ROOT / 'tools/xpu2_math_shortcut_ptx.py') == record['compiler_sha256'], 'Compiler drift')
            require(digest_file(ptx.parent / 'film.cu') == record['generated_source_sha256'], 'Generated CUDA drift')
            pinned.extend([ptx, ptx.parent / 'report.json', ptx.parent / 'film.cu'])
        # Pin imported project helpers too; never reinterpret a moving probe as the same experiment.
        for module in tuple(sys.modules.values()):
            filename = getattr(module, '__file__', None)
            if filename:
                path = Path(filename).resolve()
                if path.is_relative_to(ROOT) and path.suffix == '.py':
                    pinned.append(path)
        for path in pinned:
            sources[str(path)] = digest_file(path)
        for path, sha in sources.items():
            require(digest_file(Path(path)) == sha, 'Source drift: ' + path)
        locked = {str(rt): inventory(rt) for rt in (runtime, reference)}
        identity = gpu_identity()
        report.update(source_hashes=sources, gpu=identity, repeats=args.repeats)
        scene = out / 'scene.rdla'
        scene.write_bytes(args.scene.read_bytes())
        order = ('reference', 'exact', 'shortcut')
        runs = [(0, label) for label in order]
        for n in range(args.repeats):
            offset = n % len(order)
            runs.extend((n + 1, label) for label in order[offset:] + order[:offset])
        baseline = None
        for round_number, label in runs:
            folder = out / (str(round_number) + '-' + label)
            folder.mkdir()
            rt = reference if label == 'reference' else runtime
            env = configuration(rt, folder, kernels.get(label, kernels['exact']), args.light_ptx.resolve(),
                                'reference' if label == 'reference' else 'control')
            if label != 'reference':
                env['XPU2_NATIVE_FAMILY_PROFILE'] = str(folder / 'families.jsonl')
            before = competing_renderers()
            require(not args.repeats or not before, 'Timing blocked by competing renderer')
            print(round_number, label, flush=True)
            started = datetime.datetime.now(datetime.timezone.utc).isoformat()
            start = time.perf_counter()
            with (folder / 'render.log').open('w') as log:
                process = subprocess.Popen([str(rt / 'moonray.exe'), '-in', str(scene), '-out',
                    str(folder / 'beauty.exr'), '-exec_mode', 'xpu', '-threads', '1', '-info',
                    '-stats', str(folder / 'stats.csv')], cwd=folder, env=env, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    process.wait(timeout=600)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=10)
            elapsed = time.perf_counter() - start
            after = competing_renderers()
            result = successful('xpu', 1, process.returncode,
                (folder / 'render.log').read_text(errors='replace'),
                (folder / 'stats.csv').read_text(errors='replace') if (folder / 'stats.csv').exists() else '',
                (folder / 'beauty.exr').exists())
            row = dict(round=round_number, label=label, seconds=elapsed, started_utc=started,
                       renderer_pid=process.pid, execution=result, activity_before=before, activity_after=after,
                       configuration={k:v for k,v in env.items() if k.startswith('XPU2_')})
            report['runs'].append(row)
            save()
            require(result['passed'], 'Render failed: ' + label)
            require(not args.repeats or not after, 'Timing contaminated')
            image = read_rgba(rt, folder / 'beauty.exr', folder, 'raw', env)
            if baseline is None:
                baseline = image
            row['comparison'] = compare_rgba(baseline, image, absolute=1e-6, relative=1e-6)
            row['exact_parity'] = not row['comparison']['exactly_different_pixels']
            save()
            if label != 'shortcut':
                require(row['exact_parity'], 'Unchanged control/reference lost exact parity')
            if label != 'reference':
                row['profiles'] = profiles(folder, 'control', env)
                families = [json.loads(line) for line in (folder / 'families.jsonl').read_text().splitlines()]
                require(len(families) == 1 and families[0]['rough_diffuse'] > 0, 'No rough diffuse GPU coverage')
                require(sum(families[0].values()) == row['profiles']['gpu']['gpu_accepted'], 'GPU family accounting')
                row['families'] = families[0]
            save()
        report['summary'] = {}
        for label in order:
            rows = [r for r in report['runs'] if r['label'] == label and r['round'] > 0]
            if rows:
                values = [r['execution']['renderer_timings_seconds']['Mcrt time'] for r in rows]
                report['summary'][label] = dict(mcrt_median=statistics.median(values),
                    mcrt_min=min(values), mcrt_max=max(values))
        for rt in (runtime, reference):
            verify(rt, locked[str(rt)])
        for path, sha in sources.items():
            require(digest_file(Path(path)) == sha, 'Source drift after run: ' + path)
        require(gpu_identity() == identity, 'GPU identity drift')
        candidate = [r for r in report['runs'] if r['label'] == 'shortcut']
        report['exact_parity'] = all(r['exact_parity'] for r in candidate)
        report['tolerance_parity'] = all(r['comparison']['status'] == 'passed' for r in candidate)
        report['status'] = 'passed' if report['exact_parity'] else 'image_differences'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
    save()
    print(report['status'], report.get('error', ''), flush=True)
    return {'passed':0, 'image_differences':2}.get(report['status'], 1)


if __name__ == '__main__':
    raise SystemExit(main())
