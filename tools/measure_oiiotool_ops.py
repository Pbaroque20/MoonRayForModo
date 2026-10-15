"""What the compositor's image tool does, measured: the numbers a new compositor has to give to match it.

Small pictures are made (a single lit pixel in the middle and one in a corner, a step from black to white, a ramp of
known values), run through each of the image tool's operations the compositor uses, and the result read back. Printed:
a blur's kernel across its middle row and what it does at the picture's edge; the same for unsharp mask, median,
dilate and erode, laplacian; what saturate does to one colour; how a two-corner pattern fill runs across the picture.

measure_oiiotool_ops.py <runtime folder>"""
import pathlib
import struct
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

runtime = pathlib.Path(sys.argv[1]).resolve()
work = pathlib.Path(tempfile.mkdtemp(prefix='oiio-measure-'))


def write(name, width, height, pixel):
    """A PFM picture, pixel(x, y) -> (r, g, b) with y counted from the top."""
    rows = []
    for y in range(height - 1, -1, -1):       # PFM: the bottom row first
        rows.append(b''.join(struct.pack('<3f', *pixel(x, y)) for x in range(width)))
    path = work / name
    path.write_bytes(b'PF\n%d %d\n-1.0\n' % (width, height) + b''.join(rows))
    return path


def read(path):
    data = path.read_bytes()
    header = data.split(b'\n', 3)
    width, height = map(int, header[1].split())
    channels = 3 if header[0] == b'PF' else 1
    values = struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * channels), header[3])
    return width, height, lambda x, y, c=0: values[((height - 1 - y) * width + x) * channels + min(c, channels - 1)]


def run(source, *args):
    target = work / ('out%d.pfm' % run.count)
    run.count += 1
    subprocess.run([str(runtime / 'oiiotool.exe'), '--no-autopremult', str(source)] + list(args) + ['-d', 'float', '-o', str(target)],
                   env=native.environment(runtime), check=True, creationflags=0x08000000, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return read(target)


run.count = 0
N = 21
middle = write('middle.pfm', N, N, lambda x, y: (1.0, 0.0, 0.0) if (x, y) == (N // 2, N // 2) else (0.0, 0.0, 0.0))
corner = write('corner.pfm', N, N, lambda x, y: (1.0, 0.0, 0.0) if (x, y) == (0, 0) else (0.0, 0.0, 0.0))
flat = write('flat.pfm', N, N, lambda x, y: (1.0, 1.0, 1.0))


def row(result, y, count=None):
    width, height, at = result
    return [round(at(x, y), 7) for x in range(width if count is None else count)]


for size in ():
    print('blur %dx%d middle row:' % (size, size), row(run(middle, '--blur', '%dx%d' % (size, size)), N // 2))
    print('blur %dx%d on a white picture, first row:' % (size, size), row(run(flat, '--blur', '%dx%d' % (size, size)), 0, 4))
    print('blur %dx%d from the corner pixel, first row:' % (size, size), row(run(corner, '--blur', '%dx%d' % (size, size)), 0, 5))
for width in ('2', '2.5', '3', '3.5', '4', '4.5', '5', '6', '7', '8', '9.5', '41'):
    print('unsharp gaussian width %s contrast 1, middle row:' % width,
          [round(v, 5) for v in row(run(middle, '--unsharp:kernel=gaussian:width=%s:contrast=1:threshold=0' % width), N // 2)])
print('median 3x3 from the corner pixel:', row(run(corner, '--median', '3x3'), 0, 3))
step = write('step.pfm', N, N, lambda x, y: (1.0 if x >= N // 2 else 0.0,) * 3)
print('median 3x3 on a step, middle row:', row(run(step, '--median', '3x3'), N // 2))
print('dilate 3x3 middle row:', row(run(middle, '--dilate', '3x3'), N // 2))
print('erode 3x3 white picture first row:', row(run(flat, '--erode', '3x3'), 0, 4))
print('laplacian middle row and the rows beside:', [row(run(middle, '--laplacian'), y)[N // 2 - 2:N // 2 + 3] for y in (N // 2 - 1, N // 2, N // 2 + 1)])
print('laplacian white picture first row:', row(run(flat, '--laplacian'), 0, 4))
colour = write('colour.pfm', 1, 1, lambda x, y: (0.8, 0.4, 0.1))
for s in ('0', '0.5', '2'):
    w, h, at = run(colour, '--saturate', s)
    print('saturate %s of (0.8, 0.4, 0.1):' % s, [round(at(0, 0, c), 7) for c in range(3)])
w, h, at = run(colour, '--chsum:weight=0.2126,0.7152,0.0722')
print('chsum of (0.8, 0.4, 0.1):', round(at(0, 0), 7))
blank = write('blank.pfm', 8, 4, lambda x, y: (0.0, 0.0, 0.0))
w, h, at = run(blank, '--pattern', 'fill:left=0,0,0:right=1,1,1', '8x4', '3', '--swap', '--pop')
print('fill left to right, 8 wide, first row:', [round(at(x, 0), 7) for x in range(8)])
w, h, at = run(blank, '--pattern', 'fill:top=0,0,0:bottom=1,1,1', '8x4', '3', '--swap', '--pop')
print('fill top to bottom, 4 high, first column:', [round(at(0, y), 7) for y in range(4)])
print('kept in', work)
