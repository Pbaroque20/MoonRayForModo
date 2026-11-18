# python
"""Pictures for the docs, from a test Modo: Convert LXO to RDL after converting two small scenes made here, the Render
Animation window with MoonRay (XPU2) chosen, and the Preview Preferences with Follow drags. The scenes and the files
live under C:\\Users\\Public\\Documents\\MoonRay Docs, so that no one's own paths show. Writes test-results/docs-images/."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/docs-images'
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
public = pathlib.Path(os.environ.get('PUBLIC', r'C:\Users\Public')) / 'Documents' / 'MoonRay Docs'
shutil.rmtree(public, ignore_errors=True)
(public / 'Scenes').mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def guarded(step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
        save()
    return run


def later(ms, step):
    QtCore.QTimer.singleShot(ms, guarded(step))


def made(name, tool, sizes):
    """A small scene of one primitive under a sun, saved in the Public folder."""
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh(name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set %s on' % tool)
    lx.eval('tool.reset')
    for axis, value in sizes:
        lx.eval('tool.attr %s %s %s' % (tool, axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set %s off' % tool)
    scene.addItem('sunLight')
    path = public / 'Scenes' / (name + '.lxo')
    lx.eval('scene.saveAs {%s} $LXOB false' % path)
    return path


# Scene edits at the probe's top level: from a Qt timer Modo refuses them.
try:
    held['scenes'] = [made('Studio Cube', 'prim.cube', (('sizeX', 1), ('sizeY', 1), ('sizeZ', 1))),
                      made('Spheres', 'prim.sphere', (('sizeX', 0.5), ('sizeY', 0.5), ('sizeZ', 0.5)))]
except Exception:
    result.setdefault('errors', []).append('scenes: ' + traceback.format_exc())


def converter():
    lx.eval('moonray.lxo.convert')
    from moonray_modo import lxo_convert_window
    window = held['window'] = lxo_convert_window._window
    window.resize(760, 520)
    window.clear()
    window.add([str(p) for p in held['scenes']])
    window.beside.setCurrentIndex(window.beside.findData('folder'))
    window.folder.setText(str(public / 'RDL'))
    window.format.setCurrentIndex(window.format.findData('rdlb'))
    window.at_once.setValue(2)
    window.start()
    later(1000, wait)


def wait(tries=[240]):
    window = held['window']
    tries[0] -= 1
    if window.batch is not None and window.batch.running and tries[0] > 0:
        later(500, wait)
        return
    result['converter'] = {'status': window.status.text(),
                           'rows': [[window.scenes.topLevelItem(i).text(c) for c in range(3)] for i in range(window.scenes.topLevelItemCount())]}
    window.scenes.setCurrentItem(window.scenes.topLevelItem(0))
    QtWidgets.QApplication.processEvents()
    window.grab().save(str(out / 'convert-lxo-to-rdl.png'))
    window.close()
    lx.eval('moonray.page preview')
    later(2500, animation)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def animation():
    from moonray_modo import output_dialog, sequence_plan
    source = panel()
    dialog = output_dialog.AnimationDialog(source.settings, source, sequence_plan.window_values({}, source._animation_scene()))
    dialog.engine.setCurrentIndex(dialog.engine.findData('xpu2'))
    dialog.folder.setText(str(public / 'Renders'))
    dialog.prefix.setText('shot')
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.grab().save(str(out / 'render-animation-engine.png'))
    result['animation engines'] = [dialog.engine.itemText(i) for i in range(dialog.engine.count())]
    dialog.reject()
    later(500, preferences)


def preferences():
    from moonray_modo.preferences import Dialog
    source = panel()
    dialog = Dialog(source.preferences, source)
    follow = next(box for box in dialog.findChildren(QtWidgets.QCheckBox) if box.text() == 'Follow drags')
    follow.setChecked(True)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    whole = dialog.grab()
    whole.save(str(out / 'preview-preferences-whole.png'))
    # The MoonLightIPR rows about the box: from its section's heading to the box, with room around.
    heading = next((label for label in dialog.findChildren(QtWidgets.QLabel) if label.text() == 'MoonLightIPR quality'), None)
    top = heading.mapTo(dialog, QtCore.QPoint(0, 0)).y() - 8 if heading is not None else follow.mapTo(dialog, QtCore.QPoint(0, 0)).y() - 120
    bottom = follow.mapTo(dialog, QtCore.QPoint(0, 0)).y() + follow.height() + 10
    whole.copy(QtCore.QRect(0, max(0, top), whole.width(), bottom - max(0, top))).save(str(out / 'preview-preferences-follow-drags.png'))
    result['preferences'] = {'size': [whole.width(), whole.height()], 'crop': [top, bottom]}
    dialog.reject()
    finish()


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


save()
later(3000, converter)
