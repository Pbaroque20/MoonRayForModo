# python
"""Isolated GUI test: Automatic Presence Shadows greys Presence Shadows in the render settings and on a MoonRay light, and a
light's own value is then not written; each comes back with the preference off. A greyed command refuses to run, which is what
is read here. Realtime Sample % is set and read back by the command the preferences use.
Writes test-results/presence-auto/report.json."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/presence-auto'
out.mkdir(parents=True, exist_ok=True)
report = {'steps': []}


def runs(command):
    try:
        lx.eval(command)
        return 'runs'
    except RuntimeError as error:
        return 'refused: ' + str(error)[:120]


try:
    from moonray_modo import entities, presence_shadows
    from moonray_modo.preferences import Preferences
    store = Preferences().store
    held = store.value('presence_shadows_auto', None)
    lx.eval('moonray.entity.add RectLight')
    light = [item for item in modo.Scene().items(entities.item_type('RectLight'))][0] if hasattr(entities, 'item_type') else modo.Scene().selected[-1]
    light.select(replace=True)
    index = sorted(entities.classes()).index('RectLight')
    place = [key for key, _, _, _, _ in entities.channels('RectLight')].index('presence_shadows')
    popup = 'moonray.entity.choice%d_%d' % (index, place)
    report['popup'] = popup
    for value in (0, 1, 0):
        lx.eval('moonray.pref.presenceShadowsAuto %d' % value)
        scene = {'entities': [{'class': 'RectLight', 'identity': 'a', 'name': 'a', 'parameters': {'presence_shadows': 1}}]}
        report['steps'].append({'preference': value, 'automatic': presence_shadows.automatic(), 'query': lx.eval('moonray.pref.presenceShadowsAuto ?'),
                                'Presence Shadows': runs('moonray.render.enable_presence_shadows 0'), 'on the light': runs(popup + ' 1'),
                                'written': entities.checked(scene)[0]['parameters']})
    if held is None:
        store.remove('presence_shadows_auto')
    else:
        store.setValue('presence_shadows_auto', held)
    report['realtime before'] = lx.eval('moonray.render.xpu2_realtime ?')
    lx.eval('moonray.render.xpu2_realtime 50')
    report['realtime after'] = lx.eval('moonray.render.xpu2_realtime ?')
    from moonray_modo.preferences import realtime_share
    report['realtime the dialog reads'] = realtime_share()
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('app.quit')
