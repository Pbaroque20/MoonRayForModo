"""Render the glass balls tools/probe_glass.py exported with MoonRay and compare them with Modo's own renders.

For each case: the ball's average colour in Modo and in MoonRay, in its middle and near its edge, and the average
difference over the ball; and a picture, test-results/glass/compare_<case>.png, Modo left and MoonRay right.
Usage: check_glass.py <moonray-runtime> [case ...]"""
import json
import math
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (also sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/glass'


def regions(picture):
    """The ball's average colour within 40% of its radius, between 75% and 95%, and the pixels inside it."""
    width, height, values = picture
    centre, radius = (width - 1) / 2.0, width * .5 * .66
    middle, rim, inside = [], [], []
    for y in range(height):
        for x in range(width):
            d = math.hypot(x - centre, y - centre) / radius
            pixel = values[(y * width + x) * 3:(y * width + x) * 3 + 3]
            if d < .4:
                middle.append(pixel)
            elif .75 < d < .95:
                rim.append(pixel)
            if d < .95:
                inside.append((y * width + x, pixel))
    mean = lambda rows: [sum(p[c] for p in rows) / max(1, len(rows)) for c in range(3)]
    return mean(middle), mean(rim), inside


def main():
    runtime = Path(sys.argv[1]).resolve()
    chosen = sys.argv[2:]
    report = json.loads((folder / 'report.json').read_text())
    if 'error' in report:
        print(report['error'])
    for case in report['cases']:
        name = case['name']
        if chosen and name not in chosen:
            continue
        if 'error' in case:
            print(name, case['error'][-400:])
            continue
        output = folder / ('moonray_' + name + '.exr')
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / (name + '.rdla'), output, 0, 'vectorized'),
                              env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if done.returncode or not output.is_file():
            print(name, 'MoonRay failed:', done.stdout.decode(errors='replace')[-300:])
            continue
        modo_file = folder / ('modo_' + name + '.Final Color Output.0001.exr')
        theirs, ours = regions(pixels(runtime, modo_file)), regions(pixels(runtime, output))
        difference = sum(abs(a[1][c] - b[1][c]) for a, b in zip(theirs[2], ours[2]) for c in range(3)) / max(1, 3 * len(theirs[2]))
        brightness = sum(sum(p) for _, p in ours[2]) / max(1e-6, sum(sum(p) for _, p in theirs[2]))
        print('%-22s middle Modo %.2f/%.2f/%.2f MoonRay %.2f/%.2f/%.2f   edge Modo %.2f/%.2f/%.2f MoonRay %.2f/%.2f/%.2f   '
              'difference %.3f, brightness %.2f' % ((name,) + tuple(theirs[0]) + tuple(ours[0]) + tuple(theirs[1]) + tuple(ours[1]) + (difference, brightness)))
        if case.get('warnings'):
            print('   ', '; '.join(case['warnings'])[:200])
        subprocess.run([str(runtime / 'oiiotool.exe'), str(modo_file), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '2x1',
                        '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / ('compare_' + name + '.png'))],
                       env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


if __name__ == '__main__':
    main()
