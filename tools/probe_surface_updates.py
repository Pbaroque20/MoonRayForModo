# python
"""Read-only export checks after building a disposable Modo test scene."""
import json
from pathlib import Path
import lx
import modo

root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
exec(compile((root/'tools/probe_image_textures.py').read_text(), 'probe_image_textures.py','exec'))
from moonray_modo import host
scene=modo.Scene()
material=next(i for i in scene.items('advancedMaterial') if i.parent==mask)
layer.channel('effect').set('normal')
normal_snapshot=host.snapshot()
normal=normal_snapshot['materials']['texture_test']['layers'][0]
assert normal['effect']=='normal' and not normal['srgb']
layer.channel('effect').set('bump')
material.channel('bumpAmp').set(.03)
bump_snapshot=host.snapshot()
assert abs(bump_snapshot['materials']['texture_test']['bump_strength']-.03)<1e-6
layer.channel('effect').set('diffColor')
lx.eval('item.create constant')
top=scene.selected[0]; top.setParent(mask,0)
top.channel('effect').set('diffColor'); top.channel('opacity').set(.25)
top.channel('color.R').set(0); top.channel('color.G').set(0); top.channel('color.B').set(1)
stack=host.snapshot()['materials']['texture_test']['layers']
assert [n['kind'] for n in stack]==['imageMap','constant'], stack
assert stack[-1]['opacity']==.25
top.channel('enable').set(0)
assert len(host.snapshot()['materials']['texture_test']['layers'])==1
lx.eval('select.item {%s} set' % mesh.id)
lx.eval('item.duplicate instance:true')
instance=scene.selected[0]
modo.LocatorSuperType(instance).position.set((2,0,0))
snapshot=host.snapshot()
assert len(snapshot['meshes'])==1
assert len(snapshot['meshes'][0]['instances'])==2
assert snapshot['meshes'][0]['instances'][1][12]==2
mesh.channel('render').set('off')
instance.channel('render').set('on')
hidden=host.snapshot()
(root/'test-results/surface-updates/host-debug.json').write_text(json.dumps({'hidden':hidden,
    'source_render':host.channel(mesh,'render'),'instance_render':host.channel(instance,'render')},indent=2))
assert len(hidden['meshes'])==1 and len(hidden['meshes'][0]['instances'])==1, 'Hidden-source snapshot differs'
assert not any('meshInst' in w for w in hidden['warnings'])
instance.channel('render').set('off')
assert not host.snapshot()['meshes']
instance.channel('render').set('on')
mesh.channel('render').set('on')
folder=root/'test-results/surface-updates'
folder.mkdir(parents=True,exist_ok=True)
(folder/'host-snapshot.json').write_text(json.dumps(snapshot,indent=2))
(folder/'host.json').write_text(json.dumps({'passed':True,'ordered_layers':True,
    'normal_raw_color':True,'bump_distance':True,'shared_instances':True,'hidden_source':True},indent=2))
print('Surface host checks passed')
