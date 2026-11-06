# python
"""Command line: the MoonRay Source Override 'Bump node in MoonShine graphs' (moonray.pref.bumpNode): its value as
Modo reads it, turned off and on again, and native.bump_node() each time. Writes test-results/bump-node/override.json."""
import json
import pathlib
import traceback
import lx

result = {}
try:
    from moonray_modo import native
    result['start'] = (lx.eval('moonray.pref.bumpNode ?'), native.bump_node())
    lx.eval('moonray.pref.bumpNode false')
    result['off'] = (lx.eval('moonray.pref.bumpNode ?'), native.bump_node())
    lx.eval('moonray.pref.bumpNode true')
    result['on'] = (lx.eval('moonray.pref.bumpNode ?'), native.bump_node())
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\bump-node\override.json').write_text(json.dumps(result, indent=1, default=str))
