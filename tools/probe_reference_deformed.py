# python
"""Isolated GUI test: rest positions (ref_P) of a deformed mesh are its points before the deformer.

A sphere is given a morph map that lifts every point by 0.5 and a morph influence at full strength, so that Modo
renders it lifted; its material shows glitter in reference space. Noted, for the mesh as the plugin sends it: how it
was read (whole, or in pieces from the render cache), how far its points are lifted, and how far its ref_P is: 0.5
and 0 where the rest positions are the base mesh's."""
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
LIFT = 0.5
try:
    from moonray_modo import host, properties
    lx.eval('item.create mesh')
    mesh_item = modo.Scene().selected[-1]
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    mesh_item = max(modo.Scene().items('mesh', superType=False),
                    key=lambda item: modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed').PointCount())
    base = [list(v.position) for v in mesh_item.geometry.vertices]
    with mesh_item.geometry as geometry:
        morph = geometry.vmaps.addMorphMap('lift', False)
        for vertex in geometry.vertices:
            morph[vertex.index] = (0.0, LIFT, 0.0)
    lx.eval('select.item {%s} set' % mesh_item.id)
    lx.eval('select.vertexMap lift morf replace')
    lx.eval('morphDeform.create')
    result['influences'] = [i.type for i in modo.Scene().items() if 'morph' in i.type.lower()]
    deformed = modo.meshgeometry.MeshProvider.meshFromMeshChannel(mesh_item._item, 'deformed')
    points = lx.object.Point(deformed.PointAccessor())
    points.SelectByIndex(0)
    result['first_point'] = {'base': base[0], 'deformed': list(points.Pos())}
    lx.eval('select.item {%s} set' % mesh_item.id)
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial',
                                                             'parameters': {'show_glitter': True, 'glitter': 1.0, 'glitter_space': 5}}))
    snapshot = host.snapshot()
    pieces = [m for m in snapshot['meshes'] if m['name'] in (mesh_item.name, mesh_item.id) or str(m.get('identity', '')).startswith(mesh_item.id)]
    result['read'] = 'pieces from the render cache' if any(m.get('evaluated_geometry') for m in pieces) else 'whole'
    result['pieces'] = len(pieces)
    lifts, rests = [], []
    for mesh in pieces:
        rest = (mesh.get('point_attributes') or {}).get('ref_P')
        if not rest:
            continue
        for point, rested in zip(mesh['vertices'], rest['values']):
            lifts.append(point[1] - rested[1])
    if lifts:
        result['points_above_ref_P'] = {'least': min(lifts), 'most': max(lifts)}
    result['with_ref_P'] = sum(1 for m in pieces if (m.get('point_attributes') or {}).get('ref_P'))
    result['warnings'] = [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:6]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'reference_deformed.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
