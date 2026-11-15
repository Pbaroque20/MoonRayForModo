"""A scene for XPU2's texture overflow mode by texture density: six 8192 pixel textures (more decoded than XPU2's 4 GB
texture budget), one on a plane that fills the view, five on planes far off, each a few dozen pixels wide; written by
the kit's scene writer with the texture needs it works out (texture_density), to test-results/overflow-density/scene.rdla.
Render it with xpu2/interactive/session_harness.py: the far textures are fitted to their meshes, the near one keeps its
size, and the scene loads without compressing or halving anything.

Run with the toolchain's or Windows Python: python tools/make_overflow_density_scene.py"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
OUT = ROOT / 'test-results/overflow-density'
SIDE = 8192


def main():
    import os
    from moonray_modo import native, nodes, rdla, texture_density
    OUT.mkdir(parents=True, exist_ok=True)
    tool = native.tool('oiiotool.exe')
    env = native.environment(tool.parent)
    images = []
    for index in range(6):
        image = OUT / ('checker%d.png' % index)
        if not image.is_file():
            colour = ['%.2f,%.2f,%.2f' % ((index * .17) % 1, .5, 1 - index * .15), '.05,.05,.05']
            subprocess.run([str(tool), '--pattern', 'checker:width=256:height=256:color1=%s:color2=%s' % tuple(colour),
                            '%dx%d' % (SIDE, SIDE), '3', '-d', 'uint8', '-o', str(image)], env=env, check=True)
        images.append(image)
    materials, meshes = {}, []
    for index, image in enumerate(images):
        graph = nodes.new('DwaBaseMaterial', {'roughness': .5})
        graph['nodes']['image'] = {'type': 'ImageMap', 'parameters': {'texture': str(image), 'gamma': 0}, 'inputs': {}, 'position': [0, 0]}
        graph['nodes'][graph['root']]['inputs']['albedo'] = 'image'
        tag = 'plane%d' % index
        materials[tag] = {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph, 'node_override': True,
                          'color': [.5, .5, .5]}
        # The first fills the view 10 m off; the others 2 km off, side by side.
        size, x, z = (8.0, 0.0, 0.0) if index == 0 else (8.0, (index - 3) * 30.0, -2000.0)
        half = size / 2
        meshes.append({'name': tag, 'identity': tag, 'material': tag, 'faces': [[0, 1, 2, 3]],
                       'vertices': [[-half, -half, 0], [half, -half, 0], [half, half, 0], [-half, half, 0]],
                       'uvs': [[0, 0], [1, 0], [1, 1], [0, 1]], 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, 0, z, 1]})
    scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 10, 1], 'focal_mm': 35.0, 'film_mm': 36.0},
             'materials': materials, 'meshes': meshes, 'lights': [], 'environments': [], 'time': 0.0}
    text = rdla.scene_text(scene, 640, 360, 4, 1.0, str(OUT / 'frame.exr'))
    placed = [(mesh, {mesh['material']}) for mesh in meshes]
    need = texture_density.needs(text, placed, scene['camera'], 640)
    (OUT / 'scene.rdla').write_text(text + '\n'.join(texture_density.user_data(need)) + '\n', encoding='utf-8')
    print('textures and their needs:')
    for path, side in sorted(need.items()):
        print('  %5d  %s' % (side, pathlib.Path(path).name))


if __name__ == '__main__':
    main()
