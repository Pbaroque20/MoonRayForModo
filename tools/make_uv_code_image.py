"""A float picture whose colour is where in it a pixel is, for reading how a projection lays an image out: red is u (0 at
the left edge, 1 at the right), green is v (0 at the bottom, 1 at the top), blue a constant 0.25 (none where the image
is not shown at all). Written as an OpenEXR by the runtime's oiiotool.

make_uv_code_image.py <runtime> <out.exr> [width height]"""
import os
import struct
import subprocess
import sys
from pathlib import Path


def main():
    runtime, target = Path(sys.argv[1]), Path(sys.argv[2])
    width, height = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (512, 256)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_suffix('.pfm')
    with staged.open('wb') as out:
        out.write(('PF\n%d %d\n-1.0\n' % (width, height)).encode())
        # PFM rows run bottom up: the first row is v's lowest.
        for y in range(height):
            v = (y + .5) / height
            out.write(b''.join(struct.pack('<3f', (x + .5) / width, v, .25) for x in range(width)))
    environment = dict(os.environ, PATH=str(runtime) + os.pathsep + os.environ.get('PATH', ''))
    subprocess.run([str(runtime / 'oiiotool.exe'), str(staged), '-d', 'float', '-o', str(target)], check=True, env=environment)
    staged.unlink()


if __name__ == '__main__':
    main()
