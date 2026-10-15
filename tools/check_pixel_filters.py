"""Render one scene with each of MoonRay's pixel filters and say how soft each makes the picture.

A comparison scene (two balls on a checkered floor, from tools/compare_moonlightipr.py) is rendered small with every
pixel filter at the default width of 3, in the execution mode named (xpu, vectorized or scalar), with the runtime named.
How soft each picture is is read as the mean difference between neighbouring pixels: a softer filter makes it smaller.
Box and the B-splines are MoonRay's own; Gaussian, Triangle and Blackman-Harris are the plugin's additions.

check_pixel_filters.py <runtime folder> [mode]"""
import pathlib
import re
import struct
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

FILTERS = ['box', 'cubic b-spline', 'quadratic b-spline', 'gaussian', 'triangle', 'blackman-harris']


def main():
    runtime = pathlib.Path(sys.argv[1]).resolve()
    mode = sys.argv[2] if len(sys.argv) > 2 else 'xpu'
    out = root / 'test-results/pixel-filters'
    out.mkdir(parents=True, exist_ok=True)
    text = (root / 'build/moonlightipr/compare/dwa_skin.rdla').read_text(encoding='utf-8')
    text = re.sub(r'  \["pixel_filter"\] = [^\n]*\n', '', text)
    text = re.sub(r'  \["pixel_filter_width"\] = [^\n]*\n', '', text)
    for index, name in enumerate(FILTERS):
        scene = out / ('%s_%d.rdla' % (mode, index))
        target = out / ('%s_%d.exr' % (mode, index))
        scene.write_text(text.replace('SceneVariables {', 'SceneVariables {\n  ["pixel_filter"] = %d,\n  ["pixel_filter_width"] = 3,' % index, 1), encoding='utf-8')
        if target.is_file():
            target.unlink()
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(scene, target, 0, mode), env=native.environment(runtime),
                              cwd=str(out), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000)
        log = done.stdout.decode(errors='replace')
        warned = 'Unknown pixel filter' in log
        reported = re.search(r'Pixel filter type\s*\|?\s*(\w+)', log)
        if done.returncode or not target.is_file():
            print('%-20s FAILED (%d)\n%s' % (name, done.returncode, log[-800:]))
            continue
        pfm = target.with_suffix('.pfm')
        subprocess.run([str(runtime / 'oiiotool.exe'), str(target), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=native.environment(runtime),
                       creationflags=0x08000000, check=True)
        data = pfm.read_bytes()
        header = data.split(b'\n', 3)
        width, height = map(int, header[1].split())
        values = struct.unpack(('<' if float(header[2]) < 0 else '>') + '%df' % (width * height * 3), header[3])
        luma = [values[i * 3] * .2126 + values[i * 3 + 1] * .7152 + values[i * 3 + 2] * .0722 for i in range(width * height)]
        detail = sum(abs(luma[y * width + x] - luma[y * width + x + 1]) for y in range(height) for x in range(width - 1)) / (height * (width - 1))
        print('%-20s detail %.5f%s%s' % (name, detail, '  (MoonRay said: %s)' % reported.group(1) if reported else '',
                                          '  WARNING: MoonRay did not know it' if warned else ''))


if __name__ == '__main__':
    main()
