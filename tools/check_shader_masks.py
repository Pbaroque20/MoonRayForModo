"""Render the scene tools/probe_shader_masks.py exported with MoonRay, and read each cube's colour in Modo's render and
in MoonRay's (the average of a small square at its middle, brightness set aside: the colour's share of each channel).
Each cube should come out the colour of its mask in both. A picture of the pair, Modo left, is written beside them.
Usage: check_shader_masks.py <runtime>"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/shader-masks'
CUBES = (('Left (item mask, red)', 40), ('Middle (part, green)', 120), ('Right (selection set, blue)', 200))


def colour(picture, x, y=60, half=3):
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
for name, x in CUBES:
    print('%-28s Modo %s   MoonRay %s' % (name, colour(theirs, x), colour(ours, x)))
subprocess.run([str(runtime / 'oiiotool.exe'), str(modo), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B', '--mosaic', '2x1',
                '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / 'pair_masks.png')], env=native.environment(runtime), check=True)
