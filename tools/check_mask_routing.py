"""Deferred mask routing regression checks; no Modo process is launched."""
import sys,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.mask_types import tag_kind,needs_cache
from moonray_modo import layers
# Host channel stub allows testing parent traversal outside Modo.
sys.modules['moonray_modo.host']=types.SimpleNamespace(channel=lambda item,key,default=None:item.values.get(key,default))
class Item:
 def __init__(self,kind,parent=None,**values):self.type=kind;self.parent=parent;self.values=values
root=Item('polyRender')
for spelling in ('Material','material','MATR',b'MATR',int.from_bytes(b'MATR','big'),int.from_bytes(b'MATR','little')):
 assert tag_kind(spelling)=='material'
 mask=Item('mask',root,ptyp=spelling,ptag='')
 assert layers.material_tag(Item('advancedMaterial',mask))==''
 mask.values['ptag']='skin'
 assert layers.material_tag(Item('imageMap',mask),texture=True)=='skin'
 assert not needs_cache(spelling,'skin')
assert needs_cache('PART','body') and needs_cache('selection','faceSet') and needs_cache('material','skin',True)
mask=Item('mask',root,ptyp='selection',ptag='faceSet')
try: layers.material_tag(Item('advancedMaterial',mask))
except ValueError: pass
else: raise AssertionError('Unknown mask was incorrectly treated as global')
mask=Item('mask',root,ptyp='material',ptag='skin',enable=0)
assert layers.material_tag(Item('imageMap',mask),texture=True) is None
print('Mask routing passed; real-scene membership/appearance still needs Modo validation')

import tempfile
from moonray_modo.textures import resolve_scene_source
with tempfile.TemporaryDirectory() as temp:
 folder=Path(temp);(folder/'textures').mkdir();image=folder/'textures/body.png';image.write_bytes(b'fixture')
 assert resolve_scene_source('/old/project/textures/body.png',folder/'scene.fbx')==(image,True)
 assert resolve_scene_source(str(image),folder/'scene.fbx')[1] is False
 assert resolve_scene_source('/old/project/textures/missing.png',folder/'scene.fbx')[1] is False
 (folder/'project/textures').mkdir(parents=True);(folder/'project/textures/body.png').write_bytes(b'other')
 try: resolve_scene_source('/old/project/textures/body.png',folder/'scene.fbx')
 except ValueError: pass
 else: raise AssertionError('Ambiguous path accepted')
print('Relocated texture resolution passed')
