# python
"""Isolated GUI test: an Alembic fluid mesh (MOONRAY_PROBE_SCENE, e.g. Mesher.abc) imported as File > Import does, then read
by the kit's render cache at a frame and a moment later: whether its points and faces change, and whether Modo gives the
render cache its per-vertex velocities (the Alembic's .velocities). Then the scene as the kit hands it to a render with
motion blur, to see that it no longer refuses. Writes test-results/cl-export/alembic-velocity-gui.json."""
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
frame = int(os.environ.get('MOONRAY_PROBE_FRAME', '60'))
result = {'scene': str(source), 'frame': frame}


def save():
    (out / 'alembic-velocity-gui4.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')


def surfaces(data):
    found = []
    for key, prototype in (data.get('prototypes') or {}).items():
        for segment in prototype.get('segments', []):
            vertices = segment.get('vertices') or []
            velocities = segment.get('velocities') or []
            speeds = [math.sqrt(sum(c * c for c in v)) for v in list(velocities)[:200000]]
            found.append({'prototype': str(key)[:60], 'vertices': len(vertices), 'faces': len(segment.get('faces') or []),
                          'velocities': len(velocities), 'speed_max': round(max(speeds), 4) if speeds else None,
                          'speed_mean': round(sum(speeds) / len(speeds), 4) if speeds else None})
    return found


def run():
    try:
        began = time.perf_counter()
        # Streamed, as a fluid mesh must be (its faces change): Alembic Mesh items (MOONRAY_PROBE_STREAMING, Modo's loader's
        # polyMeshStreamingOptions), every frame.
        option = os.environ.get('MOONRAY_PROBE_STREAMING', 'StreamingItems')
        lx.eval('!loaderOptions.Alembic asStatic:false makeInstances:false allFrames:true loadFrame:0 polyMeshStreamingOptions:%s '
                'subdLevel:2 loadMorphs:false useXfrmName:false geometryScale:1.0' % option)
        result['streaming'] = option
        for command in ('!!scene.open {%s} import' % source, '!!scene.open {%s} normal' % source):
            try:
                lx.eval(command)
                result['opened_with'] = command
                break
            except RuntimeError as problem:
                result.setdefault('tried', []).append('%s: %s' % (command, problem))
        result['open_seconds'] = round(time.perf_counter() - began, 2)
        scene = modo.Scene()
        fps = float(scene.fps)
        result['fps'] = fps
        result['item_types'] = sorted({item.type for item in scene.items()})
        result['items'] = [(item.name, item.type) for item in scene.items() if 'lembic' in item.type or item.type == 'mesh'][:20]
        # The fluid mesh's vertex maps (a .velocities Modo keeps as a map would be one).
        for item in list(scene.items('mesh')) + [i for i in scene.items() if i.type == 'AlembicMesh']:
            if 'storm' in item.name.lower():
                try:
                    result['vertex_maps'] = [(m.name, m.type if hasattr(m, 'type') else '') for m in item.geometry.vmaps]
                except Exception as problem:
                    result['vertex_maps'] = 'not read: %s' % problem
                result['deformers'] = [(d.name, d.type) for d in item.itemGraph('deformers').reverse()] if hasattr(item, 'itemGraph') else []
        # The Alembic file item's channels: its frame range, among them.
        for item in scene.items():
            if item.type == 'AlembicFile':
                held = {}
                for name in item.channelNames:
                    try:
                        value = item.channel(name).get()
                        if isinstance(value, (int, float, str, bool)): held[name] = value
                    except Exception:
                        pass
                result['alembic_file'] = held
        result['scene_range'] = [lx.eval('time.range scene in:?'), lx.eval('time.range scene out:?')] if True else None
        from moonray_modo import evaluated
        spots = [float(v) for v in os.environ.get('MOONRAY_PROBE_FRAMES', '').split(',') if v] or [frame + d for d in (-1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0)]
        for label, at in [('t%.2f' % f, f / fps) for f in spots]:
            began = time.perf_counter()
            data = evaluated.capture(at)
            result[label] = {'seconds': round(time.perf_counter() - began, 2), 'surfaces': surfaces(data)}
        save()
        # The scene as a render with motion blur reads it: the kit's own frame capture, the shutter's ends included.
        lx.eval('select.time %s' % (frame / fps))
        # A shutter a whole frame long, reaching into the samples either side (blur length 1).
        camera = scene.renderCamera
        lx.eval('item.channel blurLen %s item:{%s}' % (float(os.environ.get('MOONRAY_PROBE_BLUR', '1.0')), camera.id))
        result['blur_length'] = camera.channel('blurLen').get()
        from moonray_modo import animation
        began = time.perf_counter()
        try:
            held = animation.capture_frame(frame / fps, evaluated=True, motion=True, fps=fps)
            result['motion_capture'] = 'ok'
            if held is not None:
                meshes = [m for m in held.get('meshes', []) if 'xfStorm' in str(m.get('name', '')) or 'Storm' in str(m.get('identity', ''))]
                result['motion_meshes'] = [{'identity': m.get('identity'), 'vertices': len(m.get('vertices') or []), 'vertices_close': len(m.get('vertices_close') or [])} for m in meshes[:5]]
                result['motion_warnings'] = [w for w in held.get('warnings', []) if 'shutter' in w or 'velocit' in w][:5]
        except Exception as problem:
            result['motion_capture'] = 'refused: %s' % problem
        result['motion_seconds'] = round(time.perf_counter() - began, 2)
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(5000, run)
