"""Render the procedural-bump scene as the plugin exported it (tools/probe_cl_procedural_bump.py) with MoonRay, and say
how much each cube's front face varies (the standard deviation of its brightness over its mean) in Modo's render and in
MoonRay's: a bump showing raises it well above a flat face's (about 0.01, MoonRay's sampling noise). A picture of the
pair, Modo above, is written beside them; MoonLightIPR's, where saved (moonlightipr.png), is measured too.
Usage: check_procedural_bump.py <runtime> [output name]"""
import statistics
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/procedural-bump'
# The 1200 x 300 picture: the camera 16 away (15.2 to the cubes' faces), a 50 mm lens on 36 mm film, cubes 2.4 apart.
SCALE = 600 / (15.2 * 18 / 50)
NAMES = ('Noise', 'Checker', 'Noise fine', 'Noise, no UVs')
CUBES = tuple((name, 2.4 * (index - (len(NAMES) - 1) / 2)) for index, name in enumerate(NAMES))


def varies(picture, x, y=150, half=30):
    width, height, values = picture
    bright = [sum(values[(j * width + i) * 3:(j * width + i) * 3 + 3]) for j in range(y - half, y + half + 1) for i in range(x - half, x + half + 1)]
    return statistics.pstdev(bright) / (statistics.mean(bright) or 1.0)


runtime = native.find_runtime(sys.argv[1])
name = sys.argv[2] if len(sys.argv) > 2 else 'moonray'
output = folder / (name + '.exr')
done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(folder / 'bump.rdla'), '-out', str(output), '-exec_mode', 'scalar'],
                      env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
if done.returncode or not output.is_file():
    raise SystemExit('MoonRay did not render: ' + done.stdout.decode(errors='replace')[-600:])
pictures = [('Modo', pixels(runtime, next(folder.glob('modo*.exr')))), ('MoonRay', pixels(runtime, output))]
if (folder / 'moonlightipr.png').is_file():
    pictures.append(('MoonLightIPR', pixels(runtime, folder / 'moonlightipr.png')))
for cube, position in CUBES:
    x = int(round(600 + position * SCALE))
    print('%-15s ' % cube + '   '.join('%s %.3f' % (label, varies(picture, x)) for label, picture in pictures))
subprocess.run([str(runtime / 'oiiotool.exe'), str(next(folder.glob('modo*.exr'))), '--ch', 'R,G,B', str(output), '--ch', 'R,G,B',
                '--mosaic', '1x2', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8', '-o', str(folder / ('pair_%s.png' % name))],
               env=native.environment(runtime), check=True)
