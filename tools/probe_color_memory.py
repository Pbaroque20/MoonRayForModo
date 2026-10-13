# python
"""Isolated GUI test: colour management follows Modo's system preferences, and what is chosen through MoonRay is kept.

Nothing is rendered. What Modo's system preferences say of colour management is written down with what the preview
then reads. The colour space of 8-bit pictures is changed in the preferences: what is read follows. View Transform is
then set to ACES through MoonRay's render settings, and a new scene is made: it starts on ACES, as the next Modo
would. What was changed is put back at the end."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/color-memory'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
KEYS = ('default_ocio_config', 'float_default_colorspace', '8bit_default_colorspace', 'view_default_colorspace')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def note(name):
    from moonray_modo import display_memory, modo_color
    modo_color._FROM = None
    result['steps'].append({'step': name, 'preferences': {key: modo_color.preference(key) for key in KEYS}, 'read': modo_color.refresh(),
                            'view_choice': lx.eval('moonray.render.view ?'), 'remembered': display_memory.remembered()})
    save()


def forget():
    from moonray_modo import display_memory, native
    store = QtCore.QSettings('MoonRayForModo', native.settings_name())
    store.remove('display')
    display_memory._held = None


try:
    forget()
    note('as_modo_comes')
    was = lx.eval('pref.value colormanagement.8bit_default_colorspace ?')
    result['was'] = was
    try:
        lx.eval('!pref.value colormanagement.8bit_default_colorspace {nuke-default:rec709}')
        lx.eval('!!scene.new')
        note('preference_set_to_rec709')
    finally:
        lx.eval('!pref.value colormanagement.8bit_default_colorspace {%s}' % was)
    lx.eval('!!scene.new')
    note('preference_put_back')
    lx.eval('!moonray.render.view 1')
    note('aces_chosen_through_moonray')
    lx.eval('!!scene.new')
    note('a_new_scene')
except Exception:
    result['error'] = traceback.format_exc()
try:
    forget()
except Exception:
    result['forget_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
