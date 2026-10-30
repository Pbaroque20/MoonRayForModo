"""Block-mean comparison of EXR pictures: block_cmp.py <oiiotool> <reference.exr> <a.exr> [<b.exr> ...].
Each picture against the reference: mean of |block mean difference| / reference block mean over 8x8 blocks with some
light, the worst block, and the overall mean ratio."""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def load(tool, exr):
    pfm = Path(tempfile.mkdtemp()) / 'x.pfm'
    subprocess.run([tool, exr, '-o', str(pfm)], check=True, capture_output=True)
    data = pfm.read_bytes()
    parts = data.split(b'\n', 3)
    w, h = map(int, parts[1].split())
    px = struct.unpack('<%df' % (w * h * 3), parts[3][:w * h * 12])
    return w, h, px


def blocks(w, h, px, n=8):
    out = {}
    for by in range(h // n):
        for bx in range(w // n):
            s = 0.0
            for y in range(by * n, by * n + n):
                for x in range(bx * n, bx * n + n):
                    i = (y * w + x) * 3
                    s += px[i] + px[i + 1] + px[i + 2]
            out[(bx, by)] = s / (3 * n * n)
    return out


tool = sys.argv[1]
w, h, ref = load(tool, sys.argv[2])
rb = blocks(w, h, ref)
for other in sys.argv[3:]:
    _, _, px = load(tool, other)
    ob = blocks(w, h, px)
    rel = [(abs(ob[k] - v) / v, k) for k, v in rb.items() if v > 0.02]
    mean_ref = sum(ref) / len(ref)
    mean_o = sum(px) / len(px)
    print('%s: block error %.4f, worst %.4f at %s, mean ratio %.4f' % (Path(other).name, sum(r for r, _ in rel) / len(rel),
                                                                      max(rel)[0], max(rel)[1], mean_o / mean_ref))
