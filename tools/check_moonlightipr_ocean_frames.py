"""MoonLightIPR rendering the Ocean Plane frame after frame, as a playblast does (each frame read with full-size textures,
packed while its ocean tiles are made): for frames FIRST to LAST at FPS, how long the packing and the render take, and
whether the sea is drawn (its lower half's spread of brightness; a flat sea has almost none). Writes
test-results/moonlightipr-ocean-frames/<frame>.ppm and report.json.

Environment: OCEAN_FIRST, OCEAN_LAST, OCEAN_FPS (8, 16, 30). Needs a MoonRay runtime for its oiiotool (MOONRAY_RUNTIME,
else the installed kit's)."""
import json
import os
import pathlib
import statistics
import struct
import sys
import time
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
os.environ['MOONRAY_MODO_OCEAN'] = '1'
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import moonlightipr_scene, ocean, ocean_plane  # noqa: E402

W, H = fixture.WIDTH, fixture.HEIGHT
folder = ROOT / 'test-results/moonlightipr-ocean-frames'
folder.mkdir(parents=True, exist_ok=True)
RUNTIME = os.environ.get('MOONRAY_RUNTIME') or str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime')
FIRST, LAST, FPS = int(os.environ.get('OCEAN_FIRST', 8)), int(os.environ.get('OCEAN_LAST', 16)), float(os.environ.get('OCEAN_FPS', 30))
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def scene(frame):
    item = {'class': 'OceanPlaneGeometry', 'name': 'Ocean Plane', 'identity': 'plane', 'parameters': {}, 'matrix': IDENTITY}
    held = {'camera': {'matrix': fixture.look_at([0, 4, 0], [0, 0, -60]), 'focal_mm': 35.0, 'film_mm': 36.0},
            'materials': {}, 'meshes': [], 'entities': [item], 'time': frame / FPS, 'frame': frame, 'fps': FPS,
            '_full_textures': True, '_flat_out': True,
            'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, .9, .75], 'intensity': 4.0, 'angle': 1.0,
                        'matrix': fixture.look_at([0, 0, 0], [0, -.2, -1])}],
            'environments': [{'kind': 'grad4', 'name': 'Sky', 'intensity': 1.0, 'zenith': [.25, .4, .8], 'sky': [.7, .8, 1],
                              'ground': [.3, .3, .3], 'nadir': [.1, .1, .1], 'sky_exponent': 4, 'ground_exponent': 4}]}
    return ocean_plane.apply(held, [])


def main():
    for stale in folder.glob('*.mls'):
        stale.unlink()
    session = fixture.Session(folder)
    report = {}
    try:
        with mock.patch('moonray_modo.native.default_runtime', return_value=RUNTIME):
            for frame in range(FIRST, LAST + 1):
                began = time.perf_counter()
                held = scene(frame)
                read = time.perf_counter() - began
                result = session.submit(held)
                fixture.write_images(folder / ('%03d' % frame), result['pixels'])
                pixels = struct.unpack('<%df' % (W * H * 3), result['pixels'])
                lower = [pixels[3 * (y * W + x) + 1] for y in range(H * 2 // 3, H) for x in range(0, W, 4)]
                report[frame] = {'plane': round(read, 2), 'pack_ms': result.get('pack_ms'), 'done_s': round(result['done_ms'] / 1000, 2),
                                 'sea_spread': round(statistics.pstdev(lower), 4), 'warnings': result['warnings'][:4]}
                print(frame, report[frame], flush=True)
    finally:
        session.process.kill()
    (folder / 'report.json').write_text(json.dumps(report, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
