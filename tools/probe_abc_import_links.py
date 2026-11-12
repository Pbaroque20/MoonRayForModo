# python
"""Isolated GUI test: Mesher.abc (MOONRAY_PROBE_SCENE) imported streamed, as File > Import does, to learn how Modo ties the
mesh it makes to its Alembic File item (graphs, parents, deformers), where each stands, and how the mesh Modo hands the
render cache compares with the file's own at the same time (points, faces, bounds, order): what the kit needs to read
velocities from the file for a mesh imported this way. Writes test-results/cl-export/abc-import-links.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import lxu.select
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
runtime = os.environ.get('MOONRAY_PROBE_RUNTIME')
result = {'scene': str(source)}


def save():
    (out / 'abc-import-links.json').write_text(json.dumps(result, indent=1, default=repr), encoding='utf-8')


def graphs(item):
    """Every graph the item is linked through, forward and back."""
    held = {}
    for name in ('deformers', 'parent', 'shadeLoc', 'chanLinks', 'meshInst', 'source', 'abcLink', 'AlembicFile', 'deformTree',
                 'groups', 'itemGroups', 'xfrmCore', 'local'):
        try:
            graph = item.itemGraph(name)
            forward = [(i.name, i.type, i.id) for i in graph.forward()]
            back = [(i.name, i.type, i.id) for i in graph.reverse()]
            if forward or back:
                held[name] = {'forward': forward, 'reverse': back}
        except Exception:
            pass
    return held


def bounds(points):
    return [[min(p[k] for p in points) for k in range(3)], [max(p[k] for p in points) for k in range(3)]] if points else None


def run():
    try:
        option = os.environ.get('MOONRAY_PROBE_STREAMING', 'StreamingItems')
        lx.eval('!loaderOptions.Alembic asStatic:false makeInstances:false allFrames:true loadFrame:0 polyMeshStreamingOptions:%s '
                'subdLevel:2 loadMorphs:false useXfrmName:false geometryScale:1.0' % option)
        lx.eval('!!scene.open {%s} import' % source)
        scene = modo.Scene()
        fps = float(scene.fps)
        result['fps'] = fps
        from moonray_modo.host import world_matrix
        interesting = [i for i in scene.items() if i.type in ('mesh', 'AlembicFile', 'ABCStreamingDeformer') or 'lembic' in i.type or 'ABC' in i.type]
        result['items'] = []
        for item in interesting:
            entry = {'name': item.name, 'type': item.type, 'id': item.id,
                     'parent': (item.parent.name, item.parent.type) if item.parent else None, 'graphs': graphs(item)}
            try:
                entry['matrix'] = world_matrix(item)
            except Exception as problem:
                entry['matrix'] = 'none: %s' % problem
            try:
                entry['channels'] = {n: item.channel(n).get() for n in item.channelNames
                                     if isinstance(item.channel(n).get(), (int, float, str, bool))}
            except Exception as problem:
                entry['channels'] = 'not read: %s' % problem
            result['items'].append(entry)
        save()
        from moonray_modo import animation, extra_geometry
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        for frame in (80, 120, 180):
            held = animation.capture_frame(frame / fps, evaluated=True, motion=False, fps=fps)
            meshes = [m for m in held.get('meshes', []) if not m.get('_alembic')]
            spot = {'meshes': [{'identity': m['identity'], 'name': m.get('name'), 'vertices': len(m['vertices']), 'faces': len(m['faces']),
                                'material': m.get('material'), 'matrix': m.get('matrix'), 'bounds': bounds(m['vertices']),
                                'first_points': m['vertices'][:3], 'velocities': len(m.get('velocities') or [])} for m in meshes]}
            try:
                read = extra_geometry.alembic_meshes(source, frame / fps, runtime)
                spot['file'] = [{'name': r['name'], 'vertices': len(r['vertices']), 'faces': len(r['faces']), 'matrix': r['matrix'],
                                 'sample': r['sample'], 'bounds': bounds(r['vertices']), 'first_points': r['vertices'][:3]} for r in read]
                # Whether Modo's points are the file's, in its order.
                for m in meshes:
                    for r in read:
                        if len(m['vertices']) == len(r['vertices']):
                            spot.setdefault('same_order', {})[m['identity']] = max(abs(a[k] - b[k]) for a, b in zip(m['vertices'][::997], r['vertices'][::997]) for k in range(3))
            except Exception as problem:
                spot['file'] = 'not read: %s' % problem
            result['frame %d' % frame] = spot
            save()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(5000, run)
