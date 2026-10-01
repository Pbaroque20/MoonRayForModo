# python
"""Verify item-scoped material assignment on an evaluated mesh instance."""
import json
from pathlib import Path
import lx
import modo
from moonray_modo import evaluated,host
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo');folder=root/'test-results/render-cache'
path=root/'build/modo-geometry/MoonRayPreview.lx'
lx.eval('plugin.add {%s}' % path)
scene=modo.Scene()
scene.renderCamera.position.set((1.5,0,1))
scene.renderCamera.rotation.set((0,0,0))
scene.renderCamera.channel('focalLen').set(.02)
scene.renderCamera.channel('filmFit').set('horizontal')
mesh=scene.addMesh('Instance material source');geo=mesh.geometry
for point in ((-1,-1,-3),(1,-1,-3),(0,1,-3)):geo.vertices.new(point)
geo.polygons.new((0,1,2));geo.setMeshEdits()
lx.eval('select.item {%s} set' % mesh.id)
lx.eval('item.duplicate instance:true')
instance=scene.selected[0]
modo.LocatorSuperType(instance).position.set((3,0,0))
lx.eval('item.create mask')
mask=scene.selected[0];mask.setParent(scene.renderItem,0)
lx.eval('select.item {%s} set' % mask.id)
lx.eval('mask.setMesh {%s}' % instance.name)
mask_query=lx.eval('mask.setMesh ?')
graph_info={direction:[(i.id,i.type) for i in getattr(mask.itemGraph('shadeLoc'),direction)()]
            for direction in ('forward','reverse')}
material=scene.addItem('advancedMaterial');material.setParent(mask)
material.channel('diffCol.R').set(1)
material.channel('diffCol.G').set(0)
material.channel('diffCol.B').set(0)
raw=evaluated.capture(0,path=path)
(folder/'instance-material-raw.json').write_text(json.dumps({'mask':mask_query,'graph':graph_info,'data':raw},indent=2))
snapshot=host.snapshot(evaluated_geometry=True)
(folder/'instance-material.json').write_text(json.dumps(snapshot,indent=2))
colors=[snapshot['materials'][m['material']]['raw_color'] for m in snapshot['meshes']]
assert [1,0,0] in colors and any(c!=[1,0,0] for c in colors),colors
mask.channel('enable').set(0)
disabled=host.snapshot(evaluated_geometry=True)
assert not any(m['raw_color']==[1,0,0] for m in disabled['materials'].values())
mask.channel('enable').set(1)
(folder/'instance-material-report.json').write_text(json.dumps({'passed':True,'colors':colors}))
print('Evaluated instance material overrides passed',colors)
