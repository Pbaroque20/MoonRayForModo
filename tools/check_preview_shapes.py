"""The graph editor preview's other shapes (preview_shapes) rendered in MoonRay with a material each is for: water with
the Ocean node, subsurface with DwaBaseMaterial's subsurface, velvet with DwaVelvetMaterial_v2. Writes
test-results/preview-shapes/<shape>.exr and .png; MOONRAY_RUNTIME the runtime, else the installed kit's."""
import os
import pathlib
import subprocess
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
os.environ.setdefault('MOONRAY_MODO_OCEAN', '1')
from moonray_modo import coordinates, native, nodes, ocean, preview_shapes, rdla  # noqa: E402
from moonray_modo.rdla import IDENTITY  # noqa: E402

RUNTIME = pathlib.Path(os.environ.get('MOONRAY_RUNTIME') or pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')
out = ROOT / 'test-results/preview-shapes'
out.mkdir(parents=True, exist_ok=True)


def material(shape):
    if shape == 'water':
        graph = nodes.new('DwaBaseMaterial', {'albedo': [0.01, 0.03, 0.04], 'roughness': 0.03, 'refractive_index': 1.33})
        graph['nodes']['sea'] = {'type': 'ocean', 'parameters': {'size': 20.0, 'repeat': [5.0, 5.0], 'resolution': 256, 'wind_speed': 7.0,
                                                                 'wind_direction': 30.0}, 'inputs': {}, 'position': [0, 0]}
        graph['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {}, 'inputs': {'vector': 'sea'}, 'position': [0, 0]}
        graph['displacement'] = 'push'
        return {'node_graph': graph, 'native_shader': 'DwaBaseMaterial', 'node_override': True, 'native_parameters': {}}
    if shape == 'subsurface':
        return {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'albedo': [0.9, 0.55, 0.4],
                                                                          'scattering_color': [0.95, 0.45, 0.3], 'scattering_radius': 0.4,
                                                                          'roughness': 0.35}}
    return {'native_shader': 'DwaVelvetMaterial_v2', 'native_parameters': {'albedo': [0.45, 0.04, 0.12], 'fuzz_albedo': [0.9, 0.25, 0.4]}}


def main():
    for shape in ('water', 'subsurface', 'velvet'):
        made = preview_shapes.made(shape, 1.0)
        materials = {'preview': material(shape), '': {'color': [.18, .18, .18], 'roughness': .3}}
        for mesh in made['meshes']:
            mesh['matrix'] = IDENTITY[:]
            mesh['material'] = 'preview' if mesh['name'] != made.get('floor') else ''
            mesh['uv_sets'] = {}
        scene = {'camera': made['camera'], 'meshes': made['meshes'], 'materials': materials, 'lights': made['lights'],
                 'environments': made['environments'], 'native_materials': {}, 'fps': 24, 'time': 0.0}
        target = out / (shape + '.exr')
        with mock.patch.object(native, 'default_runtime', return_value=str(RUNTIME)), ocean.writing(0.0, str(RUNTIME)):
            text = rdla.scene_text(scene, 480, 270, 16, 0.0, str(target))
        source = out / (shape + '.rdla')
        source.write_text(text, encoding='utf-8')
        done = subprocess.run([str(RUNTIME / 'moonray.exe'), '-in', str(source), '-out', str(target)], env=native.environment(RUNTIME),
                              capture_output=True, text=True, timeout=900)
        print(shape, 'moonray', done.returncode, done.stdout[-300:] if done.returncode else '')
        subprocess.run([str(RUNTIME / 'oiiotool.exe'), str(target), '--ch', 'R,G,B', '--colorconvert', 'linear', 'sRGB', '-d', 'uint8',
                        '-o', str(target.with_suffix('.png'))], env=native.environment(RUNTIME), capture_output=True, timeout=120)


if __name__ == '__main__':
    main()
