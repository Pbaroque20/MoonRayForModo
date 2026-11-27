"""Compare the plugin's surface Grid and Dots (procedurals.sample, laid by the kit's UVs and procedurals.uv_offset)
with Modo's own renders of them (tools/probe_cl_surface_procedurals.py: a 2 x 2 plane, its UVs 0 to 1, seen from a
camera on +Z, 4 units away, through a square 36 mm film and a 50 mm lens), pixel by pixel where Modo's picture is
smooth. Prints each case's mean and 95th percentile difference; where the probe wrote the plugin's scene (<case>.rdla),
MoonRay renders it and its picture is compared too (compare_<case>.png: Modo's on the left).

check_surface_procedurals.py <runtime> [folder]

check_surface_procedurals.py fixture <runtime> <folder> <out.json> <case ...>: samples of Modo's pictures for
tests/test_surface_procedurals.py, each case's layer and locator channels and its locator matrix with (X, Y, value)
points of the plane where Modo's picture is smooth."""
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import coordinates, native, procedurals  # noqa: E402

HALF_VIEW = 4 * .018 / .05   # half the frame's width at the plane


def pixels(runtime, source):
    target = source.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)],
                   env=native.environment(runtime), check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    data = target.read_bytes()
    target.unlink()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return width, height, values


def pattern(case):
    layer = case['layer']
    kind = 'dots' if 'dotWidth' in layer else 'grid'
    return {'kind': kind, 'pattern': layer['type'], 'width': float(layer.get('lineWidth', layer.get('dotWidth'))),
            'transition': float(layer['transWidth']), 'bias': float(layer['bias']), 'gain': float(layer['gain']),
            'color1': [0.0] * 3, 'color2': [1.0] * 3, 'alpha1': 1.0, 'alpha2': 1.0}


def plugin_value(case, x, y):
    """The plugin's value at the plane's point (x, y): its UV there as the kit lays it (a Planar locator's x + 0.5, y +
    0.5 in the locator's space, its Wraps left out; a UV map's (x + 1) / 2, (y + 1) / 2), moved by the layer's UV
    transform (coordinates.transform_uv), the pattern sampled with layers.py's offset."""
    locator = case['locator']
    rotation = float(locator['uvRotation'])
    if locator['projType'] == 'planar':
        size = float(case['matrix'][0])
        uv, scale = (.5 + x / size, .5 + y / size), [1.0, 1.0]
    else:
        uv, scale = ((x + 1) / 2, (y + 1) / 2), [float(locator['wrapU']), float(locator['wrapV'])]
    u, v = coordinates.transform_uv({'rotation': rotation, 'scale': scale}, [uv])[0]
    data = pattern(case)
    offset = procedurals.uv_offset(rotation, scale)
    if offset:
        data['offset'] = offset
    return procedurals.sample(data, u, v)[0][0]


def smooth_points(runtime, folder, name, step=2):
    width, height, values = pixels(runtime, folder / ('modo_%s.Final Color Output.0001.exr' % name))
    at = lambda px, py: values[((height - 1 - py) * width + px) * 3]
    found = []
    for py in range(2, height - 2, step):
        for px in range(2, width - 2, step):
            x, y = ((px + .5) / width - .5) * 2 * HALF_VIEW, (.5 - (py + .5) / height) * 2 * HALF_VIEW
            if abs(x) > .97 or abs(y) > .97:
                continue
            if any(abs(at(px, py) - at(px + i, py + j)) > .05 for i, j in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                continue
            found.append((x, y, at(px, py)))
    return found


def main():
    if sys.argv[1] == 'fixture':
        runtime, folder, target = native.find_runtime(Path(sys.argv[2])), Path(sys.argv[3]), Path(sys.argv[4])
        report = json.loads((folder / 'report.json').read_text())
        found = json.loads(target.read_text()) if target.is_file() else {}
        for name in sys.argv[5:]:
            case = report['cases'][name]
            points = smooth_points(runtime, folder, name, 3)
            middling = [p for p in points if .1 < p[2] < .9]
            ends = [p for p in points if not .1 < p[2] < .9]
            chosen = ends[::max(1, len(ends) // 16)][:16] + middling[::max(1, len(middling) // 16)][:16]
            found[name] = {k: case[k] for k in ('layer', 'locator', 'matrix')}
            found[name]['samples'] = [[round(x, 6), round(y, 6), round(v, 4)] for x, y, v in chosen]
            print(name, len(chosen), 'samples')
        target.write_bytes(json.dumps(found, indent=0).encode('utf-8'))
        return
    runtime = native.find_runtime(Path(sys.argv[1]))
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else root / 'test-results/surface-procedurals'
    report = json.loads((folder / 'report.json').read_text())
    for name, case in report['cases'].items():
        if 'layer' not in case or case['layer'].get('type') is None or not (folder / ('modo_%s.Final Color Output.0001.exr' % name)).is_file():
            continue
        if 'lineWidth' not in case['layer'] and 'dotWidth' not in case['layer']:
            continue
        errors = sorted(abs(plugin_value(case, x, y) - value) for x, y, value in smooth_points(runtime, folder, name))
        line = '%-24s mean %.4f  p95 %.4f  (%d pixels)' % (name, sum(errors) / len(errors), errors[int(.95 * len(errors))], len(errors))
        scene = folder / ('%s.rdla' % name)
        if scene.is_file():
            # The scene the plugin wrote, rendered by MoonRay, against Modo's picture where it is smooth.
            output = folder / ('moonray_%s.exr' % name)
            subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(scene, output, 0, 'vectorized'), env=native.environment(runtime),
                           cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if output.is_file():
                width, height, modo = pixels(runtime, folder / ('modo_%s.Final Color Output.0001.exr' % name))
                _, _, ours = pixels(runtime, output)
                found = []
                for py in range(2, height - 2):
                    for px in range(2, width - 2):
                        i = (py * width + px) * 3
                        if any(abs(modo[i] - modo[j]) > .05 for j in (i + 3, i - 3, i + width * 3, i - width * 3)):
                            continue
                        found.append(max(abs(modo[i + k] - ours[i + k]) for k in range(3)))
                found.sort()
                line += '   MoonRay mean %.4f  p95 %.4f' % (sum(found) / len(found), found[int(.95 * len(found))])
                subprocess.run([str(runtime / 'oiiotool.exe'), str(folder / ('modo_%s.Final Color Output.0001.exr' % name)), '--ch', 'R,G,B',
                                str(output), '--ch', 'R,G,B', '--mosaic:pad=2', '2x1', '-d', 'uint8', '-o', str(folder / ('compare_%s.png' % name))],
                               env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(line, flush=True)


if __name__ == '__main__':
    main()
