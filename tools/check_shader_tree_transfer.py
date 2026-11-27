"""Render, with MoonRay, the scenes tools/probe_cl_shader_tree_transfer.py exported before and after Move Shader Tree
Textures to MoonShine Graphs (and any others named), and set them side by side: <folder>/<a>-vs-<b>.png, each pair
above the picture of their difference times 8. Prints how far apart they are, over the whole picture and by column
(one cube a column).

check_shader_tree_transfer.py <runtime> <folder> [a:b ...]   (default before:after)"""
import struct
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402

runtime, folder = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
pairs = [tuple(p.split(':')) for p in sys.argv[3:]] or [('before', 'after')]
environment = native.environment(runtime)


def render(name):
    picture = folder / (name + '.exr')
    if picture.is_file() and picture.stat().st_mtime > (folder / (name + '.rdla')).stat().st_mtime:
        return picture
    done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / (name + '.rdla')), '-out', str(picture), '-exec_mode', 'scalar'],
                          env=environment, cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (folder / (name + '.log')).write_bytes(done.stdout)
    if done.returncode or not picture.is_file():
        raise SystemExit('%s did not render:\n%s' % (name, done.stdout.decode(errors='replace')[-3000:]))
    return picture


def pixels(source):
    target = source.with_suffix('.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], env=environment, check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    return width, height, values


for a, b in pairs:
    first, second = render(a), render(b)
    (wa, ha, va), (wb, hb, vb) = pixels(first), pixels(second)
    assert (wa, ha) == (wb, hb)
    difference = [abs(x - y) for x, y in zip(va, vb)]
    mean = sum(difference) / len(difference)
    brightness = sum(va) / len(va)
    columns = 7
    by_column = []
    for column in range(columns):
        x0, x1 = wa * column // columns, wa * (column + 1) // columns
        held = [difference[(y * wa + x) * 3 + c] for y in range(ha) for x in range(x0, x1) for c in range(3)]
        by_column.append(sum(held) / len(held))
    print('%s vs %s: mean |difference| %.5f (mean value %.4f), largest %.4f; by column %s'
          % (a, b, mean, brightness, max(difference), ' '.join('%.4f' % v for v in by_column)))
    pair = folder / ('%s-vs-%s.png' % (a, b))
    subprocess.run([str(runtime / 'oiiotool.exe'), str(first), '--ch', 'R,G,B', str(second), '--ch', 'R,G,B', '--diff', '--absdiff', '--mulc', '8',
                    '-o', str(folder / ('%s-vs-%s-diff.exr' % (a, b)))], env=environment)
    subprocess.run([str(runtime / 'oiiotool.exe'), str(first), '--ch', 'R,G,B', str(second), '--ch', 'R,G,B',
                    str(folder / ('%s-vs-%s-diff.exr' % (a, b))), '--mosaic', '1x3', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8',
                    '-o', str(pair)], env=environment, check=True)
    print('  ', pair)
