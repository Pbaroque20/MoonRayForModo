# python
"""Exercise Modo's real environment channels and spherical image links."""
import json
from pathlib import Path
import lx
import modo
from moonray_modo import host,properties
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
exec(compile((root/'tools/probe_image_textures.py').read_text(),'probe_image_textures.py','exec'))
environment=scene.items('environment')[0]
material=scene.items('envMaterial')[0]
material.channel('type').set('constant')
material.channel('zenColor.R').set(.8)
material.channel('zenColor.G').set(.2)
material.channel('zenColor.B').set(.1)
environment.channel('radiance').set(2)
environment.channel('visCam').set(0)
environment.channel('visRefl').set(0)
snapshot=host.snapshot()
value=snapshot['environments'][0]
assert value['kind']=='constant' and value['intensity']==2
assert not value['camera'] and not value['reflection']
assert abs(value['zenith'][0]-.8)<1e-6
for kind in ('grad2','grad4','overcast'):
    material.channel('type').set(kind)
    assert host.snapshot()['environments'][0]['kind']==kind
material.channel('type').set('physical')
assert not host.snapshot()['environments']
assert any('physical daylight' in w for w in host.snapshot()['warnings'])
material.channel('type').set('grad4')
layer.setParent(environment,0)
layer.channel('effect').set('envColor')
locator.channel('projType').set('spherical')
locator.rotation.set((0,.5,0))
snapshot=host.snapshot()
image=snapshot['environments'][0]
assert image['kind']=='image' and image['path']==str(source)
assert abs(image['matrix'][0]-1)>.01
assert not snapshot['warnings'],snapshot['warnings']
locator.channel('projType').set('lightprobe')
assert any('Spherical' in w for w in host.snapshot()['warnings'])
locator.channel('projType').set('spherical')
environment.channel('radiance').set(0)
assert not host.snapshot()['environments']
environment.channel('radiance').set(2)
values={'modo_environment':False,'environment_multiplier':2.5}
properties.write(scene.renderItem,values)
assert properties.scene_settings()==values
folder=root/'test-results/environment'; folder.mkdir(parents=True,exist_ok=True)
(folder/'host-snapshot.json').write_text(json.dumps(snapshot,indent=2))
(folder/'host.json').write_text(json.dumps({'passed':True,'native_controls':True,
    'image_links':True,'locator_rotation':True,'unsupported_warning':True,'stored_settings':True},indent=2))
print('Modo environment controls and HDRI link checks passed')
