# python
"""Run only in an isolated Modo 16.1v9 test profile. Creates lights without invoking MoonRay's Add command.
Checks fresh-item defaults and duplicate preservation; does not render. Not run automatically."""
from pathlib import Path
import json,traceback
import lx,modo
from moonray_modo import entities
from moonray_modo.preferences import Preferences
out=Path(__file__).resolve().parents[1]/'test-results/light-defaults';out.mkdir(parents=True,exist_ok=True)
preferences=Preferences();previous=preferences.get('light_intensity');result={'items':[]}
try:
    lx.eval('scene.new')
    scene=modo.Scene();preferences.set('light_intensity',37.)
    for name in ('MeshLight','RectLight','SphereLight','SpotLight'):
        item=scene.addItem(entities.item_type(name))
        actual=item.channel(entities.CHANNEL_PREFIX+'intensity').get()
        assert abs(actual-37.)<1e-6,(name,actual)
        item.channel(entities.CHANNEL_PREFIX+'intensity').set(8.)
        scene.select(item);lx.eval('item.duplicate')
        copies=scene.selected
        assert copies and abs(copies[0].channel(entities.CHANNEL_PREFIX+'intensity').get()-8.)<1e-6
        result['items'].append({'type':name,'default':actual,'duplicate_preserved':True})
    result['ok']=True
except Exception:result.update(ok=False,error=traceback.format_exc())
finally:
    preferences.set('light_intensity',previous)
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
