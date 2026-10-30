"""region_grid.py <ref.exr> <a.exr> [<noise.exr>] [--grid 10x6]: per-region mean (a - ref) / mean(ref) in percent,
the noise floor's the same way, and the reference's mean, as text grids (PFM via the kit's oiiotool)."""
import struct, subprocess, sys
from pathlib import Path
TOOL = r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime\oiiotool.exe'
args = [a for a in sys.argv[1:] if not a.startswith('--grid')]
grid = [a for a in sys.argv[1:] if a.startswith('--grid')]
cols, rows = (int(v) for v in (grid[0].split('=')[1] if grid else '10x6').split('x'))
def load(p):
    pfm = Path(p).with_suffix('.grid.pfm')
    subprocess.run([TOOL, str(p), '--ch', 'R,G,B', '-o', str(pfm)], check=True, capture_output=True)
    b = pfm.read_bytes(); parts = b.split(b'\n', 3); w, h = (int(v) for v in parts[1].split()); scale = float(parts[2])
    n = w * h * 3; v = struct.unpack(('<' if scale < 0 else '>') + '%df' % n, parts[3][:4 * n]); pfm.unlink()
    return w, h, v  # rows bottom to top
w, h, ref = load(args[0]); imgs = [load(p)[2] for p in args[1:]]
def grids(a):
    d = [[0.0] * cols for _ in range(rows)]; r = [[0.0] * cols for _ in range(rows)]
    for y in range(h):
        gy = (h - 1 - y) * rows // h
        for x in range(w):
            k = 3 * (y * w + x); gx = x * cols // w
            d[gy][gx] += sum(a[k:k + 3]) - sum(ref[k:k + 3]); r[gy][gx] += sum(ref[k:k + 3])
    return d, r
for name, a in zip(args[1:], imgs):
    d, r = grids(a)
    print(Path(name).name, '(a - ref) / ref, percent; whole %.3f%%' % (100 * sum(map(sum, d)) / sum(map(sum, r))))
    for gy in range(rows): print(' '.join('%6.2f' % (100 * d[gy][gx] / r[gy][gx] if r[gy][gx] else 0) for gx in range(cols)))
_, r = grids(ref)
print('reference mean per pixel')
for gy in range(rows): print(' '.join('%6.3f' % (r[gy][gx] / 3 / (w * h / cols / rows)) for gx in range(cols)))
