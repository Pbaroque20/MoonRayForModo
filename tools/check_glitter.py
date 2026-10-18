"""Render DwaBaseMaterial's glitter with MoonRay, as the plugin writes it, to find what makes it fail.

A ball of glitter (DwaBaseMaterial with Glitter shown) under a distant light, rendered in each of MoonRay's modes
(vectorized, scalar, xpu) and with each glitter space (reference, the default, and object), and once more with the
plain material for comparison. Printed for each: whether MoonRay finished, its exit code, the last lines it printed
on failure, and the picture's average brightness. Usage: check_glitter.py <moonray-runtime> [mode ...]"""
import math
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
from check_fresnel import pixels  # noqa: E402  (also sets the plugin's modules up without Modo)
from moonray_modo import native, rdla  # noqa: E402

folder = root / 'test-results/glitter'


def ball():
    rings, around = 24, 48
    vertices, faces, uvs = [], [], []
    for i in range(rings + 1):
        for j in range(around + 1):
            theta, phi = math.pi * i / rings, 2 * math.pi * j / around
            vertices.append([math.sin(theta) * math.cos(phi), math.cos(theta), math.sin(theta) * math.sin(phi)])
            uvs.append([j / around, 1 - i / rings])
    for i in range(rings):
        for j in range(around):
            a = i * (around + 1) + j
            faces.append([a, a + around + 1, a + around + 2, a + 1])
    # UVs by face corner, as the plugin writes them.
    return vertices, faces, [uvs[corner] for face in faces for corner in face]


def scene(parameters):
    vertices, faces, uvs = ball()
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 50, 'film_mm': 36},
            'materials': {'': {'native_shader': 'DwaBaseMaterial', 'native_parameters': parameters}},
            'meshes': [{'name': 'Ball', 'identity': 'ball', 'vertices': vertices, 'faces': faces, 'uvs': uvs, 'matrix': rdla.IDENTITY}],
            'lights': [{'identity': 'key', 'name': 'Key', 'kind': 'DistantLight', 'color': [1, 1, 1], 'intensity': 2.0,
                        'matrix': [1, 0, 0, 0, 0, .7, .7, 0, 0, -.7, .7, 0, 0, 0, 0, 1]}]}


def render(runtime, name, value, mode):
    output = folder / ('%s_%s.exr' % (name, mode))
    source = folder / ('%s_%s.rdla' % (name, mode))
    source.write_text(rdla.scene_text(value, 160, 160, 4, 0.1, str(output)), encoding='utf-8')
    if output.exists():
        output.unlink()
    try:
        done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(source, output, 0, mode), env=native.environment(runtime),
                              cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
    except subprocess.TimeoutExpired:
        return 'TIMED OUT', None, ''
    text = done.stdout.decode(errors='replace')
    if done.returncode or not output.is_file():
        return 'FAILED (exit %d, 0x%08x)' % (done.returncode, done.returncode & 0xffffffff), None, '\n'.join(text.splitlines()[-6:])
    width, height, values = pixels(runtime, output)
    return 'ok', sum(values[1::3]) / (width * height), ''


def main():
    runtime = Path(sys.argv[1]).resolve()
    modes = sys.argv[2:] or ['vectorized', 'scalar', 'xpu']
    folder.mkdir(parents=True, exist_ok=True)
    cases = [('plain', {}),
             ('glitter_reference', {'show_glitter': True, 'glitter': 1.0}),
             ('glitter_object', {'show_glitter': True, 'glitter': 1.0, 'glitter_space': 4})]
    for mode in modes:
        for name, parameters in cases:
            status, brightness, tail = render(runtime, name, scene(parameters), mode)
            print('%-10s %-18s %s%s' % (mode, name, status, '' if brightness is None else '  brightness %.4f' % brightness), flush=True)
            if tail:
                print('    ' + tail.replace('\n', '\n    '))


if __name__ == '__main__':
    main()
