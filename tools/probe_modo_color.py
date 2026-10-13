# python
"""Isolated GUI test: the preview follows Modo's own colour management unless told otherwise.

A ball under Modo's light, rendered with MoonRay. What was read of Modo's colour management and what the display then
uses are written down, with how bright the picture is: as the scene comes (Modo's default configuration and its Final
Color Output viewed as sRGB); with the output's colour space set to rec709 in Modo; and with View Transform set to
ACES in the MoonRay render settings, which no longer follows Modo."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/modo-color'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def bright():
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(64, 36)
    data = bytes(image.constBits())[:image.bytesPerLine() * image.height()]
    return round(sum(data) / float(len(data)), 2) if data else None


def note(name):
    from moonray_modo import display, modo_color
    panel = panel_widget()
    stored = panel._settings_values()
    shown = display.values(stored['display'])
    result['steps'].append({'step': name, 'brightness': bright(), 'stored_view': stored['display'].get('view'), 'read_from_modo': modo_color.RESOLVED,
                            'shown_with': {key: shown[key] for key in ('view', 'config', 'source', 'display', 'ocio_view')}, 'status': panel.status.text()[:80], 'foot': panel.image_info.text()})
    panel.window().grab().save(str(out / ('%d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(25000)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(25000)
def as_rec709():
    note('as_the_scene_comes')
    output = next(item for item in modo.Scene().items('renderOutput') if item.channel('effect').get() == 'shade.color')
    lx.eval('!select.item {%s} set' % output.id)
    for command in ('!item.channel renderOutput$colorspace {nuke-default:rec709}', '!item.channel colorspace {nuke-default:rec709}'):
        try:
            lx.eval(command)
            break
        except Exception as exc:
            result.setdefault('tried', []).append([command, str(exc)[:80]])
    result['output_colorspace'] = output.channel('colorspace').get()
    panel_widget().start.click()


@step(25000)
def as_aces():
    note('output_viewed_as_rec709')
    lx.eval('!moonray.render.view 1')
    result['view_now'] = lx.eval('moonray.render.view ?')
    panel_widget().start.click()


@step(500)
def finish_():
    note('view_transform_aces')
    panel_widget().stop()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
