"""Render the scenes tools/probe_scene_export.py exported with MoonRay, and compare each picture with the RDLA's: the
RDLB, the split scene (RDLA + RDLB, given to MoonRay together), the RDLA with its textures collected (rendered from its
own folder, as its paths are relative to it), the middle frame of the frame range and the beauty-only scene should all
show the same picture. Pictures are compared by the average difference of their pixels. Usage: check_scene_export.py
<runtime>"""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from moonray_modo import native  # noqa: E402

folder = root / 'test-results/scene-export'
SCENES = (('rdla', ['rdla/rdla.rdla']), ('rdlb', ['rdlb/rdlb.rdlb']), ('split', ['split/split.rdla', 'split/split.rdlb']),
          ('collected', ['collected/collected.rdla']), ('frames', ['frames/frames.0001.rdla']),
          ('beauty', ['beauty/beauty.rdla']), ('menu', ['menu/menu.rdlb']))


def render(runtime, name, scenes):
    output = folder / 'check' / (name + '.exr')
    output.parent.mkdir(exist_ok=True)
    command = [str(runtime / 'moonray.exe')]
    for scene in scenes:
        command += ['-in', str((folder / scene).resolve())]
    command += ['-out', str(output), '-exec_mode', 'scalar', '-threads', '8']
    done = subprocess.run(command, env=native.environment(runtime), cwd=str((folder / scenes[0]).parent),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if done.returncode or not output.is_file():
        print('%-10s did not render: %s' % (name, done.stdout.decode(errors='replace')[-800:]), flush=True)
        return None
    return pixels(runtime, output)[2]


runtime = native.find_runtime(sys.argv[1])
reference = None
for name, scenes in SCENES:
    picture = render(runtime, name, scenes)
    if picture is None:
        continue
    if reference is None:
        reference = picture
    mean = sum(picture) / len(picture)
    difference = sum(abs(a - b) for a, b in zip(picture, reference)) / len(picture)
    print('%-10s average %.4f   difference from the RDLA %.4f' % (name, mean, difference), flush=True)
