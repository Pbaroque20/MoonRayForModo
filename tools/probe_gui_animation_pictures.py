# python
"""Isolated GUI test of Render Animation's frames as pictures alone, and of the denoised frames' names, in a new scene with a moving
cube (frames 1-2): denoised EXRs, then denoised PNG, JPEG, TIFF and Targa with no EXR left, then the PNGs asked for again.
Writes test-results/animation-pictures/."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/animation-pictures'
shutil.rmtree(out, ignore_errors=True)
(out / 'frames').mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
held = {'to do': [('exr', None), ('png', 'only:png8'), ('jpg', 'only:jpg'), ('tif', 'only:tif8'), ('tga', 'only:tga'), ('both', 'png8')]}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def guarded(step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
        save()
    return run


def later(ms, step):
    QtCore.QTimer.singleShot(ms, guarded(step))


def setup():
    scene = modo.Scene()
    mesh = scene.addMesh('Mover')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', .5), ('sizeY', .5), ('sizeZ', .5)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    fps = float(scene.fps)
    position = modo.LocatorSuperType(mesh).position
    position.x.set(-1.0, time=1 / fps, key=True)
    position.x.set(1.0, time=2 / fps, key=True)
    render = scene.renderItem
    for name, value in (('first', 1), ('last', 2), ('step', 1), ('resX', 320), ('resY', 180)):
        render.channel(name).set(value)
    modo.LocatorSuperType(scene.renderCamera).position.set((0, 0, 4))
    modo.LocatorSuperType(scene.renderCamera).rotation.set((0, 0, 0))
    scene.addItem('sunLight')
    lx.eval('moonray.page preview')
    later(3000, begin)


def begin():
    from moonray_modo.panel import Panel
    panel = next(widget for widget in QtWidgets.QApplication.allWidgets() if isinstance(widget, Panel))
    held['panel'] = panel
    result['xpu2'] = __import__('moonray_modo.native', fromlist=['xpu2']).xpu2()
    panel._store(denoising=dict(panel._settings_values()['denoising'], engine=os.environ.get('MOONRAY_PROBE_DENOISER', 'optix'), final=True))
    next_run()


def ask(prefix, kind, missing=False):
    panel = held['panel']
    from moonray_modo import output_dialog
    real = output_dialog.AnimationDialog

    class Answered(real):
        def exec_(self):
            self.folder.setText(str(out / 'frames'))
            self.prefix.setText(prefix)
            self.digits.setValue(3)
            self.first.setValue(1)
            self.last.setValue(2)
            self.missing.setChecked(missing)
            self.type.setCurrentIndex(self.type.findData(kind))
            return True
    output_dialog.AnimationDialog = Answered
    try:
        panel.render_animation()
    finally:
        output_dialog.AnimationDialog = real


def files(prefix):
    return sorted(path.name for path in (out / 'frames').iterdir() if path.name.startswith(prefix + '.') or path.name.startswith(prefix + '_'))


def next_run():
    if not held['to do']:
        later(500, again)
        return
    prefix, kind = held['to do'].pop(0)
    ask(prefix, kind)
    wait(lambda: finished(prefix))


def wait(then, tries=480):
    panel = held['panel']
    (out / 'render-log.txt').write_text(panel.renderer.log, encoding='utf-8', errors='replace')
    if panel.sequence is not None and panel.sequence.running and tries > 0:
        later(500, lambda: wait(then, tries - 1))
        return
    later(500, then)


def finished(prefix):
    result['runs'][prefix] = {'status': held['panel'].status.text(), 'files': files(prefix)}
    next_run()


def again():
    # The same sequence asked for again: refused, its pictures untouched.
    ask('png', 'only:png8')
    result['asked again'] = {'status': held['panel'].status.text(), 'files': files('png')}
    # And resumed: nothing is left to render.
    ask('png', 'only:png8', missing=True)
    wait(resumed)


def resumed():
    result['resumed'] = {'status': held['panel'].status.text(), 'files': files('png')}
    held['panel']._store(denoising=dict(held['panel']._settings_values()['denoising'], engine='off'))
    result['done'] = True
    save()


# Here, in the script's own command: Modo refuses a scene's edits from a timer.
guarded(setup)()
