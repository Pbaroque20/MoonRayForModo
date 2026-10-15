"""MoonRay's global switches, each turned from its default, and what it does to the picture.

Renders comparison scenes (tools/compare_moonlightipr.py) in MoonRay with each switch at its default and turned, and
says how much of the picture changed: shadows, subsurface scattering, displacement, lights seen by the camera, a limit
to geometry resolution, and a dicing camera of its own.

check_global_switches.py <runtime folder>"""
import math
import pathlib
import struct
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'tools'), str(root / 'kit/MoonRayForModo/python')]
from moonray_modo import native, nodes, rdla
import compare_moonlightipr as compare

WIDTH, HEIGHT = 240, 160


def render(scene, runtime, folder, name):
    exr, scene_file = folder / (name + '.exr'), folder / (name + '.rdla')
    scene_file.write_text(rdla.scene_text(scene, WIDTH, HEIGHT, 4, scene.get('_environment', 0.3), str(exr)), encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(scene_file, folder / (name + '_main.exr'), 0, 'scalar'),
                          env=native.environment(runtime), cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=0x08000000)
    log = done.stdout.decode(errors='replace')
    if done.returncode or not exr.is_file():
        raise RuntimeError('%s did not render:\n%s' % (name, log[-1500:]))
    pfm = folder / (name + '.pfm')
    subprocess.run([str(runtime / 'oiiotool.exe'), str(exr), '--ch', 'R,G,B', '-d', 'float', '-o', str(pfm)], env=native.environment(runtime),
                   creationflags=0x08000000, check=True)
    data = pfm.read_bytes()
    header = data.split(b'\n', 3)
    width, height = map(int, header[1].split())
    values = struct.unpack('<%df' % (width * height * 3), header[3])
    return [sum(values[i:i + 3]) / 3 for i in range(0, len(values), 3)], [l for l in log.splitlines() if 'Warning' in l or 'Error' in l]


def changed(a, b):
    """The share of pixels that changed by more than a twentieth, and the change in mean brightness."""
    moved = sum(1 for x, y in zip(a, b) if abs(x - y) > .05 * max(x, y, .05)) / len(a)
    return moved, sum(b) / max(sum(a), 1e-9)


def with_settings(scene, **settings):
    return dict(scene, render_settings=dict(scene.get('render_settings', {}), **settings))


def main():
    runtime = native.find_runtime(sys.argv[1])
    folder = root / 'test-results/global-switches'
    folder.mkdir(parents=True, exist_ok=True)
    scenes = compare.scenes(folder)
    lit, skin = scenes['spot_light'], scenes['dwa_skin']
    # A ball pushed out along its normals by a displacement, for displacement and geometry resolution.
    graph = nodes.new()
    graph['nodes']['push'] = {'type': 'NormalDisplacement', 'parameters': {'height': .15, 'bound_padding': .3}}
    graph['displacement'] = 'push'
    swollen = dict(lit, materials={tag: dict(material, node_graph=graph) for tag, material in lit['materials'].items()})
    # The same as subdivision surfaces, tessellated as finely as the camera asks (an error of 8 pixels), which is what a
    # dicing camera is used for.
    adaptive = dict(swollen, meshes=[dict(mesh, geometry_settings=dict(mesh.get('geometry_settings') or {}, adaptive_error=8.0), adaptive_error=8.0, subdivision_level=5, subdivision=True)
                                   for mesh in swollen['meshes']])
    # A light standing in front of the camera, for lights seen by the camera.
    camera = lit['camera']['matrix']
    ahead = [camera[12] - 3 * camera[8], camera[13] - 3 * camera[9], camera[14] - 3 * camera[10]]
    shown = dict(lit, lights=list(lit['lights']) + [{'identity': 'seen', 'name': 'Seen', 'kind': 'SphereLight', 'color': [1, 1, 1], 'intensity': 4.0,
                                                    'radius': .2, 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0] + ahead + [1]}])
    # A dicing camera of its own: the render camera moved forward, through and past the scene, so that the scene is
    # behind it. MoonRay tessellates what its dicing camera does not see coarsely, which the picture then shows.
    far = dict(lit['camera'], matrix=list(camera[:12]) + [camera[12] - 100 * camera[8], camera[13] - 100 * camera[9], camera[14] - 100 * camera[10], 1])
    checks = [
        ('shadows off', lit, with_settings(lit, enable_shadowing=0)),
        ('subsurface off', skin, with_settings(skin, enable_subsurface_scattering=0)),
        ('displacement off', swollen, with_settings(swollen, enable_displacement=0)),
        ('lights seen by the camera', shown, with_settings(shown, lights_visible_in_camera=1)),
        ('geometry resolution limited to 1', swollen, with_settings(swollen, enable_max_geometry_resolution=1, max_geometry_resolution=1)),
        ('dicing camera facing away', adaptive, dict(adaptive, dicing_camera=far)),
    ]
    for label, before, after in checks:
        a, said_a = render(before, runtime, folder, label.replace(' ', '_') + '_before')
        b, said_b = render(after, runtime, folder, label.replace(' ', '_') + '_after')
        moved, ratio = changed(a, b)
        print('%-34s %5.1f%% of the picture changed, brightness %.3f of before%s'
              % (label, 100 * moved, ratio, ('  MoonRay said: ' + said_b[0][-120:]) if said_b else ''))


if __name__ == '__main__':
    main()
