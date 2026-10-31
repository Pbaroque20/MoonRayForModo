# python
"""Isolated GUI test: Automatic Presence Shadows greys Presence Shadows in the render settings, and a light's own value is
then not written; each comes back with the preference off. A greyed command refuses to run, which is what is read here.
Writes test-results/presence-auto/report.json."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/presence-auto'
out.mkdir(parents=True, exist_ok=True)
report = {'steps': []}
try:
    from moonray_modo import presence_shadows
    from moonray_modo.preferences import Preferences
    store = Preferences().store
    held = store.value('presence_shadows_auto', None)
    for value in (0, 1, 0):
        lx.eval('moonray.pref.presenceShadowsAuto %d' % value)
        try:
            lx.eval('moonray.render.enable_presence_shadows 0')
            field = 'runs'
        except RuntimeError as error:
            field = 'refused: ' + str(error)[:120]
        report['steps'].append({'preference': value, 'automatic': presence_shadows.automatic(), 'query': lx.eval('moonray.pref.presenceShadowsAuto ?'), 'Presence Shadows': field})
    if held is None:
        store.remove('presence_shadows_auto')
    else:
        store.setValue('presence_shadows_auto', held)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('app.quit')
