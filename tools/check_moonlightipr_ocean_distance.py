"""MoonLightIPR's displaced meshes split by their distance from the camera (moonlightipr_scene.distance_split, the
session's splitByDistance) against split evenly, as before: an 800 m sea of 100 x 100 quads with the Ocean node's
cascades, seen from 3 m up looking out to sea, within the same 400,000 triangles. The reference is the same sea split by
distance within 4,000,000. The distance split must come closer to it. Writes test-results/moonlightipr-ocean-distance/
<case>.pfm/.ppm and report.json.

Needs a MoonRay runtime for its oiiotool (MOONRAY_RUNTIME, else the installed kit's)."""
import json
import os
import pathlib
import struct
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
os.environ['MOONRAY_MODO_OCEAN'] = '1'
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import moonlightipr_scene, nodes, ocean  # noqa: E402

W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-ocean-distance'
folder.mkdir(parents=True, exist_ok=True)
SIZE, SEGMENTS = 800.0, 100
RUNTIME = os.environ.get('MOONRAY_RUNTIME') or str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')


def plane():
    vertices, faces = [], []
    for j in range(SEGMENTS + 1):
        for i in range(SEGMENTS + 1):
            vertices.append([-SIZE / 2 + SIZE * i / SEGMENTS, 0.0, SIZE / 2 - SIZE * j / SEGMENTS])
    for j in range(SEGMENTS):
        for i in range(SEGMENTS):
            a = j * (SEGMENTS + 1) + i
            faces.append([a, a + 1, a + SEGMENTS + 2, a + SEGMENTS + 1])
    uv = [[v[0] / 80.0, v[2] / 80.0] for v in vertices]    # one 80 m tile a unit
    return vertices, faces, [uv[k] for face in faces for k in face]


def scene():
    graph = nodes.new('DwaBaseMaterial', {'albedo': [0.01, 0.03, 0.04], 'roughness': 0.05, 'refractive_index': 1.33})
    graph['nodes']['sea'] = {'type': 'ocean', 'position': [0, 0], 'inputs': {},
                             'parameters': {'resolution': 256, 'wind_speed': 9.0, 'wind_direction': 30.0, 'choppiness': 1.0,
                                            'fit_to_mesh': False, 'repeat': [1.0, 1.0]}}
    graph['displacement'] = 'sea'
    vertices, faces, uvs = plane()
    return {
        'camera': {'matrix': fixture.look_at([0, 3, 0], [0, 0, -60]), 'focal_mm': 35.0, 'film_mm': 36.0},
        'materials': {'': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {'albedo': [0.01, 0.03, 0.04], 'roughness': 0.05},
                           'node_graph': graph, 'node_override': True, 'shader': 'DwaBaseMaterial', 'color': [.01, .03, .04]}},
        'meshes': [{'name': 'Sea', 'identity': 'sea', 'vertices': vertices, 'faces': faces, 'material': '', 'uvs': uvs}],
        'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, .9, .75], 'intensity': 4.0, 'angle': 1.0,
                    'matrix': fixture.look_at([0, 0, 0], [0, -.2, -1])}],
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
            for name, budget, by_distance in (('reference', 4000000, True), ('distance', 400000, True), ('even', 400000, False)):
                patches = [mock.patch.object(moonlightipr_scene, 'DISPLACED_TRIANGLES', budget)]
                if not by_distance:
                    patches.append(mock.patch.object(moonlightipr_scene, 'distance_split', return_value=None))
                for held in patches:
                    held.start()
                try:
                    result = session.submit(scene())
                finally:
                    for held in patches:
                        held.stop()
                fixture.write_images(folder / name, result['pixels'])
                images[name] = values(result['pixels'])
                report[name] = {'warnings': result['warnings'], 'seconds': round(result['done_ms'] / 1000, 2)}
                print(name, report[name], flush=True)
    finally:
        session.process.kill()
    reference = images['reference']

    def error(name):
        return sum(abs(a - b) for a, b in zip(images[name], reference)) / len(reference)
    report['error_distance'] = error('distance')
    report['error_even'] = error('even')
    (folder / 'report.json').write_text(json.dumps(report, indent=1))
    print('mean difference from the reference: split by distance %.4f, evenly %.4f' % (report['error_distance'], report['error_even']))
    if not report['error_distance'] < report['error_even']:
        print('MoonLightIPR distance split check FAILED: splitting by distance does not come closer to the reference')
        return 1
    print('MoonLightIPR distance split check passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
