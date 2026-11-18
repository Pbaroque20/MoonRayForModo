# python
"""GUI check of MoonLightIPR's Render Animation alpha: a new scene with a cube in front of nothing (frames 1-2, 160 x 90),
Render Animation with MoonLightIPR as its engine, saved as OpenEXR and PNG 8-bit. Records the frames written and the
status; the files' channels and alpha are read afterwards (outside Modo) from test-results/moonlightipr-animation-alpha.
Writes report.json there."""
import json
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/moonlightipr-animation-alpha'
shutil.rmtree(out, ignore_errors=True)
(out / 'frames').mkdir(parents=True, exist_ok=True)
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


def setup():
    scene = modo.Scene()
    mesh = scene.addMesh('Box')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', .5), ('sizeY', .5), ('sizeZ', .5)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    render = scene.renderItem
    for name, value in (('first', 1), ('last', 2), ('step', 1), ('resX', 160), ('resY', 90)):
        render.channel(name).set(value)
    modo.LocatorSuperType(scene.renderCamera).position.set((0, 0, 4))
    scene.addItem('sunLight')
    lx.eval('moonray.page preview')
    later(3000, start)


def find_panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def start():
    panel = held['panel'] = find_panel()
    from moonray_modo import output_dialog
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    result['alpha in render settings'] = 'alpha' in panel._settings_values().get('aovs', [])
    real = output_dialog.AnimationDialog

    class Answered(real):
        def exec_(self):
            self.folder.setText(str(out / 'frames'))
            self.prefix.setText('cube')
            self.first.setValue(1)
            self.last.setValue(2)
            self.motion.setChecked(False)
            self.engine.setCurrentIndex(self.engine.findData('moonlightipr'))
            self.type.setCurrentIndex(self.type.findData('png8'))
            result['type'] = self.type.currentText()
            result['summary'] = self.summary.text()
            return True
    output_dialog.AnimationDialog = Answered
    try:
        panel.render_animation()
    finally:
        output_dialog.AnimationDialog = real
    result['animation'] = type(panel.sequence).__name__
    later(500, lambda: watch(480))


def watch(tries):
    panel = held['panel']
    if panel.sequence is not None and panel.sequence.running and tries > 0:
        later(250, lambda: watch(tries - 1))
        return
    result['status'] = panel.status.text()
    result['files'] = sorted(p.name for p in (out / 'frames').iterdir())
    finish()


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


save()
# Scene edits at the probe's top level: from a Qt timer Modo refuses them (addMesh: bad result).
guarded(setup)()
