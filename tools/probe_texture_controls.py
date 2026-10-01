# python
"""Discover real layer/locator channel values in an isolated Modo scene."""
import json
from pathlib import Path
import lx
import modo
from moonray_modo import host
scene=modo.Scene()
lx.eval('item.create imageMap')
layer=scene.selected[0]
locator=next(i for i in layer.itemGraph('shadeLoc').forward() if i.type=='txtrLocator')
def values(item):
    result={}
    for i in range(item.ChannelCount()):
        name=item.ChannelName(i)
        try:
            value=host.channel(item,name)
            if isinstance(value,(str,int,float,bool)): result[name]=value
        except Exception: pass
    return result
report={'layer':values(layer),'locator':values(locator),'blends':{}}
for i in range(32):
    try:
        layer.channel('blend').set(i)
        report['blends'][i]=host.channel(layer,'blend')
    except Exception: break
folder=Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cpu-readiness')
folder.mkdir(parents=True,exist_ok=True)
(folder/'texture-controls.json').write_text(json.dumps(report,indent=2))
print('Texture controls captured')
