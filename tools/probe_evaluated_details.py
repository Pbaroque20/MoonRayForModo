# python
"""Inspect and exercise tessellation from the supplied Render Cache SDK."""
import json
from pathlib import Path
import lx
import modo
from moonray_modo import evaluated, host
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder=root/'test-results/render-cache'
path=root/'build/modo-geometry/MoonRayPreview.lx'
lx.eval('plugin.add {%s}' % path)
scene=modo.Scene()
scene.renderItem.channel('resX').set(64)
scene.renderItem.channel('resY').set(64)
mesh=scene.addMesh('Evaluated subdivision cube')
geo=mesh.geometry
for point in ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)):
    geo.vertices.new(point)
for face in ((3,2,1,0),(4,5,6,7),(0,1,5,4),(2,3,7,6),(1,2,6,5),(3,0,4,7)):
    geo.polygons.new(face)
geo.setMeshEdits()
lx.eval('select.item {%s} set' % mesh.id)
lx.eval('poly.convert psubdiv face')
evaluated.capture(0,path=path)
data=host.snapshot(evaluated_geometry=True)
faces=sum(len(m['faces']) for m in data['meshes'])
assert faces>6,faces
assert not any(m['subdivision'] for m in data['meshes'])
report={'passed':False,'tessellated_faces':faces}
material=scene.items('advancedMaterial')[0]
lx.eval('item.create constant')
layer=scene.selected[0]
layer.setParent(scene.renderItem,0)
layer.channel('effect').set('displace')
layer.channel('value').set(1.0)
(folder/'details.json').write_text(json.dumps(report,indent=2,default=str))
material.channel('displace').set(.02)
displaced=host.snapshot(evaluated_geometry=True)
report['displacement_changed_vertices']=data['meshes'][0]['vertices']!=displaced['meshes'][0]['vertices']
report['displaced_faces']=sum(len(m['faces']) for m in displaced['meshes'])
assert report['displacement_changed_vertices']
assert not any('unsupported effect displace' in w for w in displaced['warnings'])
report['passed']=True
(folder/'details.json').write_text(json.dumps(report,indent=2,default=str))
print(json.dumps(report,default=str))
