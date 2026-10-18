"""A layered environment turned by its locator, baked turned (as before) and baked at rest with the turn given to the
light (environment_layers.held_placement): MoonRay's two pictures should be the same.
Usage: check_env_placement.py <runtime> <hdri>"""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (sets the plugin's modules up without Modo)
from time_hdri_rotation import turned  # noqa: E402
from moonray_modo import environment_layers, native, rdla  # noqa: E402

folder = root / 'test-results/hdri-rotation'


def scene(hdri, degrees):
    image = {'kind': 'image', 'path': str(hdri), 'srgb': False, 'color_space': '(default)', 'matrix': turned(degrees),
             'intensity': 1.0, 'effect': 'envColor', 'opacity': .9, 'blend': 'normal', 'invert': False,
             'uv_matrix': [1, 0, 0, 0, 1, 0], 'rotation': 0, 'scale': [1, 1], 'transformed': False}
    under = {'kind': 'color', 'color': [.2, .3, .4], 'effect': 'envColor', 'opacity': 1, 'blend': 'normal', 'invert': False}
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 20, 'film_mm': 36},
            'materials': {'': {'color': [.8, .8, .8], 'roughness': .2}},
            'meshes': [{'name': 'Quad', 'identity': 'quad', 'vertices': [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                        'faces': [[0, 1, 2, 3]], 'matrix': rdla.IDENTITY}],
            'environments': [{'kind': 'stack', 'intensity': 1.0, 'layers': [image, under]}], 'render_settings': {'sampling_mode': 0}}


def render(runtime, name, value):
    output = folder / (name + '.exr')
    source = folder / (name + '.rdla')
    source.write_text(rdla.scene_text(value, 320, 180, 3, 0.0, str(output)), encoding='utf-8')
    subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(source, output, 0, 'vectorized'), env=native.environment(runtime),
                   cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
    return pixels(runtime, output)


def main():
    runtime, hdri = native.find_runtime(Path(sys.argv[1])), Path(sys.argv[2])
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    folder.mkdir(parents=True, exist_ok=True)
    value = scene(hdri, 90)
    held = environment_layers.held_placement(value['environments'][0])
    print('held placement:', 'yes' if held else 'no')
    new = render(runtime, 'placement_held', value)
    keep = environment_layers.held_placement
    environment_layers.held_placement = lambda environment: None
    try:
        old = render(runtime, 'placement_baked', value)
    finally:
        environment_layers.held_placement = keep
    a, b = old[2], new[2]
    difference = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    mean = sum(a) / len(a)
    print('baked turned: average %.4f; at rest, light turned: average %.4f; average difference %.4f (%.1f%% of the average)'
          % (mean, sum(b) / len(b), difference, 100 * difference / max(1e-9, mean)))


if __name__ == '__main__':
    main()
