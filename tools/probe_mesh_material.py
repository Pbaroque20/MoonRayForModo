# python
"""Isolated GUI test: a whole mesh given a MoonRay material, then given more polygons, keeps the material on them.

A mesh is made with one quad and given a MoonRay material whole (materials.assign). A second quad is added to it,
tagged as Modo tags new polygons. The scene is read as for a render, and which material each of the mesh's faces
renders with is written down."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/mesh-material'
out.mkdir(parents=True, exist_ok=True)
result = {}


def quad(mesh, x):
    with mesh.geometry as geometry:
        points = [geometry.vertices.new((x + a, b, 0.0)) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]
        geometry.polygons.new(points)


try:
    from moonray_modo import host, materials
    scene = modo.Scene()
    mesh = scene.addMesh('Box')
    quad(mesh, 0.0)
    scene.select(mesh)
    material = materials.assign()
    mask = material.parent
    result['mask'] = {'ptyp': mask.channel('ptyp').get(), 'ptag': mask.channel('ptag').get(),
                      'linked': [i.name for i in mask.itemGraph('shadeLoc').forward()]}
    quad(mesh, 2.0)
    result['tags'] = [mesh.geometry.polygons[i].materialTag for i in range(len(mesh.geometry.polygons))]
    snapshot = host.snapshot()
    result['snapshot_meshes'] = [{k: m.get(k) for k in ('name', 'identity', 'source_item', 'material', 'face_materials')} for m in snapshot['meshes']]
    result['snapshot_materials'] = {tag: {k: v for k, v in held.items() if k in ('native_shader', 'shader')} if isinstance(held, dict) else str(held)
                                    for tag, held in snapshot['materials'].items()}
    entries = [m for m in snapshot['meshes'] if m.get('source_item') == mesh.id or m.get('identity', '').split('|')[0] == mesh.id or m.get('name') == 'Box']
    def shader_of(tag):
        held = snapshot['materials'].get(tag, {})
        return held.get('native_shader') or (held.get('material_stack') or [{}])[-1].get('native_shader')
    result['faces'] = []
    for entry in entries:
        tags = entry.get('face_materials') or [entry.get('material')] * len(entry['faces'])
        result['faces'] += [shader_of(tag) for tag in tags]
    result['every_face_moonray'] = bool(result['faces']) and all(face == 'DwaBaseMaterial' for face in result['faces'])
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
