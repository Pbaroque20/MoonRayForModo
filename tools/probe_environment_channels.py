# python
import json
from pathlib import Path
import modo
import lx
from moonray_modo import host
scene=modo.Scene()
report=[]
for item in scene.items():
    if item.type not in ('environment','envMaterial'):
        continue
    row={'id':item.id,'name':item.name,'type':item.type,
         'parent':item.parent.id if item.parent else None,'channels':{}}
    for index in range(item.ChannelCount()):
        key=item.ChannelName(index)
        try:
            value=host.channel(item,key)
            if isinstance(value,(str,int,float,bool)) or value is None:
                row['channels'][key]=value
        except Exception: pass
    report.append(row)
folder=Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\environment')
folder.mkdir(parents=True,exist_ok=True)
(folder/'channels.json').write_text(json.dumps(report,indent=2))
material=scene.items('envMaterial')[0]
types=[]
for n in range(5):
    material.channel('type').set(n)
    types.append(host.channel(material,'type'))
lx.eval('item.create imageMap')
layer=scene.selected[0]
locator=next(i for i in layer.itemGraph('shadeLoc').forward() if i.type=='txtrLocator')
projections=[]
for n in range(8):
    locator.channel('projType').set(n)
    projections.append(host.channel(locator,'projType'))
(folder/'enums.json').write_text(json.dumps({'types':types,'projections':projections},indent=2))
print('Environment channels captured')
