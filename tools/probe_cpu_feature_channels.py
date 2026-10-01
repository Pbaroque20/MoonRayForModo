# python
"""Deferred Modo 16.1 channel/time-restoration checks. Run via run_script_probe.py."""
import json
from pathlib import Path
import traceback
import lx
import modo
from moonray_modo import host, rdla
from moonray_modo.animation import capture_frame

root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder=root/'test-results/cpu-features'; folder.mkdir(parents=True,exist_ok=True)
report={'passed':False,'level':'host channels; no visual parity check'}
try:
    assert lx.service.Platform().IsHeadless(), 'Use an isolated command-line Modo profile'
    assert lx.eval('query platformservice appversion ?')==1619
    scene=modo.Scene()
    material=scene.items('advancedMaterial')[0]
    for name,value in [('subsAmt',.4),('subsDist',.015),('tranDist',.2),('aniso',.65)]:
        material.channel(name).set(value)
    data=host.material_values(material)
    assert abs(data['subsurface_amount']-.4)<1e-6
    assert abs(data['subsurface_distance']-.015)<1e-6
    assert abs(data['absorption_distance']-.2)<1e-6
    scene.renderCamera.channel('projType').set('ortho')
    scene.renderItem.channel('region').set(True)
    for name,value in [('regX0',.1),('regY0',.2),('regX1',.7),('regY1',.8)]:
        scene.renderItem.channel(name).set(value)
    data=host.snapshot()
    assert data['camera']['projection']=='ortho'
    assert all(abs(a-b)<1e-6 for a,b in zip(data['region'],[.1,.2,.7,.8]))
    assert 'OrthographicCamera' in rdla.scene_text(data)
    before=lx.service.Selection().GetTime()
    capture_frame(before+1/24,False,False,24)
    assert lx.service.Selection().GetTime()==before
    report.update(passed=True,camera=data['camera'],region=data['region'])
except Exception:
    report['error']=traceback.format_exc()
finally:
    (folder/'host-channels.json').write_text(json.dumps(report,indent=2))
if not report['passed']: raise RuntimeError(report['error'])
