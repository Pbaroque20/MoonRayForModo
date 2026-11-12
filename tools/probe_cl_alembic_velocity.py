# python
"""Command-line test: an Alembic fluid mesh (MOONRAY_PROBE_SCENE, e.g. Mesher.abc's xfStormMesh) read by the kit's render
cache at a frame and a moment later: whether its points and faces change (a mesher's do), and whether Modo gives the
render cache its per-vertex velocities (LXiRENDERCACHE_GEOVERT_OVEL, from the Alembic's .velocities). Writes
test-results/cl-export/alembic-velocity.json."""
import json
import math
import os
import pathlib
import time
import traceback
import lx

result = {}
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
try:
    began = time.perf_counter()
    # An Alembic comes in as File > Import does (scene.open's import mode, into the empty scene); a scene file opens.
    tried = []
    for command in ('scene.open {%s} import' % source, '!!scene.open {%s} import' % source, 'scene.open {%s} normal' % source):
        try:
            lx.eval(command)
            result['opened_with'] = command
            break
        except RuntimeError as problem:
            tried.append('%s: %s' % (command, problem))
    result['tried'] = tried
    if 'opened_with' not in result:
        raise RuntimeError('the file did not open: ' + ' | '.join(tried))
    result['open_seconds'] = round(time.perf_counter() - began, 2)
    import modo
    scene = modo.Scene()
    fps = float(scene.fps)
    result['fps'] = fps
    result['items'] = [(item.name, item.type) for item in scene.items() if item.type in ('mesh', 'meshInst', 'locator', 'groupLocator')][:20]
    frame = int(os.environ.get('MOONRAY_PROBE_FRAME', '60'))
    from moonray_modo import evaluated
    readings = {}
    for label, at in (('frame', frame / fps), ('later', (frame + 0.25) / fps)):
        began = time.perf_counter()
        data = evaluated.capture(at)
        seconds = round(time.perf_counter() - began, 2)
        surfaces = []
        for key, prototype in (data.get('prototypes') or {}).items():
            for segment in prototype.get('segments', []):
                vertices = segment.get('vertices') or []
                velocities = segment.get('velocities') or []
                speeds = [math.sqrt(sum(c * c for c in v)) for v in velocities[:200000]]
                surfaces.append({'prototype': str(key)[:80], 'vertices': len(vertices), 'faces': len(segment.get('faces') or []),
                                 'velocities': len(velocities), 'speed_max': round(max(speeds), 4) if speeds else None,
                                 'speed_mean': round(sum(speeds) / len(speeds), 4) if speeds else None,
                                 'first_vertex': vertices[0] if vertices else None, 'first_velocity': velocities[0] if velocities else None})
        readings[label] = {'seconds': seconds, 'surfaces': surfaces}
    result['readings'] = readings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'alembic-velocity.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')
lx.out('alembic velocity probe written')
