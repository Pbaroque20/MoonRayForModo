"""Render the scenes tools/probe_cl_environment_projections.py wrote with MoonRay and compare each with Modo's own picture
of the same environment. Both are latitude-longitude pictures of an image whose colour is its own coordinates, so the
difference is how far apart (in the image) the two renderers look each direction up. Pixels where Modo's picture jumps
(a seam where the image repeats, filtered differently by each renderer) are left out of the mean. Writes, for each case,
compare_<case>.png: Modo's picture above MoonRay's (and the switch-off scene's below, where written), and
compare.json with the numbers. A case the probe rendered in the six views of a cube (PROBE_VIEWS=cube, the views folder)
is compared over all six, one view to a column.

check_environment_projections.py <runtime> [folder] [case ...]

check_environment_projections.py fixture <runtime> <folder> <out.json> <case ...>: samples of Modo's own pictures for
tests/test_environment_projections.py, each case's locator and matrix with directions where Modo's picture is smooth
(no edge its filter blurs): an image case's (x, y, z, u, v, 0.25), a procedural case's (x, y, z, value) and its layer's
channels. Modo's spherical camera sees the direction (sin L cos f, sin f, cos L cos f) at a pixel's longitude L (-pi at
the left edge) and latitude f."""
import math
import json
import struct
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402


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


def apart(modo, ours):
    width, height, a = modo
    w2, h2, b = ours
    if (width, height) != (w2, h2):
        return None
    total, count, worst = 0.0, 0, []
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            i = (y * width + x) * 3
            if any(abs(a[i + k] - a[j + k]) > .05 for j in (i + 3, i - 3, i + width * 3, i - width * 3) for k in range(3)):
                continue
            d = max(abs(a[i + k] - b[i + k]) for k in range(3))
            total += d
            count += 1
            worst.append(d)
    worst.sort()
    return {'mean': total / max(1, count), 'p95': worst[int(len(worst) * .95)] if worst else 0, 'pixels': count}


def fixture(runtime, folder, target, cases):
    report = json.loads((folder / 'report.json').read_text())
    found = json.loads(target.read_text()) if target.is_file() else {}
    for name in cases:
        case = report['cases'][name]
        width, height, values = pixels(runtime, folder / ('modo_%s.Final Color Output.0001.exr' % name))
        at = lambda x, y, k: values[((height - 1 - y) * width + x) * 3 + k]   # the PFM's rows run bottom up
        procedural = 'layer' in case
        smooth, middling = [], []
        for y in range(2, height - 2, 3):
            for x in range(2, width - 2, 3):
                near = [at(x + i, y + j, k) for i in (-2, 0, 2) for j in (-2, 0, 2) for k in (range(1) if procedural else range(2))]
                spread = max(near) - min(near)
                # In a pattern's soft edge the picture changes steadily: there, no more than its filter can shift it.
                if spread > (.2 if procedural and .1 < at(x, y, 0) < .9 else .03 if procedural else .02):
                    continue
                longitude, latitude = 2 * math.pi * ((x + .5) / width - .5), math.pi * (.5 - (y + .5) / height)
                d = [round(v, 6) for v in (math.sin(longitude) * math.cos(latitude), math.sin(latitude), math.cos(longitude) * math.cos(latitude))]
                sample = d + ([round(at(x, y, 0), 4)] if procedural else [round(at(x, y, k), 4) for k in range(3)])
                (middling if procedural and .1 < at(x, y, 0) < .9 else smooth).append(sample)
        # Spread over the picture: every so many, more of those in a pattern's soft edges.
        chosen = smooth[::max(1, len(smooth) // 16)][:16] + middling[::max(1, len(middling) // 16)][:16]
        found[name] = {'locator': case['locator'], 'matrix': case['matrix'], 'samples': chosen}
        if procedural:
            found[name]['layer'] = case['layer']
            found[name]['kind'] = 'dots' if 'dotWidth' in case['layer'] else 'grid'
        print(name, len(chosen), 'samples')
    target.write_text(json.dumps(found, indent=0), encoding='utf-8')


def main():
    if sys.argv[1] == 'fixture':
        return fixture(native.find_runtime(Path(sys.argv[2])), Path(sys.argv[3]), Path(sys.argv[4]), sys.argv[5:])
    runtime = native.find_runtime(Path(sys.argv[1]))
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else root / 'test-results/env-projections'
    only = sys.argv[3:]
    report = json.loads((folder / 'report.json').read_text())
    found = {}
    for name, case in report['cases'].items():
        if only and name not in only:
            continue
        labels = ['%s_v%d' % (name, i) for i in range(case['views'])] if case.get('views') else [name]
        if not all((folder / ('modo_%s.Final Color Output.0001.exr' % label)).is_file() for label in labels):
            continue
        entry = {}
        rows = [[folder / ('modo_%s.Final Color Output.0001.exr' % label) for label in labels]]
        for tag in ('', '_off'):
            if not all((folder / ('%s%s.rdla' % (label, tag))).is_file() for label in labels):
                continue
            row, sums = [], []
            for label in labels:
                output = folder / ('moonray_%s%s.exr' % (label, tag))
                done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(folder / ('%s%s.rdla' % (label, tag)), output, 0, 'vectorized'),
                                      env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if done.returncode or not output.is_file():
                    entry['error' + tag] = done.stdout.decode(errors='replace')[-800:]
                    break
                sums.append(apart(pixels(runtime, rows[0][len(row)]), pixels(runtime, output)))
                row.append(output)
            else:
                count = sum(s['pixels'] for s in sums)
                entry['moonray' + tag] = {'mean': sum(s['mean'] * s['pixels'] for s in sums) / max(1, count),
                                          'p95': max(s['p95'] for s in sums), 'pixels': count}
                rows.append(row)
        sheet = folder / ('compare_%s.png' % name)
        arguments = []
        for row in rows:
            for picture in row:
                arguments += [str(picture), '--ch', 'R,G,B']
        subprocess.run([str(runtime / 'oiiotool.exe')] + arguments + ['--mosaic:pad=2', '%dx%d' % (len(labels), len(rows)), '-d', 'uint8', '-o', str(sheet)],
                       env=native.environment(runtime), check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        found[name] = entry
        on, off = entry.get('moonray'), entry.get('moonray_off')
        print('%-24s on %s   off %s' % (name, '%.4f (p95 %.3f)' % (on['mean'], on['p95']) if on else entry.get('error', '-')[-80:],
                                         '%.4f' % off['mean'] if off else '-'), flush=True)
    (folder / 'compare.json').write_text(json.dumps(found, indent=1))


if __name__ == '__main__':
    main()
