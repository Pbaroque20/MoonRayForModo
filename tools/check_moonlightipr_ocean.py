"""MoonLightIPR's ocean: one 40 m Ocean tile on a plane, seen from above at an angle under a low sun, rendered three
ways: the plane finely split (0.1 m between vertices, as MoonRay dices it: the reference), coarsely (2 m, as an artist's
plane often is) with the tile's slope in the shading, and coarsely without it. The coarse plane with the slope must come
much closer to the reference than without it. Writes test-results/moonlightipr-ocean/<case>.pfm/.ppm and report.json.

Needs a MoonRay runtime for its oiiotool (MOONRAY_RUNTIME, else the installed kit's)."""
import json
import math
import os
import pathlib
import struct
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
os.environ['MOONRAY_MODO_OCEAN'] = '1'
import check_moonlightipr_session as fixture  # noqa: E402
if os.environ.get('MOONLIGHTIPR_BUILD'):
    fixture.BUILD = pathlib.Path(os.environ['MOONLIGHTIPR_BUILD'])  # another session, to compare with
from moonray_modo import moonlightipr_materials, moonlightipr_scene, nodes, ocean  # noqa: E402

W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-ocean'
folder.mkdir(parents=True, exist_ok=True)
SIZE = 40.0
RUNTIME = os.environ.get('MOONRAY_RUNTIME') or str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')


def plane(segments):
    vertices, faces, uvs = [], [], []
    for j in range(segments + 1):
        for i in range(segments + 1):
            vertices.append([-SIZE / 2 + SIZE * i / segments, 0.0, SIZE / 2 - SIZE * j / segments])
    for j in range(segments):
        for i in range(segments):
            a = j * (segments + 1) + i
            faces.append([a, a + 1, a + segments + 2, a + segments + 1])   # its normal up, out of the water
    uv = [[i / segments, j / segments] for j in range(segments + 1) for i in range(segments + 1)]
    return vertices, faces, [uv[k] for face in faces for k in face]


def scene(segments):
    graph = nodes.new('DwaBaseMaterial', {'albedo': [0.01, 0.03, 0.04], 'roughness': 0.05, 'refractive_index': 1.33})
    graph['nodes']['sea'] = {'type': 'ocean', 'position': [0, 0], 'inputs': {},
                             'parameters': {'size': SIZE, 'resolution': 256, 'wind_speed': 9.0, 'wind_direction': 30.0, 'choppiness': 1.0}}
    graph['displacement'] = 'sea'
    vertices, faces, uvs = plane(segments)
    return {
        'camera': {'matrix': fixture.look_at([0, 9, 16], [0, 0, 0]), 'focal_mm': 35.0, 'film_mm': 36.0},
        'materials': {'': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'albedo': [0.01, 0.03, 0.04], 'roughness': 0.05},
                           'node_graph': graph, 'node_override': True, 'shader': 'DwaBaseMaterial', 'color': [.01, .03, .04]}},
        'meshes': [{'name': 'Sea', 'identity': 'sea%d' % segments, 'vertices': vertices, 'faces': faces, 'material': '', 'uvs': uvs}],
        'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, .9, .75], 'intensity': 4.0, 'angle': 1.0,
                    'matrix': fixture.look_at([0, 0, 0], [0, -.35, 1])}],
        'environments': [{'kind': 'grad4', 'name': 'Sky', 'intensity': 1.0, 'zenith': [.25, .4, .8], 'sky': [.7, .8, 1],
                          'ground': [.3, .3, .3], 'nadir': [.1, .1, .1], 'sky_exponent': 4, 'ground_exponent': 4}]}


def values(pixels):
    return struct.unpack('<%df' % (W * H * 3), pixels)


def main():
    for stale in folder.glob('*.mls'):
        stale.unlink()
    session = fixture.Session(folder)
    images, report = {}, {}
    try:
        with mock.patch('moonray_modo.native.default_runtime', return_value=RUNTIME), ocean.writing(2.0, RUNTIME):
            for name, segments, slope in (('fine', 400, True), ('coarse_slope', 20, True), ('coarse_plain', 20, False)):
                # The coarse plane as it is, not split finer for its displacement (a large sea's mesh has no room to be).
                with mock.patch.object(moonlightipr_scene, 'DISPLACED_TRIANGLES', 2 * segments * segments):
                    if not slope:
                        # The slope left out: its layer dropped where the displacement is read.
                        original = moonlightipr_materials.displacement_tree

                        def without(*a, **k):
                            found = original(*a, **k)
                            if found is None:
                                return None
                            return [(s, own, [l for l in ls if l.get('effect') != '_slope']) for s, own, ls in found[0]], found[1]
                        with mock.patch.object(moonlightipr_materials, 'displacement_tree', without):
                            result = session.submit(scene(segments))
                    else:
                        result = session.submit(scene(segments))
                fixture.write_images(folder / name, result['pixels'])
                images[name] = values(result['pixels'])
                report[name] = {'warnings': result['warnings'], 'seconds': round(result['done_ms'] / 1000, 2)}
                print(name, report[name])
    finally:
        session.process.kill()
    fine = images['fine']

    def error(name):
        return sum(abs(a - b) for a, b in zip(images[name], fine)) / len(fine)
    report['error_with_slope'] = error('coarse_slope')
    report['error_without_slope'] = error('coarse_plain')
    (folder / 'report.json').write_text(json.dumps(report, indent=1))
    print('mean difference from the fine plane: with the slope %.4f, without %.4f' % (report['error_with_slope'], report['error_without_slope']))
    if not report['error_with_slope'] < 0.8 * report['error_without_slope']:
        print('MoonLightIPR ocean check FAILED: the slope does not bring the coarse plane closer to the fine one')
        return 1
    print('MoonLightIPR ocean check passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
