# python
"""Isolated GUI test: the preference that gives the M key to MoonRay's Assign Material, and back."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/assign-key'
out.mkdir(parents=True, exist_ok=True)
result = {}


def note(step):
    result['reached'] = step
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    note('start')
    result['before'] = lx.eval('moonray.pref.assignKey ?')
    note('queried')
    lx.eval('moonray.pref.assignKey 1')
    note('on')
    result['on'] = lx.eval('moonray.pref.assignKey ?')
    lx.eval('moonray.pref.assignKey 0')
    note('off')
    result['off'] = lx.eval('moonray.pref.assignKey ?')
except Exception:
    result['error'] = traceback.format_exc()
note(result.get('reached', '') + ' end')
lx.eval('!app.quit')
