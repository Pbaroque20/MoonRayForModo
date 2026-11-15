"""The Ocean Crest node in MoonLightIPR: the swell check's sea (a 2.5 m swell 150 m long over the cascades), seen from
3 m up, with its water colour as it is, and turning to the Ocean Plane's Crest Colour by an Ocean Crest mask where the
waves stand highest. The glow must brighten the picture, and no graph be baked. Writes
test-results/moonlightipr-ocean-crest/<case>.pfm/.ppm and report.json.

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
folder = ROOT / 'test-results/moonlightipr-ocean-crest'
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


def scene(crest=False, **swell):
    graph = nodes.new('DwaBaseMaterial', {'albedo': [0.01, 0.03, 0.04], 'roughness': 0.05, 'refractive_index': 1.33})
    graph['nodes']['sea'] = {'type': 'ocean', 'position': [0, 0], 'inputs': {},
                             'parameters': {'resolution': 256, 'wind_speed': 9.0, 'wind_direction': 30.0, 'choppiness': 1.0,
                                            'fit_to_mesh': False, 'repeat': [1.0, 1.0], **swell}}
    graph['displacement'] = 'sea'
    if crest:
        graph['nodes']['crest'] = {'type': 'ocean_crest', 'position': [0, 0], 'inputs': {}, 'parameters': {}}
        graph['nodes']['glow'] = {'type': 'mix', 'position': [0, 0], 'inputs': {'mix': 'crest'},
                                  'parameters': {'bg': [0.01, 0.03, 0.04], 'fg': CREST, 'mix': 0.0}}
        graph['nodes']['surface']['inputs']['albedo'] = 'glow'
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


SWELL = {'swell_height': 2.5, 'swell_length': 150.0, 'swell_direction': 80.0}
CREST = [float(c) for c in os.environ.get('CHECK_CREST', '0.03,0.15,0.12').split(',')]


def main():
    for stale in folder.glob('*.mls'):
        stale.unlink()
    session = fixture.Session(folder)
    images, report = {}, {}
    try:
        for name, crest in (('plain', False), ('crest', True)):
            with mock.patch('moonray_modo.native.default_runtime', return_value=RUNTIME), ocean.writing(2.0, RUNTIME),                     mock.patch('moonray_modo.graph_bake.bake', side_effect=AssertionError('baked')):
                result = session.submit(dict(scene(crest, **SWELL), time=2.0))
            fixture.write_images(folder / name, result['pixels'])
            images[name] = values(result['pixels'])
            report[name] = {'warnings': result['warnings'], 'seconds': round(result['done_ms'] / 1000, 2)}
            print(name, report[name], flush=True)
    finally:
        session.process.kill()
    report['brighter'] = (sum(images['crest']) - sum(images['plain'])) / len(images['plain'])
    (folder / 'report.json').write_text(json.dumps(report, indent=1))
    print('mean brightening by the crests %.4f' % report['brighter'])
    if not report['brighter'] > 1e-3 or any(report[n]['warnings'] for n in ('plain', 'crest')):
        print('MoonLightIPR ocean crest check FAILED')
        return 1
    print('MoonLightIPR ocean crest check passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
