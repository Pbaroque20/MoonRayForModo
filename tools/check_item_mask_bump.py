"""Render the bump scene as the plugin exported it (tools/probe_cl_item_mask_bump.py) with MoonRay, and read each cube's
front face in Modo's render and in MoonRay's: its colour (each channel's share) and how much it varies across the face
(the standard deviation of its brightness over its mean), which a bump showing through raises. A picture of the pair,
Modo above, is written beside them. Usage: check_item_mask_bump.py <runtime>"""
import statistics
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/item-mask-bump'
# The 900 x 300 picture: the camera 12 away (11.2 to the cubes' faces), a 50 mm lens on 36 mm film.
SCALE = 450 / (11.2 * 18 / 50)
CUBES = (('Member (Group mask), blue', -2.4), ('Tagged (material tag), red', 0.0), ('Other (bump alone)', 2.4))


def face(picture, x, y=150, half=20):
    width, height, values = picture
    total, bright = [0.0, 0.0, 0.0], []
    for j in range(y - half, y + half + 1):
        for i in range(x - half, x + half + 1):
            rgb = values[(j * width + i) * 3:(j * width + i) * 3 + 3]
            for c in range(3):
                total[c] += rgb[c]
            bright.append(sum(rgb))
    whole = sum(total) or 1.0
    mean = statistics.mean(bright) or 1.0
    return '%s  varies %.3f' % (' '.join('%.2f' % (v / whole) for v in total), statistics.pstdev(bright) / mean)


runtime = native.find_runtime(sys.argv[1])
output = folder / 'moonray.exr'
done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / 'bump.rdla'), '-out', str(output), '-exec_mode', 'scalar'],
                      env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if done.returncode or not output.is_file():
    raise SystemExit('MoonRay did not render: ' + done.stdout.decode(errors='replace')[-600:])
modo = next(folder.glob('modo*.exr'))
ours, theirs = pixels(runtime, output), pixels(runtime, modo)
for name, position in CUBES:
    x = int(round(450 + position * SCALE))
    print('%-28s Modo %s   MoonRay %s' % (name, face(theirs, x), face(ours, x)))
subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '1x2',
                '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / 'pair.png')], env=native.environment(runtime), check=True)
