"""Brightness on a ring of tools/probe_cl_ies_lights.py's floor (camera 8 units up, a 5.76 unit square seen), around a
centre point, every 15 degrees: angle 0 is +x, 90 is -z (up the picture), as seen from above.

read_ies_ring.py <runtime> <picture.exr> [radius] [cx cz]"""
import math
import struct
import subprocess
import sys
from pathlib import Path


def pixels(runtime, source):
    target = Path(str(source) + '.ring.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    target.unlink()
    return width, height, values


def at(width, height, values, x, z):
    """The mean of a 3 x 3 patch at floor point (x, z); PFM rows run bottom up, the picture's bottom +z."""
    column = int((x / 5.76 + .5) * width)
    row = int((.5 - z / 5.76) * height)
    found = [values[((r * width) + c) * 3] for r in range(row - 1, row + 2) for c in range(column - 1, column + 2)
             if 0 <= r < height and 0 <= c < width]
    return sum(found) / len(found) if found else 0.0


if __name__ == '__main__':
    runtime, source = Path(sys.argv[1]), Path(sys.argv[2])
    radius = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    cx, cz = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (0.0, 0.0)
    width, height, values = pixels(runtime, source)
    print(' '.join('%3d:%.4f' % (a, at(width, height, values, cx + radius * math.cos(math.radians(a)), cz - radius * math.sin(math.radians(a))))
                   for a in range(0, 360, 15)))
