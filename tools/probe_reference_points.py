# python
"""Isolated GUI test: a Modo mesh with glitter in reference space carries its rest positions (ref_P) to MoonRay.

A sphere is given DwaBaseMaterial with glitter shown in reference space. Noted: whether the scene asks for rest
positions, the mesh's point count and its ref_P's, whether they are its points (no deformer here), and the warnings.
The scene is written as test-results/glitter/reference_points.rdla for MoonRay to render (tools/check_glitter.py's
render_scene step, or moonray.exe on it)."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/glitter'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import host, properties, rdla, reference_points
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial',
                                                             'parameters': {'show_glitter': True, 'glitter': 1.0, 'glitter_space': 5}}))
    snapshot = host.snapshot()
    result['wanted'] = reference_points.wanted(snapshot['materials'])
    meshes = []
    for mesh in snapshot['meshes']:
        rest = (mesh.get('point_attributes') or {}).get('ref_P')
        meshes.append({'name': mesh['name'], 'points': len(mesh['vertices']), 'ref_P': len(rest['values']) if rest else None,
                       'same': bool(rest) and all(abs(a - b) < 1e-6 for p, q in zip(mesh['vertices'], rest['values']) for a, b in zip(p, q))})
    result['pieces'] = len(meshes)
    result['pieces_with_ref_P'] = sum(1 for m in meshes if m['ref_P'] is not None)
    result['pieces_ref_P_their_points'] = sum(1 for m in meshes if m['same'])
    # The base mesh's points read directly, against the points Modo renders it with (no deformer: the same).
    # The sphere: the mesh with points (the test also makes an empty one first).
    sphere = max(modo.Scene().items('mesh', superType=False),
                 key=lambda item: modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed').PointCount())
    deformed = modo.meshgeometry.MeshProvider.meshFromMeshChannel(sphere._item, 'deformed')
    rest = reference_points.read(sphere, deformed.PointCount())
    points = lx.object.Point(deformed.PointAccessor())
    shown = []
    for index in range(deformed.PointCount()):
        points.SelectByIndex(index)
        shown.append(list(points.Pos()))
    result['base_read'] = {'points': len(shown), 'rest': None if rest is None else len(rest),
                           'same': rest is not None and all(abs(a - b) < 1e-6 for p, q in zip(shown, rest) for a, b in zip(p, q))}
    result['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:6]
    (out / 'reference_points.rdla').write_text(rdla.scene_text(snapshot, 320, 180, 4, 0.15, str(out / 'reference_points.exr')), encoding='utf-8')
except Exception:
    result['error'] = traceback.format_exc()
(out / 'reference_points.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
