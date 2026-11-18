"""Render the item-mask scene as the plugin exported it (tools/probe_cl_item_mask_kinds.py) with MoonRay, and read each
cube's colour in Modo's render and in MoonRay's: the average of a small square at its middle, brightness set aside
(each channel's share). Each cube should come out its mask's colour in both, and the last the Base Material's grey.
A picture of the pair, Modo above, is written beside them. Usage: check_item_mask_kinds.py <runtime> [rdla in the folder, reopened.rdla by default]"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/item-mask-kinds'
# Where each cube's middle falls in the 1320 x 200 picture: the camera 16 away (15.6 to the cubes' faces), a 50 mm
# lens on 36 mm film, the cubes 1.2 apart in the probe's order.
SCALE = 660 / (15.6 * 18 / 50)
NAMES = ('Locator, red', 'Nested, magenta', 'Group Locator, green', 'Group, blue', 'Sub-group, cyan',
         'Sub-group applied, orange', 'Group of a locator, purple', 'Group of a plain locator, azure', 'Mesh, yellow', 'Other')
CUBES = tuple((name, 1.2 * (index - (len(NAMES) - 1) / 2)) for index, name in enumerate(NAMES))


def colour(picture, x, y=100, half=4):
    width, height, values = picture
    total = [0.0, 0.0, 0.0]
    for j in range(y - half, y + half + 1):
        for i in range(x - half, x + half + 1):
            for c in range(3):
                total[c] += values[(j * width + i) * 3 + c]
    whole = sum(total) or 1.0
    return ' '.join('%.2f' % (v / whole) for v in total)


runtime = native.find_runtime(sys.argv[1])
output = folder / 'moonray.exr'
done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / (sys.argv[2] if len(sys.argv) > 2 else 'reopened.rdla')), '-out', str(output), '-exec_mode', 'scalar'],
                      env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if done.returncode or not output.is_file():
    raise SystemExit('MoonRay did not render: ' + done.stdout.decode(errors='replace')[-600:])
modo = next(folder.glob('modo*.exr'))
ours, theirs = pixels(runtime, output), pixels(runtime, modo)
for name, position in CUBES:
    x = int(round(660 + position * SCALE))
    print('%-28s Modo %s   MoonRay %s' % (name, colour(theirs, x), colour(ours, x)))
subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '1x2',
                '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / 'pair.png')], env=native.environment(runtime), check=True)
