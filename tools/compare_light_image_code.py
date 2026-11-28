"""Compare two renders of tools/probe_cl_light_images.py's scenes (Modo's and MoonRay's) by the image coordinate each
pixel shows (read_light_image_code.code: u = R / 4B, v = G / 4B), over the pixels lit in both: the mean and the 95th
percentile of |du| and |dv|, and the ratio of their mean brightness (B). Also writes <out>.png: the two side by side.

compare_light_image_code.py <runtime> <modo.exr> <moonray.exr> [out]"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from read_light_image_code import code  # noqa: E402


def main():
    runtime, first, second = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    a, b = code(runtime, first), code(runtime, second)
    both = [k for k in a if k in b]
    if not both:
        print('no pixel lit in both')
        return
    du = sorted(abs(a[k][0] - b[k][0]) for k in both)
    dv = sorted(abs(a[k][1] - b[k][1]) for k in both)
    bright = sum(a[k][2] for k in both) / max(1e-12, sum(b[k][2] for k in both))
    print('%d pixels: |du| mean %.4f p95 %.4f, |dv| mean %.4f p95 %.4f; brightness modo/moonray %.3f'
          % (len(both), sum(du) / len(du), du[int(.95 * (len(du) - 1))], sum(dv) / len(dv), dv[int(.95 * (len(dv) - 1))], bright))
    if len(sys.argv) > 4:
        out = Path(sys.argv[4])
        subprocess.run([str(runtime / 'oiiotool.exe'), str(first), '--ch', 'R,G,B', str(second), '--ch', 'R,G,B', '--mosaic', '2x1',
                        '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(out)], check=True)


if __name__ == '__main__':
    main()
