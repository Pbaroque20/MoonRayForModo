"""Render the anisotropy grid tools/probe_aniso_direction.py exported (MOONRAY_PROBE_GRID) with MoonRay, as the plugin
wrote it, and say how far each picture is from Modo's own render of it: the root mean square difference of their
green channel over the frame, capped at 4 so that the hottest pixels do not rule. Usage: check_aniso_direction.py <runtime>"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/aniso-direction'
runtime = native.find_runtime(sys.argv[1])
green = lambda values: [min(4.0, values[i + 1]) for i in range(0, len(values), 3)]
total = []
for scene in sorted(folder.glob('grid_*.rdla')):
    output = folder / ('moonray_' + scene.stem + '.exr')
    subprocess.run([str(runtime / 'moonray.exe'), '-in', str(scene), '-out', str(output), '-exec_mode', 'scalar'],
                   env=native.environment(runtime), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ours = green(pixels(runtime, output)[2])
    theirs = green(pixels(runtime, folder / ('modo_%s.Final Color Output.0001.exr' % scene.stem))[2])
    error = (sum((a - b) ** 2 for a, b in zip(ours, theirs)) / len(ours)) ** .5
    total.append(error)
    print('%-16s %.4f' % (scene.stem, error), flush=True)
print('mean %.4f' % (sum(total) / max(1, len(total))))
