# python
"""Isolated GUI test: the options on the MoonRay page of Modo's Preferences are read, changed and put back.

The options are kept with the preview window's own, which this machine's Modo shares, so every one is put back as it
was found."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/preferences'
out.mkdir(parents=True, exist_ok=True)
result = {}
CASES = (('moonray.pref.engine', 1), ('moonray.pref.live', 1), ('moonray.pref.renderOnOpen', 1), ('moonray.pref.noticesOpen', 1),
         ('moonray.pref.assignType', 3), ('moonray.pref.assignSmooth', 0), ('moonray.pref.assignAngle', 75.0),
         ('moonray.pref.draftInk', 1), ('moonray.pref.lightIntensity', 77.0))
found = {}
try:
    for command, value in CASES:
        found[command] = lx.eval(command + ' ?')
    result['found'] = found
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    changed = {}
    for command, value in CASES:
        lx.eval('%s %s' % (command, value))
        changed[command] = lx.eval(command + ' ?')
    result['changed'] = changed
    from moonray_modo import draft, entities
    from moonray_modo.preferences import Preferences
    held = Preferences()
    result['stored'] = {key: held.get(key) for key in ('preview_engine', 'ipr', 'render_on_open', 'notices_open', 'assign/shader', 'assign/smooth', 'assign/angle', 'draft/ink', 'light_intensity')}
    result['ink'] = draft.ink()
    lx.eval('moonray.entity.add RectLight')
    lamp = modo.Scene().selected[0]
    result['new_light_intensity'] = lamp.channel(entities.CHANNEL_PREFIX + 'intensity').get()
    result['runtime'] = lx.eval('moonray.pref.runtime ?')
except Exception:
    result['error'] = traceback.format_exc()
finally:
    restored = {}
    for command, value in found.items():
        try:
            lx.eval('%s %s' % (command, value))
            restored[command] = lx.eval(command + ' ?')
        except Exception as exc:
            restored[command] = str(exc)
    result['restored'] = restored
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
