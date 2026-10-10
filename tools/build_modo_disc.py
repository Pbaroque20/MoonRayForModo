"""Turn Modo's own pictures of its solar disc into the table the plugin reads.

Usage: build_modo_disc.py <moonray-runtime>
Reads test-results/modo-disc, which tools/probe_modo_disc.py makes, and writes modo_disc.json beside the sky's table:
for each sun height, haze amount and amount of Disc In-Scatter, the radiance at the middle of the disc."""
import json
import pathlib
import struct
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native

SOURCE = ROOT / 'test-results/modo-disc'
TARGET = ROOT / 'kit/MoonRayForModo/python/moonray_modo/modo_disc.json'


def pixels(runtime, name):
    """The picture as (width, height, values), bottom row first."""
    source = next(SOURCE.glob(name + '.*.exr'))
    target = SOURCE / (name + '.pfm')
    if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)],
                       env=native.environment(runtime), check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    data = target.read_bytes()
    header = data.split(b'\n', 3)
    width, height = map(int, header[1].split())
    return width, height, struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * 3), header[3])


def middle(picture, elevation):
    """The radiance at the middle of the disc: the four pixels about where a sun that high stands, due south."""
    width, height, values = picture
    row = (0.5 + elevation / 180.0) * height - 0.5
    column = width / 2.0 - 0.5
    found = [0.0, 0.0, 0.0]
    for y in (int(row), int(row) + 1):
        for x in (int(column), int(column) + 1):
            at = (min(height - 1, y) * width + x) * 3
            for c in range(3):
                found[c] += values[at + c] / 4.0
    return found


def main():
    runtime = native.find_runtime(sys.argv[1])
    report = json.loads((SOURCE / 'report.json').read_text())
    if report.get('error'):
        raise SystemExit(report['error'])
    elevations, hazes, amounts = report['elevations'], report['hazes'], report['amounts']
    disc = [[[None] * len(amounts) for _ in hazes] for _ in elevations]
    for e, elevation in enumerate(elevations):
        for h, haze in enumerate(hazes):
            for a, amount in enumerate(amounts):
                disc[e][h][a] = [round(v, 4) for v in middle(pixels(runtime, 'disc_%d_%d_%d' % (e, h, a)), elevation)]
            print('sun %2d haze %g  ' % (elevation, haze) + '  '.join('%g: %s' % (amount, [round(v, 1) for v in disc[e][h][a]]) for a, amount in enumerate(amounts)))
    TARGET.write_text(json.dumps({'elevations': elevations, 'hazes': hazes, 'amounts': amounts, 'disc': disc}), encoding='utf-8')
    print('Wrote', TARGET)


if __name__ == '__main__':
    main()
