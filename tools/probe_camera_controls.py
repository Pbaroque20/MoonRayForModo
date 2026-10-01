# python
"""Check actual Modo camera controls without changing the user's scene."""
import json
import math
from pathlib import Path
import modo
from moonray_modo import host, rdla, properties
scene = modo.Scene()
camera = scene.renderCamera
for name,value in {'dof':1,'fStop':1.4,'focusDist':2.5,'irisBlades':6,'irisRot':.5}.items():
    camera.channel(name).set(value)
data = host.snapshot()
c = data['camera']
assert c['dof'] and abs(c['f_stop']-1.4)<1e-6 and c['focus_distance']==2.5
assert c['iris_blades']==6 and abs(c['iris_rotation']-.5)<1e-6
assert not any('Camera dof' in w for w in data['warnings'])
text = rdla.scene_text(data)
assert '["enable_dof"] = true' in text and '["bokeh_sides"] = 6' in text
camera.channel('dof').set(0)
assert not host.snapshot()['camera']['dof']
material=scene.items('advancedMaterial')[0]
properties.write(material,{'shader':'DwaBaseMaterial'})
material.channel('aniso').set(.7)
anisotropic=host.snapshot()
assert any(abs(m.get('anisotropy',0)-.7)<1e-6 for m in anisotropic['materials'].values())
assert not any('Anisotropy requires' in w for w in anisotropic['warnings'])
folder = Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\camera-controls')
folder.mkdir(parents=True,exist_ok=True)
(folder/'host.json').write_text(json.dumps({'passed':True,'camera':c},indent=2))
print('Modo depth-of-field channel translation passed')
