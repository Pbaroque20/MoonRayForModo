# python
"""Command-line test for README pictures: an Alembic fluid (MOONRAY_PROBE_SCENE, the tester's Mesher.abc) read by the kit at a few
frames (MOONRAY_PROBE_FRAMES, e.g. 90,120,150,180) with motion blur, as a render reads it, under one camera that sees the
fluid at all of them, its material a glossy blue and the backdrop darkened so the splash shows. Each frame's scene is
written as MoonRay is given it (test-results/cl-export/alembic-frame-<n>.rdla) for a renderer outside Modo, at
MOONRAY_PROBE_SIZE (width,height). Writes test-results/cl-export/alembic-frames.json."""
import json
import math
import os
import pathlib
import time
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
source = os.environ['MOONRAY_PROBE_SCENE']
frames = [int(f) for f in os.environ.get('MOONRAY_PROBE_FRAMES', '90,120,150,180').split(',')]
width, height = [int(v) for v in os.environ.get('MOONRAY_PROBE_SIZE', '420,560').split(',')]
result = {'file': source, 'frames': frames}


def save():
    (out / 'alembic-frames.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')


try:
    import modo
    from moonray_modo import animation, properties, rdla
    scene = modo.Scene()
    owner = scene.addItem('locator', name='Fluid')
    settings = properties.scene_settings()
    settings.setdefault('production', {}).setdefault('objects', {})[owner.id] = {'geometry_file': source, 'material': ''}
    properties.write(scene.renderItem, settings)
    # The look: the base material glossy blue water, the backdrop a darker gradient.
    for material in scene.items('advancedMaterial'):
        for name, value in (('diffCol', (0.05, 0.22, 0.45)), ('diffAmt', 0.8), ('specAmt', 0.6), ('rough', 0.15), ('reflAmt', 0.15)):
            try:
                if isinstance(value, tuple):
                    for k, part in enumerate('RGB'):
                        material.channel(name + '.' + part).set(value[k])
                else:
                    material.channel(name).set(value)
            except Exception as problem:
                result.setdefault('look_skipped', []).append('%s: %s' % (name, problem))
    for environment in scene.items('envMaterial'):
        for name, value in (('zenColor', (0.10, 0.11, 0.13)), ('skyColor', (0.22, 0.23, 0.26)), ('gndColor', (0.08, 0.08, 0.09)), ('nadColor', (0.04, 0.04, 0.05))):
            try:
                for k, part in enumerate('RGB'):
                    environment.channel(name + '.' + part).set(value[k])
            except Exception as problem:
                result.setdefault('look_skipped', []).append('%s: %s' % (name, problem))
    fps = float(scene.fps)
    held_frames = {}
    for frame in frames:
        began = time.perf_counter()
        held = animation.capture_frame(frame / fps, evaluated=False, motion=True, fps=fps)
        fluid = [m for m in held.get('meshes', []) if m.get('_alembic')]
        result['frame %d' % frame] = {'seconds': round(time.perf_counter() - began, 2), 'points': sum(len(m['vertices']) for m in fluid),
                                      'largest_move': round(max((math.dist(p, q) for m in fluid for p, q in zip(m['vertices'], m['vertices_close'])), default=0), 4)}
        held_frames[frame] = held
        save()
    # One camera for every frame: down -Z at the middle of all of them, the whole of each in view.
    points = [p for held in held_frames.values() for m in held.get('meshes', []) if m.get('_alembic') for p in m['vertices']]
    # Where most of it is: a few stray drops fall a hundred units, and framed whole the splash would be a speck.
    ordered = [sorted(p[k] for p in points) for k in range(3)]
    keep = float(os.environ.get('MOONRAY_PROBE_KEEP', '0.02'))
    low = [axis[int(len(axis) * keep)] for axis in ordered]
    high = [axis[int(len(axis) * (1 - keep))] for axis in ordered]
    centre = [(a + b) / 2 for a, b in zip(low, high)]
    result['bounds'] = [low, high]
    for frame, held in held_frames.items():
        camera = dict(held['camera'])
        focal = float(camera.get('focal_mm', 35.0)) or 35.0
        aperture = 36.0 * min(1.0, width / height)
        size = max((high[0] - low[0]) * height / width, high[1] - low[1])
        distance = size * focal / aperture * 1.08 + (high[2] - low[2]) / 2
        matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, centre[0], centre[1], centre[2] + distance, 1]
        camera.update(matrix=matrix, matrix_close=matrix, focal_mm=focal, focal_mm_close=focal)
        held['camera'] = camera
        text = rdla.scene_text(held, width, height, 64, 0.25, 'OUTPUT')
        (out / ('alembic-frame-%d.rdla' % frame)).write_text(text, encoding='utf-8')
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.out('alembic frames probe written')
