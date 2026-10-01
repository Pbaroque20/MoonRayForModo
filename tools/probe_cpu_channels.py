# python
"""Capture Modo CPU integration channels in an isolated default scene."""
import json
from pathlib import Path
import modo
from moonray_modo import host
scene=modo.Scene()
report={}
for kind in ('camera','advancedMaterial','mesh'):
    items=scene.items(kind)
    item=items[0] if items else scene.addItem(kind)
    values={}
    for index in range(item.ChannelCount()):
        key=item.ChannelName(index)
        try:
            value=host.channel(item,key)
            if isinstance(value,(str,int,float,bool)) or value is None: values[key]=value
        except Exception: pass
    report[kind]=values
camera=scene.renderCamera
report['camera_projection_types']=[]
for i in range(5):
    camera.channel('projType').set(i)
    report['camera_projection_types'].append(host.channel(camera,'projType'))
folder=Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cpu-readiness')
folder.mkdir(parents=True,exist_ok=True)
(folder/'channels.json').write_text(json.dumps(report,indent=2))
print('CPU integration channels captured')
