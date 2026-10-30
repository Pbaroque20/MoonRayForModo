"""pixels.py <exr> <channels, comma separated (at most 3)> <x> <y> <w> <h>: the pixels of a window as rows of values."""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime\oiiotool.exe'
exr, chans, x, y, w, h = sys.argv[1], sys.argv[2].split(','), *map(int, sys.argv[3:7])
pfm = Path(tempfile.mkdtemp()) / 'p.pfm'
spec = ','.join(chans + ['pad%d=0' % k for k in range(3 - len(chans))])
subprocess.run([TOOL, exr, '--ch', spec, '--cut', '%dx%d+%d+%d' % (w, h, x, y), '-d', 'float', '-o', str(pfm)], check=True, capture_output=True)
data = pfm.read_bytes().split(b'\n', 3)
W, H = map(int, data[1].split())
v = struct.unpack('<%df' % (W * H * 3), data[3][:W * H * 12])
for row in range(H - 1, -1, -1):  # PFM rows run bottom up
    print(' '.join('/'.join('%.4f' % v[(row * W + col) * 3 + k] for k in range(len(chans))) for col in range(W)))
