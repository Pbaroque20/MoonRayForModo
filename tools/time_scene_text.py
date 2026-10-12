"""What writing a kept snapshot as MoonRay scene text costs, the second time and after, when only the camera has moved.

Usage: time_scene_text.py [profile]
Reads test-results/snapshot/scene.pickle (tools/probe_dump_snapshot.py). The scene is written once to warm what is
kept between renders, then again with the camera moved a little each time, as a followed drag does; each writing and
each comparison with the text before it is timed."""
import cProfile
import pathlib
import pickle
import pstats
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, ipr
from moonray_modo.scene_delta import difference

held = pickle.load(open(str(ROOT / 'test-results/snapshot/scene.pickle'), 'rb'))
scene, samples, environment = held['scene'], held['samples'], held['environment']
scene, width, height = ipr.prepare(scene, 640, round(640 * scene['height'] / scene['width']), samples, 160, 1, 100.0)


def moved(step):
    camera = dict(scene['camera'])
    matrix = list(camera.get('matrix') or rdla.IDENTITY)
    matrix[12] += 0.002 * step
    camera['matrix'] = matrix
    return dict(scene, camera=camera)


def write(step):
    return rdla.scene_text(moved(step), width, height, 1, environment, None)


started = time.perf_counter()
before = write(0)
print('first writing   %.3f s, %d lines, %.1f MB' % (time.perf_counter() - started, before.count('\n'), len(before) / 1e6))
profile = cProfile.Profile() if sys.argv[1:] == ['profile'] else None
for step in range(1, 5):
    started = time.perf_counter()
    if profile:
        profile.enable()
    text = write(step)
    middle = time.perf_counter()
    delta = difference(before, text)
    if profile:
        profile.disable()
    print('writing %.3f s, comparing %.3f s, %s' % (middle - started, time.perf_counter() - middle,
                                                    'a whole reload' if delta is None else 'a change of %d characters' % len(delta)))
    before = text
if profile:
    pstats.Stats(profile).sort_stats('cumulative').print_stats(28)
