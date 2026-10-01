# python
"""Verify the C++ geometry bridge on controlled Modo fixtures."""
import ctypes
import json
from pathlib import Path
import traceback
import lx
import modo
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder=root/'test-results/render-cache';folder.mkdir(parents=True,exist_ok=True)
report={'passed':False,'app_version':lx.eval('query platformservice appversion ?')}
try:
    path=root/'build/modo-geometry/MoonRayPreview.lx'
    lx.eval('plugin.add {%s}' % path)
    bridge=ctypes.CDLL(str(path))
    bridge.MR_geometry_snapshot.argtypes=[ctypes.c_double,ctypes.c_int]
    bridge.MR_geometry_snapshot.restype=ctypes.c_char_p
    scene=modo.Scene()
    mesh=scene.addMesh('Render cache triangle')
    geometry=mesh.geometry
    for v in ((-1,-1,0),(1,-1,0),(0,1,0)):geometry.vertices.new(v)
    geometry.polygons.new((0,1,2));geometry.setMeshEdits()
    mesh.position.set((2,3,-4))
    mesh.scale.set((2,3,4))
    data=json.loads(bridge.MR_geometry_snapshot(0,0).decode('utf-8'))
    (folder/'triangle.json').write_text(json.dumps(data,indent=2))
    assert 'error' not in data,data
    surfaces=[s for s in data['surfaces'] if s['source_item']==mesh.id]
    assert surfaces,'Missing controlled mesh surface'
    surface=surfaces[0]
    report['transform']=surface['matrix']
    assert surface['matrix'][12:15]==[2,3,-4],surface['matrix']
    from moonray_modo.host import world_matrix
    assert all(abs(a-b)<1e-6 for a,b in zip(surface['matrix'],world_matrix(mesh))),surface['matrix']
    prototype=data['prototypes'][str(surface['source_id'])]
    assert sum(len(s['faces']) for s in prototype['segments'])==1,prototype
    assert len(prototype['segments'][0]['normals'])==3
    report['triangle']=True
    report['features']=prototype['features']
    # A forced fresh evaluation must observe subsequent geometry edits.
    mesh.position.set((4,3,-4))
    updated=json.loads(bridge.MR_geometry_snapshot(0,0).decode('utf-8'))
    assert any(s['source_item']==mesh.id and s['matrix'][12]==4 for s in updated['surfaces'])
    report['reevaluation']=True
    mesh.rotation.set((.2,.4,.3))
    rotated=json.loads(bridge.MR_geometry_snapshot(0,0).decode('utf-8'))
    transform=next(s['matrix'] for s in rotated['surfaces'] if s['source_item']==mesh.id)
    assert all(abs(a-b)<1e-5 for a,b in zip(transform,world_matrix(mesh))),transform
    report['rotation_and_nonuniform_scale']=True
    from moonray_modo import evaluated, host, rdla
    evaluated._bridge=bridge
    exported=host.snapshot(evaluated_geometry=True)
    assert len(exported['meshes'])==1
    assert exported['meshes'][0]['matrix']==transform
    rdla.scene_text(exported)
    report['exporter']=True
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('item.duplicate instance:true')
    instance=scene.selected[0]
    modo.LocatorSuperType(instance).position.set((8,0,0))
    (folder/'instances-raw.json').write_text(json.dumps(evaluated.capture(0),indent=2))
    (folder/'instances-undisplaced.json').write_text(json.dumps(evaluated.capture(0,displaced=False),indent=2))
    instanced=host.snapshot(evaluated_geometry=True)
    (folder/'instances.json').write_text(json.dumps(instanced,indent=2))
    assert sum(len(m.get('instances',[m['matrix']])) for m in instanced['meshes'])==2
    mesh.channel('render').set('off'); instance.channel('render').set('on')
    hidden=host.snapshot(evaluated_geometry=True)
    assert sum(len(m.get('instances',[m['matrix']])) for m in hidden['meshes'])==1
    report['instances_and_hidden_source']=True
    instance.channel('render').set('off')
    assert not host.snapshot(evaluated_geometry=True)['meshes']
    # Existing texture fixture has two differently valued UV sets; named lookup
    # must select PaintUV rather than the first map alphabetically.
    exec(compile((root/'tools/probe_image_textures.py').read_text(),'probe_image_textures.py','exec'))
    textured=host.snapshot(evaluated_geometry=True)
    (folder/'textured.json').write_text(json.dumps(textured,indent=2))
    uvs=[uv for m in textured['meshes'] for uv in m['uvs']]
    assert [1,1] in uvs and [0,0] in uvs,uvs
    (folder/'textured.rdla').write_text(rdla.scene_text(textured,96,96,2,1))
    report['named_uvs']=True
    report['passed']=True
except Exception:
    report['error']=traceback.format_exc()
(folder/'report.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))
