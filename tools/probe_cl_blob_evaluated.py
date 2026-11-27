# python
"""Command line: a Blob and a Sprite in a scene read as Modo's evaluated geometry (its render cache: replicators, Scene
Proxies, Alembic and item masks make the kit read it so). A cube wearing 'Cube' (grey), a Blob over 8 points wearing
'BlobRed' (a red material in a mask of its own, on no polygon), a Sprite beside them; read directly and evaluated
(host.snapshot(evaluated_geometry=True)). report.json: for each reading the render cache's surfaces (source item,
material tag), the meshes (name, material, particle kind), the extra geometry, the materials' diffuse colours and the
notices. MOONRAY_PROBE_OUT is the folder; the scene is saved there as blob_evaluated.lxo."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or 'test-results/blob-evaluated')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def cloud(scene, name, points):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        for p in points:
            geo.vertices.new(p)
    return mesh


def reading(snapshot):
    held = {}
    data = snapshot.get('_evaluated_data') or {}
    held['surfaces'] = [{'source_item': s.get('source_item'), 'material': s.get('material'), 'source_material': s.get('source_material')}
                        for s in data.get('surfaces', [])]
    held['meshes'] = [{'name': m.get('name'), 'identity': m.get('identity'), 'material': m.get('material'), 'particles': m.get('_particles'),
                       'faces': len(m.get('faces') or [])} for m in snapshot.get('meshes', [])]
    held['extra'] = [{'name': e.get('name'), 'kind': e.get('kind'), 'material': e.get('material')} for e in snapshot.get('extra_geometry', [])]
    held['materials'] = {tag: {'color': m.get('color') or m.get('diffuse_color'), 'keys': sorted(m)[:40]} for tag, m in snapshot.get('materials', {}).items()}
    held['warnings'] = snapshot.get('warnings')
    return held


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Cube')
    lx.eval('select.item {%s} set' % cube.id)
    with cube.geometry as geo:
        v = [geo.vertices.new((x * 0.5 - 2.0, y * 0.5 + 0.5, z * 0.5)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([v[i] for i in face])
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial Cube {0.5 0.5 0.5} 0.8 0.04 true false')
    # A material for BlobRed: made on a second mesh's polygons, the mesh then deleted (its mask and material stay).
    temp = scene.addMesh('Temp')
    with temp.geometry as geo:
        a = [geo.vertices.new(p) for p in ((5, 0, 0), (6, 0, 0), (6, 1, 0))]
        geo.polygons.new(a)
    lx.eval('select.item {%s} set' % temp.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial BlobRed {0.9 0.05 0.05} 0.8 0.04 true false')
    lx.eval('select.type item')
    scene.removeItems(temp)
    points = cloud(scene, 'Blob points', [(x * 0.3, 0.6 + y * 0.3, z * 0.3) for x in (0, 1) for y in (0, 1) for z in (0, 1)])
    blob = scene.addItem('blob', name='Blob')
    lx.eval('select.item {%s} set' % blob.id)
    lx.eval('volume.particle {%s}' % points.id)
    blob.channel('radius').set(0.4)
    blob.channel('material').set('BlobRed')
    puffs = cloud(scene, 'Sprite points', [(2.0, 0.8, 0.0)])
    sprite = scene.addItem('sprite', name='Sprite')
    lx.eval('select.item {%s} set' % sprite.id)
    lx.eval('volume.particle {%s}' % puffs.id)
    sprite.channel('radius').set(0.5)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'blob_evaluated.lxo'))
    report['masks'] = [(m.name, m.channel('ptag').get()) for m in scene.items('mask')]
    save()
    from moonray_modo import host
    report['direct'] = reading(host.snapshot())
    save()
    report['evaluated'] = reading(host.snapshot(evaluated_geometry=True))
    save()
    if os.environ.get('MOONRAY_PROBE_RENDER'):
        scene.renderItem.channel('resX').set(640)
        scene.renderItem.channel('resY').set(360)
        lx.eval('!render.animation {%s} openexr' % (out / 'modo'))
except Exception:
    report['error'] = traceback.format_exc()
save()
