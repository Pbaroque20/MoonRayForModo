"""MoonLightIPR rendering an Ocean Plane read in Modo, still and with motion blur: each reading pickled by
tools/probe_cl_ocean_plane_height.py (still_<height>.pickle, motion_<height>.pickle in FOLDER), or made here without
Modo (--made: the plane at HEIGHT, read still and with the shutter's ends, the camera moving CAMERA_MOVE metres along X
during the shutter), packed as the preview packs it and rendered by the session. For each: whether the sea is drawn (the
spread of brightness in the picture's lower part; a flat sea has almost none), the sea's height and the mesh flags.
Writes <name>.pfm/.ppm and report.json in FOLDER (test-results/ocean-plane-height).

Needs a MoonRay runtime for its oiiotool (MOONRAY_RUNTIME, else the installed kit's)."""
import json
import os
import pathlib
import pickle
import statistics
import struct
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
os.environ['MOONRAY_MODO_OCEAN'] = '1'
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import moonlightipr_scene  # noqa: E402

W, H = fixture.WIDTH, fixture.HEIGHT
FOLDER = pathlib.Path(os.environ.get('FOLDER', str(ROOT / 'test-results/ocean-plane-height')))
RUNTIME = os.environ.get('MOONRAY_RUNTIME') or str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def made(height, move):
    """A reading of an Ocean Plane at height made as host.snapshot makes it (ocean_plane.apply), still, and with the
    shutter's ends read as animation.capture_frame reads them (motion.apply_motion), the camera moving along X."""
    from moonray_modo import motion, ocean_plane

    def read(x):
        item = {'class': 'OceanPlaneGeometry', 'name': 'Ocean Plane', 'identity': 'plane', 'parameters': {},
                'matrix': IDENTITY[:13] + [height, 0, 1]}
        held = {'camera': {'matrix': fixture.look_at([x, height + 4, 0], [x, height, -60]), 'focal_mm': 35.0, 'film_mm': 36.0,
                           'identity': 'camera'},
                'materials': {}, 'meshes': [], 'entities': [item], 'time': 0.5, 'frame': 12, 'fps': 24.0,
                'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, .9, .75], 'intensity': 4.0,
                            'angle': 1.0, 'matrix': fixture.look_at([0, 0, 0], [0, -.2, -1])}],
                'environments': [{'kind': 'grad4', 'name': 'Sky', 'intensity': 1.0, 'zenith': [.25, .4, .8], 'sky': [.7, .8, 1],
                                  'ground': [.3, .3, .3], 'nadir': [.1, .1, .1], 'sky_exponent': 4, 'ground_exponent': 4}]}
        return ocean_plane.apply(held, [])
    still = read(0.0)
    blurred = read(0.0)
    motion.apply_motion(blurred, read(-move / 2), read(move / 2), [-0.25, 0.25], preview=True)
    return {'still_made_%s' % height: still, 'motion_made_%s' % height: blurred}


def main():
    readings = {}
    if '--made' in sys.argv:
        readings.update(made(float(os.environ.get('HEIGHT', 2.5)), float(os.environ.get('CAMERA_MOVE', 0.0))))
    else:
        for path in sorted(FOLDER.glob('*.pickle')):
            readings[path.stem] = pickle.loads(path.read_bytes())
    for stale in FOLDER.glob('*.mls'):
        stale.unlink()
    session = fixture.Session(FOLDER)
    report = {}
    try:
        with mock.patch('moonray_modo.native.default_runtime', return_value=RUNTIME):
            for name, held in readings.items():
                held = dict(held, _full_textures=True, _flat_out=True)
                held['camera'] = dict(held['camera'], focal_mm=35.0, film_mm=36.0)
                result = session.submit(held)
                fixture.write_images(FOLDER / name, result['pixels'])
                pixels = struct.unpack('<%df' % (W * H * 3), result['pixels'])
                lower = [pixels[3 * (y * W + x) + 1] for y in range(0, H // 3) for x in range(0, W, 4)]
                seas = [m for m in held.get('meshes') or [] if m.get('_ocean_plane')]
                report[name] = {'sea_spread': round(statistics.pstdev(lower), 5), 'sea_mean': round(statistics.mean(lower), 5),
                                'seas': [[round(m['vertices'][0][1] + (m.get('matrix') or IDENTITY)[13], 3), bool(m.get('vertices_close'))]
                                         for m in seas],
                                'motion': bool(held.get('motion_steps')), 'warnings': result['warnings'][:4]}
                print(name, report[name], flush=True)
    finally:
        session.process.kill()
    (FOLDER / ('made_report.json' if '--made' in sys.argv else 'render_report.json')).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
