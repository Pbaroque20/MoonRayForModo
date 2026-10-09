"""Render the material scenes tools/probe_material_parity.py exported with MoonRay and set them beside Modo's own renders.

Usage: check_material_parity.py <moonray-runtime>"""
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

folder = root / 'test-results/material-parity'


def pixels(runtime, source):
    target = source.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], env=native.environment(runtime), check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return width, height, [values[(height - 1 - y) * width * 3:(height - y) * width * 3] for y in range(height)]


def main():
    runtime = Path(sys.argv[1]).resolve()
    report = json.loads((folder / 'report.json').read_text())
    for case in report['cases']:
        name = case['name']
        if 'error' in case:
            print(name, case['error'])
            continue
        output = folder / ('moonray_' + name + '.exr')
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / (name + '.rdla'), output, 0, 'vectorized'),
                              env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if done.returncode or not output.is_file():
            print(name, 'MoonRay failed:', done.stdout.decode(errors='replace')[-400:])
            continue
        reference = folder / ('modo_' + name + '.Final Color Output.0001.exr')
        width, height, theirs = pixels(runtime, reference)
        _, _, ours = pixels(runtime, output)
        # Tiles of the picture, each compared by its mean.
        ratios = []
        for ty in range(0, height, 20):
            for tx in range(0, width, 20):
                a = [sum(ours[y][x * 3 + c] for y in range(ty, ty + 20) for x in range(tx, tx + 20)) for c in range(3)]
                b = [sum(theirs[y][x * 3 + c] for y in range(ty, ty + 20) for x in range(tx, tx + 20)) for c in range(3)]
                ratios.append([p / q if q > 1e-6 else 1.0 for p, q in zip(a, b)])
        close = sum(all(abs(v - 1) <= .1 for v in tile) for tile in ratios) / len(ratios)
        mean = [sum(tile[c] for tile in ratios) / len(ratios) for c in range(3)]
        print('%-16s MoonRay/Modo by tile: mean %s, %d%% of tiles within 10%%' % (name, ' '.join('%.3f' % v for v in mean), round(100 * close)))
        for source, label in ((reference, 'modo'), (output, 'moonray')):
            subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-o',
                            str(folder / ('%s_%s.png' % (name, label)))], env=native.environment(runtime))
        subprocess.run([str(runtime / 'oiiotool.exe'), str(folder / (name + '_modo.png')), str(folder / (name + '_moonray.png')), '--mosaic', '2x1',
                        '-o', str(folder / (name + '_modo_left_moonray_right.png'))], env=native.environment(runtime))


if __name__ == '__main__':
    main()
