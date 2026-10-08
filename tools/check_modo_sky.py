"""Hold the plugin's sky to Modo's own pictures of its physically based daylight (tools/probe_modo_sky.py), which the table was not built from.

Usage: check_modo_sky.py <moonray-runtime>"""
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

folder = root / 'test-results/modo-sky'


def pfm(path):
    data = path.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    scale = float(parts[2])
    values = struct.unpack(('<' if scale < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    # PFM rows run bottom to top.
    return width, height, lambda x, y: values[((height - 1 - y) * width + x) * 3:((height - 1 - y) * width + x) * 3 + 3]


def load(runtime, name):
    source = folder / (name + '.Final Color Output.0001.exr')
    target = folder / (name + '.pfm')
    if not target.is_file() or target.stat().st_mtime < source.stat().st_mtime:
        subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)],
                       env=native.environment(runtime), check=True)
    return pfm(target)


def direction(x, y, width, height):
    """Where a pixel of the spherical picture looks: the middle of the picture is +Z, behind the camera."""
    longitude = (x + .5) / width * 2 * math.pi - math.pi
    latitude = math.pi / 2 - (y + .5) / height * math.pi
    return [math.cos(latitude) * math.sin(longitude), math.sin(latitude), math.cos(latitude) * math.cos(longitude)]


def main():
    runtime = Path(sys.argv[1]).resolve()
    report = json.loads((folder / 'report.json').read_text())
    worst_case = 0.0
    for case in report['cases']:
        width, height, sky = load(runtime, 'sky_' + case['name'])
        # A light turned by hand shines along its -Z; one placed by date and time reports where the sun is.
        sun = case['direction'] if 'matrix' in case else [-v for v in case['direction']]
        environment = {'sun_direction': sun, 'haze': case['haze'], 'normalize': bool(case['flags'].get('normalize', 1)),
                       'sky_gamma': case['flags'].get('gamma', 1.0), 'ground_albedo': [.5, .5, .5]}
        errors = []
        for y in range(0, height // 2):
            for x in range(0, width, 4):
                toward = direction(x, y, width, height)
                if sum(a * b for a, b in zip(toward, sun)) > .9986:
                    continue    # the solar disc, which the sun light supplies
                errors += [abs(ours - theirs) / max(theirs, 1e-3) for ours, theirs in zip(daylight.color(toward, environment), sky(x, y))]
        errors.sort()
        below = max(abs(a - b) for a, b in zip(daylight.color([0, -.5, .5], environment), sky(width // 2, height - 20)))
        worst_case = max(worst_case, errors[int(len(errors) * .9)])
        print('%-22s sun %5.1f deg  haze %-4s sky off by: median %.3f  90%% of it within %.3f  worst %.3f  ground off by %.3f' % (
            case['name'], math.degrees(math.asin(sun[1])), case['haze'], errors[len(errors) // 2], errors[int(len(errors) * .9)], errors[-1], below))
    print('worst 90%% figure %.3f' % worst_case)


if __name__ == '__main__':
    main()
