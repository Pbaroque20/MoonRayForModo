# python
"""Command-line test: an Alembic file's meshes rendered by the kit itself (extra_geometry.alembic_scene_meshes), as a tester's
fluid (MOONRAY_PROBE_SCENE, Mesher.abc) needs: a new scene, a locator whose production Geometry file is the .abc, the
frame (MOONRAY_PROBE_FRAME) read with motion blur as a render reads it, the camera aimed at the fluid, and the scene
written as MoonRay is given it (test-results/cl-export/alembic-scene.rdla) for a renderer outside Modo.
Writes test-results/cl-export/alembic-scene.json."""
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
frame = int(os.environ.get('MOONRAY_PROBE_FRAME', '120'))
result = {'file': source, 'frame': frame}
try:
    import modo
    from moonray_modo import animation, properties, rdla
    scene = modo.Scene()
    owner = scene.addItem('locator', name='Fluid')
    settings = properties.scene_settings()
    settings.setdefault('production', {}).setdefault('objects', {})[owner.id] = {'geometry_file': source, 'material': ''}
    properties.write(scene.renderItem, settings)
    fps = float(scene.fps)
    result['fps'] = fps
    began = time.perf_counter()
    held = animation.capture_frame(frame / fps, evaluated=False, motion=True, fps=fps)
    result['capture_seconds'] = round(time.perf_counter() - began, 2)
    fluid = [m for m in held.get('meshes', []) if m.get('_alembic')]
    result['meshes'] = [{'identity': m['identity'], 'vertices': len(m['vertices']), 'faces': len(m['faces']),
                         'vertices_close': len(m.get('vertices_close') or []),
                         'largest_move': round(max(math.dist(p, q) for p, q in zip(m['vertices'], m['vertices_close'])), 4) if m.get('vertices_close') else None}
                        for m in fluid]
    result['warnings'] = [w for w in held.get('warnings', []) if 'velocit' in w or 'shutter' in w or 'Alembic' in w]
    # The camera aimed at the fluid from the front (down -Z), its whole height in view.
    points = [p for m in fluid for p in m['vertices']]
    low = [min(p[k] for p in points) for k in range(3)]
    high = [max(p[k] for p in points) for k in range(3)]
    centre = [(a + b) / 2 for a, b in zip(low, high)]
    size = max(high[0] - low[0], high[1] - low[1])
    result['bounds'] = [low, high]
    camera = dict(held['camera'])
    focal = float(camera.get('focal_mm', 35.0)) or 35.0
    distance = size * focal / 24.0 * 1.15 + (high[2] - low[2]) / 2
    matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, centre[0], centre[1], centre[2] + distance, 1]
    camera.update(matrix=matrix, matrix_close=matrix, focal_mm=focal, focal_mm_close=focal)
    held['camera'] = camera
    text = rdla.scene_text(held, 480, 360, 16, 0.25, 'OUTPUT')
    (out / 'alembic-scene.rdla').write_text(text, encoding='utf-8')
    result['rdla_bytes'] = len(text)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'alembic-scene.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')
lx.out('alembic scene probe written')
