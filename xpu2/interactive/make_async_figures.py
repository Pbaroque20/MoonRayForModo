"""Figures for ASYNC_RESULTS.md from a uniform and an adaptive benchmark.

make_async_figures.py --uniform <run_async_benchmark output> --adaptive <run_async_adaptive_benchmark output>
    --output <folder for the images>

For each fixture: the 1024-sample images of original XPU and of XPU2 and their difference (they converge to the
same image); the 64-sample images of both, rendered in the timed runs; the adaptive images of both at XPU's
quality, with where each put its samples; and one chart of the render times. Plain Python: PNGs are written with
zlib, the chart as SVG. Images are shown with the sRGB curve, unscaled; differences in linear light, scaled by
DIFFERENCE_SCALE, so their brightness is their size."""
import argparse
import json
import math
import struct
import subprocess
import zlib
from pathlib import Path

from prototype_wire import decode
from reference_repeatability import values
from xpu2.images import pixels

HERE = Path(__file__).resolve().parent
TR = HERE.parents[1] / 'test-results'
RUNTIME = TR / 'interactive-reference-042'
DIFFERENCE_SCALE = 20


def srgb(v):
    v = min(max(v, 0.0), 1.0)
    return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def png(path, width, height, rgb):
    """rgb: rows top to bottom of (r, g, b) floats in [0, 1], already display-encoded."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            for c in rgb[y * width + x]:
                raw.append(int(round(min(max(c, 0.0), 1.0) * 255)))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))


def shown(rgba, width, height):
    return [tuple(srgb(rgba[i * 4 + c]) for c in range(3)) for i in range(width * height)]


def difference(a, b, width, height):
    return [tuple(DIFFERENCE_SCALE * abs(a[i * 4 + c] - b[i * 4 + c]) for c in range(3)) for i in range(width * height)]


RAMP = [(0.267, 0.005, 0.329), (0.229, 0.322, 0.546), (0.128, 0.567, 0.551), (0.369, 0.789, 0.383), (0.993, 0.906, 0.144)]


def heat(counts, width, height, low, high):
    out = []
    for n in counts:
        t = 0.0 if high <= low else min(max((math.log(n) - math.log(low)) / (math.log(high) - math.log(low)), 0.0), 1.0)
        f = t * (len(RAMP) - 1)
        i = min(int(f), len(RAMP) - 2)
        u = f - i
        out.append(tuple(RAMP[i][c] * (1 - u) + RAMP[i + 1][c] * u for c in range(3)))
    return out


def xpu_image(folder, decoder):
    raw = folder / 'beauty.rgba'
    if raw.exists():
        return values(raw.read_bytes())
    _, data = decode(decoder, RUNTIME, folder / 'beauty.exr', folder)
    return values(data)


def counts(path, n):
    return list(struct.unpack('<%dI' % n, path.read_bytes()))


def chart(path, rows):
    """rows: (label, xpu seconds, xpu2 seconds); horizontal bars on one linear scale per row."""
    w, left, bar, gap = 760, 230, 18, 14
    h = 40 + len(rows) * (2 * bar + gap + 10)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="sans-serif" font-size="13">' % (w, h, w, h),
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="%d" y="22" font-weight="bold">Render time, 12 threads (bar length relative to XPU in each row)</text>' % 10]
    y = 40
    for label, xpu, ours in rows:
        span = w - left - 150
        out.append('<text x="10" y="%d">%s</text>' % (y + bar + 4, label))
        out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#8c8c8c"/>' % (left, y, span, bar))
        out.append('<text x="%d" y="%d">XPU %.2f s</text>' % (left + span + 6, y + 13, xpu))
        mine = max(1.5, span * ours / xpu)
        out.append('<rect x="%d" y="%d" width="%.1f" height="%d" fill="#2a7ab9"/>' % (left, y + bar + 4, mine, bar))
        out.append('<text x="%d" y="%d">XPU2 %.3f s (%.0f× faster)</text>' % (left + mine + 6, y + 2 * bar + 1, ours, xpu / ours))
        y += 2 * bar + gap + 10
    out.append('</svg>')
    path.write_text('\n'.join(out) + '\n', encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uniform', type=Path, required=True)
    p.add_argument('--adaptive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve()
    a.uniform, a.adaptive = a.uniform.resolve(), a.adaptive.resolve()
    out.mkdir(parents=True, exist_ok=True)
    decoder = Path(json.loads((TR / 'interactive-prototype-build-20261022qmc/build.json').read_text())['exe'])
    fixtures = json.loads((TR / 'interactive-large-scenes-20261022/report.json').read_text())
    prior = json.loads((TR / 'interactive-large-benchmark-20261022/report.json').read_text())
    uniform = json.loads((a.uniform / 'report.json').read_text())
    adaptive = json.loads((a.adaptive / 'report.json').read_text())
    rows, notes = [], {}
    for name, case in uniform['cases'].items():
        width, height = fixtures['cases'][name]['resolution']
        n = width * height
        reference = values((Path(prior['cases'][name]['converged_reference']['folder']) / 'beauty.rgba').read_bytes())
        d = a.uniform / name
        high = values((d / 'high-1024' / 'run-0.rgba').read_bytes())
        png(out / f'{name}-xpu-1024.png', width, height, shown(reference, width, height))
        png(out / f'{name}-xpu2-1024.png', width, height, shown(high, width, height))
        png(out / f'{name}-difference-1024.png', width, height, difference(reference, high, width, height))
        xpu64 = xpu_image(d / 'xpu-t12-1', decoder)
        ours64 = values((d / 'async-t12' / 'run-1.rgba').read_bytes())
        png(out / f'{name}-xpu-64.png', width, height, shown(xpu64, width, height))
        png(out / f'{name}-xpu2-64.png', width, height, shown(ours64, width, height))
        timing = case['timing']['12']
        rows.append((f'{name}, 64 samples', timing['xpu_median'], timing['async_median']))
        # Adaptive: XPU at its settings, XPU2 at the target that meets XPU's error.
        ad = adaptive['cases'][name]
        at = ad['timing']['12']
        matched = at['quality_matched']
        k = [round(adaptive['adaptive']['target_error'] * s, 6) for s in (1.0, .9, .8, .7, .6, .5)].index(round(matched['target_error'], 6))
        folder = a.adaptive / name / ('async-t12' if k == 0 else f'async-t12-target{k}')
        xa = xpu_image(a.adaptive / name / 'xpu-t12-1', decoder)
        oa = values((folder / 'run-1.rgba').read_bytes())
        png(out / f'{name}-xpu-adaptive.png', width, height, shown(xa, width, height))
        png(out / f'{name}-xpu2-adaptive.png', width, height, shown(oa, width, height))
        _, wv = pixels(a.adaptive / name / 'xpu-t12-0' / 'weight.pfm')
        xw = [max(1, int(round(v))) for v in wv[::3]]
        ow = counts(folder / 'run-1.counts', n)
        low, top = min(min(xw), min(ow)), max(max(xw), max(ow))
        png(out / f'{name}-xpu-samples.png', width, height, heat(xw, width, height, low, top))
        png(out / f'{name}-xpu2-samples.png', width, height, heat(ow, width, height, low, top))
        rows.append((f'{name}, adaptive', at['xpu_median'], matched['async_median']))
        notes[name] = {'samples_range': [low, top], 'adaptive_target': matched['target_error']}
    chart(out / 'render-times.svg', rows)
    (out / 'figures.json').write_text(json.dumps({'uniform': a.uniform.name, 'adaptive': a.adaptive.name,
                                                   'difference_scale': DIFFERENCE_SCALE, 'cases': notes}, indent=2) + '\n')
    print(json.dumps(notes))


if __name__ == '__main__':
    main()
