# python
"""Isolated GUI test: Mesher.abc (MOONRAY_PROBE_SCENE) imported streamed, as File > Import does, then read as a render with
motion blur reads it (animation.capture_frame) at a few frames: the kit should render the file's own mesh in place of
Modo's stretched one, blurred along the file's velocities, under Modo's mesh's material. Writes
test-results/cl-export/abc-import-blur.json."""
import json
import math
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
result = {'scene': str(source)}


def save():
    (out / 'abc-import-blur.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')


def run():
    try:
        lx.eval('!loaderOptions.Alembic asStatic:false makeInstances:false allFrames:true loadFrame:0 polyMeshStreamingOptions:%s '
                'subdLevel:2 loadMorphs:false useXfrmName:false geometryScale:1.0' % os.environ.get('MOONRAY_PROBE_STREAMING', 'StreamingItems'))
        lx.eval('!!scene.open {%s} import' % source)
        scene = modo.Scene()
        fps = float(scene.fps)
        from moonray_modo import animation
        for frame in (40, 120, 180):
            began = time.perf_counter()
            held = animation.capture_frame(frame / fps, evaluated=True, motion=True, fps=fps)
            meshes = held.get('meshes', [])
            result['frame %d' % frame] = {
                'seconds': round(time.perf_counter() - began, 2),
                'meshes': [{'identity': m['identity'], 'alembic': bool(m.get('_alembic')), 'vertices': len(m['vertices']), 'faces': len(m['faces']),
                            'material': m.get('material'), 'evaluated_geometry': m.get('evaluated_geometry'),
                            'largest_move': round(max(math.dist(p, q) for p, q in zip(m['vertices'], m['vertices_close'])), 4) if m.get('vertices_close') else None}
                           for m in meshes],
                'warnings': [w for w in held.get('warnings', []) if 'shutter' in w or 'velocit' in w or 'lembic' in w]}
            save()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(5000, run)
