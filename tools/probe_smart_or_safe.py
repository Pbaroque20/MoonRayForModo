# python
"""Isolated GUI test: Safe Denoising and Smart Render are one or the other, and a render Smart Render stopped goes on.

Two balls, MoonRay chosen.
1. Safe Denoising is switched on with the command its form uses, then Smart Render: Safe Denoising is off. Then Safe
   Denoising again: Smart Render is off. The same from the picture's menu.
2. With Smart Render on, the scene is rendered until Smart Render stops it. What the button then says is written
   down, and it is pressed: what happens to the render it took up is written down too."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/smart-or-safe'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': [], 'pairs': []}
held = {'waited': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def pair(name):
    values = panel_widget()._settings_values()['denoising']
    result['pairs'].append([name, values.get('safe'), values.get('smart'), panel_widget().status.text()[:90]])


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'button': panel.start.text(), 'rendering': panel._rendering, 'status': panel.status.text()[:110],
                            'timing': panel.render_timing.text(), 'buffer': panel.buffer.currentData(), 'info': panel.image_info.text()})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


def begin():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        lx.eval('moonray.render.denoise_safe 1')
        pair('form: safe on')
        lx.eval('moonray.render.smart_render 2')
        pair('form: smart medium')
        lx.eval('moonray.render.denoise_safe 1')
        pair('form: safe on again')
        panel._smart_chosen('draft')
        pair('menu: smart draft')
        panel._safe_chosen('optix')
        pair('menu: safe optix')
        panel._smart_chosen('draft')
        pair('menu: smart draft again')
        save()
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(3000, until_stopped)


def until_stopped():
    panel = panel_widget()
    held['waited'] += 1
    if panel._rendering and held['waited'] < 60:
        QtCore.QTimer.singleShot(1000, until_stopped)
        return
    note('smart_render_stopped')
    held['generation'] = panel.renderer.generation
    panel.start.click()
    QtCore.QTimer.singleShot(1500, went_on)


def went_on():
    result['renders_begun_by_the_button'] = panel_widget().renderer.generation - held['generation']
    note('button_pressed_after_the_stop')
    QtCore.QTimer.singleShot(25000, finish)


def finish():
    note('later')
    panel = panel_widget()
    if panel._rendering:
        panel.stop()
    lx.eval('moonray.render.smart_render 0')
    lx.eval('moonray.render.denoise_safe 0')
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
