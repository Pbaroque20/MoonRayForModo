# python
"""Check a native Undo performed at the host prompt, outside another command."""
from pathlib import Path
import json
import traceback
import lx
import modo
from moonray_modo import properties
root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
path = root / 'tools/probe_result.json'
report = json.loads(path.read_text(encoding='utf-8'))
try:
    selected = properties.selected_meshes()
    assert selected and properties.read(selected[0])['level'] == 2
    report['scene_and_object_settings']['undo'] = True
    saved = root / 'test-results/settings-roundtrip.lxo'
    lx.eval('!scene.saveAs {%s} $LXOB true' % saved)
    lx.eval('scene.open {%s}' % saved)
    restored = modo.Scene().item('MoonRay API Test')
    assert properties.read(restored)['level'] == 2
    assert properties.scene_settings()['render']['max_depth'] == 7
    assert properties.scene_settings()['aovs'] == ['depth', 'normal']
    report['scene_and_object_settings']['saved_and_reopened'] = True
except Exception:
    report['error'] = traceback.format_exc()
path.write_text(json.dumps(report, indent=2), encoding='utf-8')
