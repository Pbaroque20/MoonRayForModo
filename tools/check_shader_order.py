"""Deferred export ordering regressions; fixture child lists run bottom to top."""
import sys,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import layers
class Item:
 def __init__(self,name,kind,children=(),**values):
  self.id=self.name=name;self.type=kind;self.parent=None;self.values=values;self.items=list(children)
  for item in self.items:item.parent=self
 def children(self):return self.items
channel=lambda item,key,default=None:item.values.get(key,default)
def material(item):return {'base_layer_id':item.id,'color':[.5,.5,.5]}
sys.modules['moonray_modo.host']=types.SimpleNamespace(channel=channel,color=lambda item,key,default=(0,0,0):channel(item,key,default),material_values=material)
below=Item('below','constant',effect='diffColor',color=[0,0,1])
base=Item('base','advancedMaterial')
above=Item('above','constant',effect='diffColor',color=[1,0,0])
top=Item('top','constant',effect='diffColor',color=[0,1,0])
group=Item('group','mask',[below,base,above,top],ptyp='material',ptag='skin')
root=Item('render','polyRender',[group]);scene=types.SimpleNamespace(renderItem=root)
assert [i.id for i in layers.ordered_items(root)]==['group','top','above','base','below']
for membership in (None,{'above','top','base','below'}):
 mats={'skin':material(base)};warnings=[]
 layers.collect(scene,mats,warnings,layer_filter=membership,material_key='skin')
 assert [v['value'] for v in mats['skin']['layers']]==[[1,0,0],[0,1,0]]
 assert any('below' in warning and 'overridden' in warning for warning in warnings)
# Material boundaries partition texture layers without reversing nested groups.
upper_base=Item('upperBase','advancedMaterial');upper_tex=Item('upperTex','constant',effect='diffColor',color=[1,1,0])
group.items.extend([upper_base,upper_tex]);upper_base.parent=group;upper_tex.parent=group
stack=layers.material_stack(scene,[base,upper_base],[],'skin')
assert [v['base_layer_id'] for v in stack]==['base','upperBase']
assert [v['value'] for v in stack[0]['layers']]==[[1,0,0],[0,1,0]]
assert stack[1]['layers'][0]['value']==[1,1,0]
print('Shader order fixture passed; verify displayed order in Modo separately')
