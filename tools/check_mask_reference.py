"""Render the mask reference scene as the plugin exported it (tools/probe_cl_mask_reference.py) with MoonRay, and
read each cube's colour in Modo's render and in MoonRay's: the average of a small square at its middle, brightness
set aside (each channel's share). Each cube should come out its mask's colour in both. A picture of the pair, Modo
above, is written beside them. Usage: check_mask_reference.py <runtime>"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/mask-reference'
# Where each cube's middle falls in the 640 x 240 picture: the camera 7 away, a 50 mm lens on 36 mm film.
SCALE = 320 / (6.6 * 18 / 50)
CUBES = (('Material mask, red', -1.8), ('Part mask, green', -0.6), ('Selection Set mask, blue', 0.6), ('Item mask, yellow', 1.8))


def colour(picture, x, y=120, half=4):
    width, height, values = picture
    total = [0.0, 0.0, 0.0]
    for j in range(y - half, y + half + 1):
        for i in range(x - half, x + half + 1):
            for c in range(3):
                total[c] += values[(j * width + i) * 3 + c]
    whole = sum(total) or 1.0
    return ' '.join('%.2f' % (v / whole) for v in total)


runtime = native.find_runtime(sys.argv[1])
output = folder / 'moonray_masks.exr'
done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / 'masks.rdla'), '-out', str(output), '-exec_mode', 'scalar'],
                      env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if done.returncode or not output.is_file():
    raise SystemExit('MoonRay did not render: ' + done.stdout.decode(errors='replace')[-600:])
modo = next(folder.glob('modo_masks*.exr'))
ours, theirs = pixels(runtime, output), pixels(runtime, modo)
for name, position in CUBES:
    x = int(round(320 + position * SCALE))
    print('%-26s Modo %s   MoonRay %s' % (name, colour(theirs, x), colour(ours, x)))
subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '1x2',
                '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / 'pair_masks.png')], env=native.environment(runtime), check=True)
