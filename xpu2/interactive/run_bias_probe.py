"""Where two renderers' converged images differ (a debugging aid, not a gate).

run_bias_probe.py --build <build_async output>/build.json --fixtures <make_material_scenes report> --case <case>
                  --output <new folder> [--settings 'SceneVariables { ... }' ...]

For each settings override (an RDLA snippet read after the scene): original XPU at 1024 samples a pixel, frames 0 and
1, and the asynchronous renderer at 1024 with two seeds; prints the signed mean difference XPU2 - XPU in per mille of
the image, by 20-pixel blocks, beside XPU's own frame-to-frame difference."""
import argparse
import json
from pathlib import Path

from reference_repeatability import save, values
from reference_runtime import verify
from run_m0 import guard
from run_paths_benchmark import HERE, TR, probe, xpu


def grey(raw):
    return [(raw[4 * i] + raw[4 * i + 1] + raw[4 * i + 2]) / 3 for i in range(len(raw) // 4)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build', type=Path, required=True)
    p.add_argument('--fixtures', type=Path, required=True)
    p.add_argument('--case', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--settings', nargs='+', default=['-- the scene as it is'])
    p.add_argument('--threads', type=int, default=12)
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runtime = TR / 'interactive-reference-042'
    verify(runtime, json.loads((HERE / 'reference-lock.json').read_text()))
    guard()
    build = json.loads(a.build.read_text())
    decoder = Path(json.loads((TR / 'interactive-prototype-build-20261022qmc/build.json').read_text())['exe'])
    fixture = json.loads(a.fixtures.read_text())['cases'][a.case]
    width, height = fixture['resolution']
    scene = Path(fixture['scenes']['32'])
    report = {'case': a.case, 'variants': []}
    for n, text in enumerate(a.settings):
        d = out / f'variant-{n}'
        d.mkdir()
        settings = d / 'settings.rdla'
        settings.write_text(text + '\n', encoding='utf-8')
        frame1 = d / 'frame1.rdla'
        frame1.write_text(text + '\nSceneVariables { ["frame"]=1 }\n', encoding='utf-8')
        ref, _ = xpu(runtime, scene, settings, d / 'xpu-1024', a.threads, decoder)
        ind, _ = xpu(runtime, scene, frame1, d / 'xpu-1024-frame1', a.threads, decoder)
        h0 = probe(build, scene, runtime, d / 'xpu2-1024', a.threads, 1, settings)
        h1 = probe(build, scene, runtime, d / 'xpu2-1024-seed17', a.threads, 1, settings, 17)
        r, i = grey(ref), grey(ind)
        x0, x1 = grey(values(Path(h0['runs'][0]['raw_file']).read_bytes())), grey(values(Path(h1['runs'][0]['raw_file']).read_bytes()))
        total = sum(r) / len(r)
        bias = (sum(x0) + sum(x1)) / 2 / len(r) - total
        own = sum(i) / len(i) - total
        print('variant %d %r: mean %.5f, XPU2 - XPU %+.3f per mille (XPU frame 1 - frame 0 %+.3f)' %
              (n, text, total, 1000 * bias / total, 1000 * own / total), flush=True)
        B = 20
        for y0 in range(0, height, B):
            row = []
            for xb in range(0, width, B):
                idx = [y * width + x for y in range(y0, min(y0 + B, height)) for x in range(xb, min(xb + B, width))]
                m = sum(r[k] for k in idx) / len(idx)
                b = sum((x0[k] + x1[k]) / 2 - r[k] for k in idx) / len(idx)
                row.append('%5.1f' % (1000 * b / m if m > 1e-4 else 0.0))
            print('  ' + ' '.join(row), flush=True)
        report['variants'].append({'settings': text, 'mean': total, 'bias_per_mille': 1000 * bias / total,
                                   'xpu_frame_difference_per_mille': 1000 * own / total})
        save(out / 'report.json', report)


if __name__ == '__main__':
    main()
