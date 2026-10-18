# python
"""Isolated GUI test: Export as MoonRay Scene.

A small scene (a cube, an image on the environment) is saved, then exported each way the window offers: RDLA, RDLB,
RDLA + RDLB, RDLA with its textures collected, and RDLA for every frame of a three-frame range. The command is run
as the MoonRay menu runs it: its window is pictured, filled in and accepted, and the summary that follows is pictured and closed. tools/check_scene_export.py renders what
was written with MoonRay."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/scene-export'
out.mkdir(parents=True, exist_ok=True)
for old in out.rglob('*'):
    if old.is_file() and old.suffix.lower() in ('.rdla', '.rdlb', '.png', '.json', '.lxo', '.exr', '.tx'):
        old.unlink()
result = {'exports': {}}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def build():
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 160), ('resY', 120), ('first', 0), ('last', 2)):
        render.channel(name).set(value)
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('sizeX', 1.0), ('sizeY', 1.0), ('sizeZ', 1.0)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    # A small picture of its own on the environment, for textures to be collected.
    picture = QtGui.QImage(64, 32, QtGui.QImage.Format_RGB32)
    picture.fill(QtGui.QColor(90, 140, 220))
    image = out / 'maps' / 'sky.png'
    image.parent.mkdir(exist_ok=True)
    picture.save(str(image))
    environment = next(iter(scene.items('environment')))
    lx.eval('clip.addStill {%s}' % image)
    clip = scene.items('videoStill')[-1]
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    layer.channel('effect').set('envColor')
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('spherical')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'probe.lxo'))
    result['scene'] = str(out / 'probe.lxo')


def use_test_runtime():
    """The test Modo's own settings (not the user's) point at the test runtime, which has the converter, until the
    probe ends."""
    import os
    from moonray_modo.preferences import Preferences
    store = Preferences().store
    result['stored_runtime'] = store.value('runtime', '')
    store.setValue('runtime', os.environ['MOONRAY_MODO_RUNTIME'])


def restore_runtime():
    from moonray_modo.preferences import Preferences
    Preferences().store.setValue('runtime', result['stored_runtime'])


def exports():
    from moonray_modo import scene_export
    for label, choices in (('rdla', {'format': 'rdla'}), ('rdlb', {'format': 'rdlb'}), ('split', {'format': 'split'}),
                           ('collected', {'format': 'rdla', 'collect': True}), ('frames', {'format': 'rdla', 'frames': True}),
                           ('beauty', {'format': 'rdla', 'outputs': False})):
        held = {'path': out / label / ('%s.rdla' % label), 'outputs': True, 'collect': False, 'frames': False}
        held.update(choices)
        held['path'].parent.mkdir(exist_ok=True)
        warnings = []
        try:
            written = scene_export.export(held, warnings)
            result['exports'][label] = {'written': [str(p) for p in written], 'sizes': [p.stat().st_size for p in written],
                                        'warnings': warnings}
        except Exception:
            result['exports'][label] = {'error': traceback.format_exc()}
        save()


def shown():
    return [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]


def fill_dialog():
    try:
        from moonray_modo.scene_export import ExportDialog
        dialog = next(w for w in shown() if isinstance(w, ExportDialog))
        result['dialog_path'] = dialog.path.text()
        result['dialog_formats'] = [dialog.format.itemText(i) for i in range(dialog.format.count())]
        dialog.grab().save(str(out / 'dialog.png'))
        (out / 'menu').mkdir(exist_ok=True)
        dialog.path.setText(str(out / 'menu' / 'menu.rdla'))
        dialog.format.setCurrentIndex(dialog.format.findData('rdlb'))
        dialog.accept()
    except Exception:
        result['dialog_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(6000, close_summary)


def close_summary(tries=20):
    try:
        box = next((w for w in shown() if isinstance(w, QtWidgets.QMessageBox)), None)
        if box is None and tries:
            QtCore.QTimer.singleShot(1000, lambda: close_summary(tries - 1))
            return
        result['summary'] = box.text()
        box.grab().save(str(out / 'summary.png'))
        box.accept()
    except Exception:
        result['summary_error'] = traceback.format_exc()
    save()


def run_command():
    QtCore.QTimer.singleShot(2000, fill_dialog)
    try:
        lx.eval('moonray.scene.export')
        result['command'] = 'ran'
    except Exception:
        result['command_error'] = traceback.format_exc()
    save()
    restore_runtime()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


try:
    use_test_runtime()
    build()
    exports()
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(4000, run_command)
