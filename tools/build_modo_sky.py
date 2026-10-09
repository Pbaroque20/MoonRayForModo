"""Make the table the plugin's physically based daylight reads, from Modo's own pictures of its sky and sun.

The pictures come from tools/probe_modo_sky_table.py (the sky) and tools/probe_modo_sun.py (the
sun). Usage: build_modo_sky.py <moonray-runtime>"""
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
from moonray_modo import daylight, native

SKY = root / 'test-results/modo-sky-table'
SUN = root / 'test-results/modo-sun'


def picture(runtime, folder, name):
    source = folder / (name + '.Final Color Output.0001.exr')
    target = folder / (name + '.pfm')
    if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)],
                       env=native.environment(runtime), check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    # PFM rows run bottom to top.
    return width, height, [values[(height - 1 - y) * width * 3:(height - y) * width * 3] for y in range(height)]


def sample(rows, width, height, zenith, azimuth):
    """The sky at an angle from the zenith and an azimuth from the sun, which stands in the middle column."""
    x = (azimuth / (2 * math.pi) + .5) * width - .5
    y = min(height / 2 - 1, max(0.0, zenith / math.pi * height - .5))
    x0, y0 = math.floor(x), int(math.floor(y))
    y1 = min(height // 2 - 1, y0 + 1)
    fx, fy = x - x0, y - y0
    result = []
    for channel in range(3):
        top = rows[y0][(x0 % width) * 3 + channel] * (1 - fx) + rows[y0][((x0 + 1) % width) * 3 + channel] * fx
        bottom = rows[y1][(x0 % width) * 3 + channel] * (1 - fx) + rows[y1][((x0 + 1) % width) * 3 + channel] * fx
        result.append(max(0.0, top * (1 - fy) + bottom * fy))
    return result


def horizon(rows, width, height, azimuth):
    """The sky exactly at the horizon, which no row of the picture holds: worked back from the first row
    below it, where Modo has begun its blend from the horizon to the ground's colour (mid-grey in these pictures)."""
    x = (azimuth / (2 * math.pi) + .5) * width - .5
    x0 = math.floor(x)
    fx = x - x0
    row = rows[height // 2]
    kept = 1 - (math.pi / height / 2) / daylight.HORIZON_BLEND
    return [max(0.0, .5 + (row[(x0 % width) * 3 + c] * (1 - fx) + row[((x0 + 1) % width) * 3 + c] * fx - .5) / kept) for c in range(3)]


def main():
    runtime = Path(sys.argv[1]).resolve()
    report = json.loads((SKY / 'report.json').read_text())
    elevations = sorted({node['elevation'] for node in report['nodes']})
    hazes = sorted({node['haze'] for node in report['nodes']})
    nodes = {(node['haze'], node['elevation']): node for node in report['nodes']}
    values, scales = [], []
    for haze in hazes:
        for elevation in elevations:
            node = nodes[(haze, elevation)]
            width, height, rows = picture(runtime, SKY, node['file'])
            _, _, clamped = picture(runtime, SKY, node['file'] + '_clamped')
            ratios = sorted(rows[y][x * 3 + c] / clamped[y][x * 3 + c] for y in range(0, height // 2, 4) for x in range(0, width, 8) for c in range(3)
                            if clamped[y][x * 3 + c] > 1e-3)
            scales.append(ratios[len(ratios) // 2] if ratios else 0.0)
            sun_zenith = math.radians(90 - elevation)
            for altitude in daylight.ALTITUDES:
                zenith = math.radians(90 - altitude)
                for apart in daylight.ANGLES:
                    # The azimuth from the sun at which this height is this far from it; the nearest there is, if none.
                    across = math.sin(zenith) * math.sin(sun_zenith)
                    cosine = (math.cos(math.radians(apart)) - math.cos(zenith) * math.cos(sun_zenith)) / across if abs(across) > 1e-9 else 1.0
                    azimuth = math.acos(max(-1.0, min(1.0, cosine)))
                    values += horizon(rows, width, height, azimuth) if altitude <= 0 else sample(rows, width, height, zenith, azimuth)
        print('haze', haze, 'clamp scales', ' '.join('%.1f' % v for v in scales[-len(elevations):]), flush=True)
    measured = [row for row in json.loads((SUN / 'measured.json').read_text()) if 'check' not in row]
    sun = {}
    for row in measured:
        sun.setdefault((row['thinning'], row['haze']), []).append((row['elevation'], row['E']))
    table = {'elevations': elevations, 'hazes': hazes, 'clamp': scales,
             'sun': [{'thinning': bool(thinning), 'haze': haze, 'elevations': [e for e, _ in sorted(rows)], 'values': [v for _, v in sorted(rows)]}
                     for (thinning, haze), rows in sorted(sun.items())]}
    target = root / 'kit/MoonRayForModo/python/moonray_modo'
    (target / 'modo_daylight.json').write_text(json.dumps(table, separators=(',', ':')))
    (target / 'modo_daylight.bin').write_bytes(struct.pack('<%de' % len(values), *(min(60000.0, v) for v in values)))
    print(len(values), 'sky values;', len(measured), 'sun measurements')
    for check in report['checks']:
        width, height, rows = picture(runtime, SKY, check['file'])
        print(check['change'], 'zenith', ' '.join('%.3f' % v for v in rows[0][384:387]), 'mid', ' '.join('%.3f' % v for v in rows[32][0:3]),
              'toward sun', ' '.join('%.2f' % v for v in rows[42][384:387]), 'near', ' '.join('%.2f' % v for v in rows[42][396:399]),
              'ground', ' '.join('%.3f' % v for v in rows[100][0:3]), 'max', '%.1f' % max(max(r) for r in rows[:64]))


if __name__ == '__main__':
    main()
