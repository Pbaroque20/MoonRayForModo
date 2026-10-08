"""Render the ball scenes tools/probe_fresnel.py exported with MoonRay and compare what the ball shows with Modo's.

The ball is in an even white sky, so its brightness from the middle to the edge is how much it
reflects at each angle. Printed for each case: Modo's and MoonRay's at angles from straight on (0)
to nearly edge on. Usage: check_fresnel.py <moonray-runtime> [case ...]"""
import json
import math
import struct
import subprocess
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

folder = root / 'test-results/fresnel'
ANGLES = (0, 20, 40, 55, 65, 75, 82)


def pixels(runtime, source):
    target = source.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], env=native.environment(runtime), check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return width, height, values


def profile(picture):
    """The ball's colour at each angle between the view and its surface, averaged around the ball."""
    width, height, values = picture
    # The ball's edge: where the middle row stops being the ball. The sky is 1; the ball differs or, if not, fills a known share.
    inside = [x for x in range(width) if abs(values[(height // 2 * width + x) * 3 + 1] - values[1]) > .02]
    radius = (inside[-1] - inside[0] + 1) / 2.0 if inside else width * .25
    centre = (inside[0] + inside[-1]) / 2.0 if inside else (width - 1) / 2.0
    found = []
    for angle in ANGLES:
        distance = radius * math.sin(math.radians(angle))
        total, count = [0.0, 0.0, 0.0], 0
        for step in range(24):
            turn = 2 * math.pi * step / 24
            x, y = int(round(centre + distance * math.cos(turn))), int(round((height - 1) / 2.0 + distance * math.sin(turn)))
            for c in range(3):
                total[c] += values[(y * width + x) * 3 + c]
            count += 1
            if angle == 0:
                break
        found.append([v / count for v in total])
    return found


def main():
    runtime = Path(sys.argv[1]).resolve()
    chosen = sys.argv[2:]
    report = json.loads((folder / 'report.json').read_text())
    if 'error' in report:
        print(report['error'])
    print('%-24s %s' % ('angle from straight on', '  '.join('%5d' % a for a in ANGLES)))
    for case in report['cases']:
        name = case['name']
        if chosen and name not in chosen:
            continue
        if 'error' in case:
            print(name, case['error'])
            continue
        output = folder / ('moonray_' + name + '.exr')
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / (name + '.rdla'), output, 0, 'vectorized'),
                              env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if done.returncode or not output.is_file():
            print(name, 'MoonRay failed:', done.stdout.decode(errors='replace')[-300:])
            continue
        theirs = profile(pixels(runtime, folder / ('modo_' + name + '.Final Color Output.0001.exr')))
        ours = profile(pixels(runtime, output))
        coloured = any(abs(v[0] - v[2]) > .02 for v in theirs + ours)
        for label, rows in (('Modo', theirs), ('MoonRay', ours)):
            if coloured:
                print('%-24s %s' % (name + ' ' + label, '  '.join('%.2f/%.2f/%.2f' % tuple(v) for v in rows[::2])))
            else:
                print('%-24s %s' % (name + ' ' + label, '  '.join('%5.3f' % v[1] for v in rows)))
        if case.get('warnings'):
            print('   ', '; '.join(case['warnings'])[:200])


if __name__ == '__main__':
    main()
