"""Render the light scenes tools/probe_light_units.py exported with MoonRay and give its brightness against Modo's.

A white card under one light of each kind. The figures are MoonRay over Modo under the light, a
quarter and a half of the way out to the picture's edge, and at the edge. Usage: check_light_units.py <moonray-runtime>"""
import json
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

folder = root / 'test-results/light-units'


def pixels(runtime, source):
    target = source.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], env=native.environment(runtime), check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return width, height, [values[(height - 1 - y) * width * 3:(height - y) * width * 3] for y in range(height)]


def patch(rows, x, y, size=4):
    return sum(rows[j][i * 3 + 1] for j in range(y - size, y + size) for i in range(x - size, x + size)) / (4 * size * size)


def main():
    runtime = Path(sys.argv[1]).resolve()
    report = json.loads((folder / 'report.json').read_text())
    if 'error' in report:
        print(report['error'])
    worst = 0.0
    for case in report['cases']:
        name = case['name']
        if 'error' in case:
            print(name, case['error'])
            continue
        output = folder / ('moonray_' + name + '.exr')
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / (name + '.rdla'), output, 0, 'vectorized'),
                              env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if done.returncode or not output.is_file():
            print(name, 'MoonRay failed:', done.stdout.decode(errors='replace')[-300:])
            continue
        width, height, theirs = pixels(runtime, folder / ('modo_' + name + '.Final Color Output.0001.exr'))
        _, _, ours = pixels(runtime, output)
        places = [(width // 2, height // 2), (width // 2 + width // 8, height // 2), (width // 2 + width // 4, height // 2), (width - 6, height // 2)]
        modo = [patch(theirs, x, y) for x, y in places]
        moonray = [patch(ours, x, y) for x, y in places]
        ratios = [b / a if a > 1e-5 else float('nan') for a, b in zip(modo, moonray)]
        worst = max([worst] + [abs(r - 1) for r, a in zip(ratios, modo) if a > 1e-3 and r == r])
        print('%-13s Modo %s   MoonRay %s   MoonRay/Modo %s' % (name, ' '.join('%7.4f' % v for v in modo), ' '.join('%7.4f' % v for v in moonray),
                                                               ' '.join('%5.2f' % v for v in ratios)))
    print('furthest from Modo: %.0f%%' % (100 * worst))


if __name__ == '__main__':
    main()
