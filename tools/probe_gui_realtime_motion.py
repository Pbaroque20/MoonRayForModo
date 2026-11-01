# python
"""Isolated GUI test: a copy of dragon_test.lxo (MOONRAY_PROBE_SCENE), or a new scene's moving cube. Render with Motion Blur on on the Modo camera
alone; then XPU2 realtime with its preference off and on. Saves each picture and says whether its scene had motion blur.
Writes test-results/realtime-motion/."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/realtime-motion'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
        save()
    QtCore.QTimer.singleShot(ms, run)


def picture(name):
    panel = held['panel']
    snapshot = (panel.renderer.active or {}).get('snapshot', {})
    if not panel.preview.image.isNull():
        panel.preview.image.save(str(out / (name + '.png')))
    return {'motion in the scene': bool(snapshot.get('motion_steps')), 'realtime': bool(snapshot.get('_realtime')), 'status': panel.status.text(),
            'xpu2': getattr(panel.renderer.session, 'xpu2_active', None), 'hud': panel._hud_words(), 'rt': panel.rt.text()}


def show():
    lx.eval('moonray.page preview')
    later(3000, render)


def render():
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    result['kit Motion Blur setting'] = panel._settings_values()['final_motion']
    result['camera Motion Blur'] = int(modo.Scene().renderCamera.channel('motionBlur').get())
    result['motion wanted'] = panel._motion_wanted()
    result['window would say'] = panel._animation_scene()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.preferences.set('xpu2_motion', False)
    panel.start.click()
    held['began'] = time.monotonic()
    later(1000, lambda: wait(600, after_render))


def wait(tries, step):
    panel = held['panel']
    if panel._rendering and tries > 0:
        later(500, lambda: wait(tries - 1, step))
    else:
        result.setdefault('seconds', {})[step.__name__] = round(time.monotonic() - held['began'], 1)
        step()


def begin(step, tries=360):
    held['began'] = time.monotonic()
    later(1000, lambda: wait(tries, step))


def edit():
    """An edit realtime has to follow: the time moved one frame."""
    lx.eval('select.time %g' % (lx.service.Selection().GetTime() + 1 / float(modo.Scene().fps)))


def after_render():
    result['Render'] = picture('render')
    held['panel'].rt.setChecked(True)
    result['RT off pref says'] = held['panel'].rt.text()
    begin(rt_off_first)


def rt_off_first():
    result['RT, preference off'] = picture('rt-off')
    edit()
    later(1500, lambda: begin(rt_off_edit))


def rt_off_edit():
    result['RT off, after an edit'] = picture('rt-off-edit')
    panel = held['panel']
    panel.rt.setChecked(False)
    later(3000, start_blurred)


def start_blurred():
    panel = held['panel']
    panel.preferences.set('xpu2_motion', True)
    panel.rt.setChecked(True)
    result['RT on pref says'] = panel.rt.text()
    begin(rt_on_first)


def rt_on_first():
    result['RT, preference on'] = picture('rt-on')
    edit()
    later(1500, lambda: begin(rt_on_edit))


def rt_on_edit():
    panel = held['panel']
    result['RT on, after an edit'] = picture('rt-on-edit')
    panel.rt.setChecked(False)
    panel.preferences.set('xpu2_motion', False)
    result['done'] = True


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('!scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    later(1000, show)
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
