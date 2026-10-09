# python
import json
from pathlib import Path
import lx
import modo
from moonray_modo import host,properties,rdla
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
scene=modo.Scene()
mesh=scene.addMesh('MoonShine assignment test')
geo=mesh.geometry
for p in ((-1,-1,-3),(1,-1,-3),(0,1,-3)):
    geo.vertices.new(p)
geo.polygons.new((0,1,2)); geo.polygons[0].materialTag='Original'; geo.setMeshEdits()
scene.select(mesh)
try:
    lx.eval('moonray.material.assign')
except Exception:
    # Preserve the underlying API exception instead of only a Modo result code.
    import traceback
    from moonray_modo.materials import assign
    scene.select(mesh)
    try:
        assign()
    except Exception:
        (root/'test-results/material-error.txt').write_text(traceback.format_exc())
    raise
material=scene.selected[0]
assert material.name=='DwaBaseMaterial' and material.type=='advancedMaterial'
assert properties.read(material)['shader']=='DwaBaseMaterial'
assert abs(lx.eval('item.channel advancedMaterial$rough ?')-.35)<1e-6
tag=mesh.geometry.polygons[0].materialTag
assert material.parent.channel('ptag').get()==tag
lx.eval('moonray.material.thin true')
assert lx.eval('moonray.material.enable ?') and lx.eval('moonray.material.thin ?')
snapshot=host.snapshot()
assert snapshot['materials'][tag]['shader']=='DwaBaseMaterial' and snapshot['materials'][tag]['thin_geometry']
assert 'DwaBaseMaterial(' in rdla.scene_text(snapshot)
saved=root/'test-results/moonshine-material.lxo'
lx.eval('!scene.saveAs {%s} $LXOB true' % saved)
lx.eval('scene.open {%s}' % saved)
restored=modo.Scene().item('DwaBaseMaterial')
assert properties.read(restored)['shader']=='DwaBaseMaterial' and properties.read(restored)['thin_geometry']
(root/'test-results/material-host.json').write_text(json.dumps({'passed':True,'assignment':True,
    'native_properties':True,'rdla_shader':True,'saved_reopened':True},indent=2))
print('MoonShine assignment and persistence passed')
