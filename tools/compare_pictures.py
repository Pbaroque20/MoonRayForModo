"""Compare two pictures (R, G, B): the mean |difference| over the mean value (relative), the share of pixels within 5%
and 10% of the first's value (of those lit above 1% of its largest), and, given an output path, the two side by side
and their difference times 8, as sRGB.

compare_pictures.py <runtime> <a.exr> <b.exr> [out.png]"""
import struct
import subprocess
import sys
from pathlib import Path


def pixels(runtime, source):
    target = Path(str(source) + '.compare.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(source), '--ch', 'R,G,B', '-d', 'float', '-o', str(target)], check=True)
    data = target.read_bytes()
    parts = data.split(b'\n', 3)
    width, height = (int(v) for v in parts[1].split())
    values = struct.unpack(('<' if float(parts[2]) < 0 else '>') + '%df' % (width * height * 3), parts[3][:width * height * 12])
    target.unlink()
    return width, height, values


def main():
    runtime, a, b = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    (wa, ha, va), (wb, hb, vb) = pixels(runtime, a), pixels(runtime, b)
    if (wa, ha) != (wb, hb):
        raise SystemExit('sizes differ')
    mean = sum(va) / len(va)
    difference = sum(abs(x - y) for x, y in zip(va, vb)) / len(va)
    peak = max(va) or 1.0
    lit = [(sum(va[i:i + 3]), sum(vb[i:i + 3])) for i in range(0, len(va), 3) if sum(va[i:i + 3]) > peak * .03]
    within = [sum(1 for x, y in lit if abs(x - y) <= f * x) / max(1, len(lit)) for f in (.05, .10)]
    print('mean |a-b| / mean a: %.4f; lit pixels within 5%%: %.3f, within 10%%: %.3f; mean a/b %.4f'
          % (difference / (mean or 1.0), within[0], within[1], mean / ((sum(vb) / len(vb)) or 1.0)))
    if len(sys.argv) > 4:
        out = Path(sys.argv[4])
        diff = out.with_suffix('.diff.exr')
        subprocess.run([str(runtime / 'oiiotool.exe'), str(a), '--ch', 'R,G,B', str(b), '--ch', 'R,G,B', '--absdiff', '--mulc', '8', '-o', str(diff)],
                       check=True)
        subprocess.run([str(runtime / 'oiiotool.exe'), str(a), '--ch', 'R,G,B', str(b), '--ch', 'R,G,B', str(diff), '--ch', 'R,G,B',
                        '--mosaic', '3x1', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out)], check=True)
        diff.unlink()


if __name__ == '__main__':
    main()
