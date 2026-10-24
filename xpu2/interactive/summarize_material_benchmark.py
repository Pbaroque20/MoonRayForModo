"""The material benchmark's reports as a Markdown table (PATH_TRACER.md's results).

summarize_material_benchmark.py <report.json> [<report.json> ...]

One row a case: MoonRay's time and XPU2's at 64 samples a pixel, XPU2's 64-sample error relative to MoonRay's own (1.00
is XPU's), and at 1024 samples the largest pixel and 8x8 block differences from MoonRay, then which gates passed."""
import json
import sys
from pathlib import Path


def rows(path):
    report = json.loads(Path(path).read_text(encoding='utf-8'))
    mode = report.get('reference_mode', 'xpu')
    for name, c in report['cases'].items():
        if 'async_median' not in c:
            continue
        e = c['async_errors'][1]['relative_mse']
        he = c['async_1024_error']
        gates = 'all' if c['all_gates_passed'] else ', '.join(
            g for g, ok in (('64 spp error', c['meets_xpu']), ('convergence', c['converges'])) if not ok) + ' missed'
        yield (name, mode, c['xpu_median'], c['async_median'], e / c['xpu_error'], he['max_pixel'], c['async_1024_noise_max_pixel'],
               he['max_block_mean'], gates)


def main():
    out = ['| Case | MoonRay (s) | XPU2 (s) | Error vs MoonRay | 1024 max pixel (XPU2 noise) | 1024 8x8 block | Gates |',
           '|---|---:|---:|---:|---:|---:|---|']
    for path in sys.argv[1:]:
        for name, mode, x, a, ratio, mp, noise, block, gates in rows(path):
            label = name + (' (scalar MoonRay)' if mode != 'xpu' else '')
            out.append('| %s | %.2f | %.3f | %.2f | %.3f (%.3f) | %.4f | %s |' % (label, x, a, ratio, mp, noise, block, gates))
    print('\n'.join(out))


if __name__ == '__main__':
    main()
