# python
"""Isolated GUI test: a mesh whose shape changes over the shutter, held as a morph map and a keyed Morph Influence.

A quad gets a relative morph map moving one point up by 1; a Morph Influence deformer for that map is made and linked
to the mesh, its strength keyed 0 a quarter frame before and 1 a quarter frame after the current time. The deformed
point is read at both times, and the scene captured as for a render with motion blur."""
import json
import pathlib
import traceback
import lx
import lxu.object
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/morph-shutter'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Bent')
    with mesh.geometry as geometry:
        points = [geometry.vertices.new(p) for p in ((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0))]
        geometry.polygons.new(points)
    with mesh.geometry as geometry:
        morph = geometry.vmaps.addMorphMap('RDL shutter close', False)
        morph.setAbsolutePosition(geometry.vertices[2].index, (1, 2, 0)) if hasattr(morph, 'setAbsolutePosition') else None
        morph[geometry.vertices[2].index] = (0.0, 1.0, 0.0)
    result['maps'] = [m.name for m in mesh.geometry.vmaps]
    deformer = scene.addItem('morphDeform', name='RDL shutter close')
    result['deformer_channels'] = [c.name for c in deformer.channels()][:40]
    deformer.channel('mapName').set('RDL shutter close')
    deformer.itemGraph('deformers') >> mesh.itemGraph('deformers')
    now, fps = lx.service.Selection().GetTime(), float(scene.fps)
    strength = deformer.channel('strength')
    strength.set(0.0, time=now - 0.25 / fps, key=True)
    strength.set(1.0, time=now + 0.25 / fps, key=True)

    def deformed_point(time):
        selection = lx.service.Selection()
        held = selection.GetTime()
        selection.SetTime(time)
        try:
            evaluated = modo.meshgeometry.MeshProvider.meshFromMeshChannel(mesh._item, 'deformed')
            points = lx.object.Point(evaluated.PointAccessor())
            points.SelectByIndex(2)
            return [round(v, 4) for v in points.Pos()]
        finally:
            selection.SetTime(held)
    result['point_open'] = deformed_point(now - 0.25 / fps)
    result['point_close'] = deformed_point(now + 0.25 / fps)
    from moonray_modo import animation
    snapshot = animation.capture_current(False)
    bent = next(m for m in snapshot['meshes'] if m['name'] == 'Bent')
    result['captured'] = {'motion_steps': snapshot.get('motion_steps'), 'open': bent['vertices'][2],
                          'close': (bent.get('vertices_close') or [None] * 3)[2]}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
