# python
"""Isolated GUI test: the MoonRay scene importer's Import into a new scene and Close buttons.

A ball is made in the scene that is open. The importer reads one of MoonRay's example scenes, and Import into a new
scene is pressed: the scene that was open still holds only what it held, and a new one holds the imported scene. Close
then shuts the importer's window."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/import-new-scene'
out.mkdir(parents=True, exist_ok=True)
SOURCE = root / 'downloads/moonray-example-scenes/scenes/veach-mis/scene.rdla'
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def dialog():
    from moonray_modo import rdl_import_dialog
    return rdl_import_dialog._dialog


def scenes():
    return int(lx.eval('query sceneservice scene.N ?'))


def note(name):
    window = dialog()
    scene = modo.Scene()
    result['steps'].append({'step': name, 'scenes': scenes(), 'current_scene': scene.name, 'meshes': [m.name for m in scene.items('mesh')][:8],
                            'mesh_count': len(scene.items('mesh')), 'lights': len(scene.items('light')),
                            'buttons': {b.text(): b.isEnabled() for b in (window.choose, window.import_button, window.new_button, window.cancel, window.close_button)},
                            'window_shown': window.isVisible(), 'report': window.report.toPlainText()[:160]})
    if window.isVisible():
        window.grab().save(str(out / ('%d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(40000)
def read():
    from moonray_modo.rdl_import_dialog import show
    held['first'] = modo.Scene().name
    held['first_meshes'] = len(modo.Scene().items('mesh'))
    show(str(SOURCE))


@step(20000)
def into_new():
    note('scene_read')
    dialog().new_button.click()


@step(1500)
def close():
    note('imported_into_a_new_scene')
    result['first_scene'] = held['first']
    dialog().close_button.click()


@step(500)
def finish_():
    note('closed')


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!!app.quit')
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
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, lambda: run())
