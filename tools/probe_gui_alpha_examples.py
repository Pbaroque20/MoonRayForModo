# python
"""Isolated GUI test: Render Animation's files and their alpha, for looking at. A new scene with a box moving under motion blur, whose soft
edges have partial alpha, in front of a still box and Modo's environment. One frame as denoised EXR, PNG, TIFF, Targa and JPEG with Alpha on
on XPU2 and MoonRay XPU, and a PNG with Alpha off. Writes test-results/alpha-examples/."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
# A dim light, so that a soft edge's colour can be seen, with Modo's environment seen by the camera or hidden from it.
variant = os.environ.get('MOONRAY_ALPHA_VARIANT', '')
out = root / ('test-results/alpha-examples' + ('-' + variant if variant else ''))
shutil.rmtree(out, ignore_errors=True)
(out / 'frames').mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
KINDS = (('exr', None, True), ('png', 'only:png8', True), ('tif', 'only:tif8', True), ('tga', 'only:tga', True), ('jpg', 'only:jpg', True), ('noalpha_png', 'only:png8', False))
if variant:
    KINDS = KINDS[:2]
held = {'to do': [(engine, name, kind, alpha) for engine in ('xpu2', 'xpu') for name, kind, alpha in KINDS]}


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


def box(name, size, at):
    scene = modo.Scene()
    mesh = scene.addMesh(name)
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', size), ('sizeY', size), ('sizeZ', size)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    modo.LocatorSuperType(mesh).position.set(at)
    return mesh


def setup():
    scene = modo.Scene()
    box('Still', .7, (1, .3, -1))
    mover = box('Mover', .7, (0, 0, 0))
    fps = float(scene.fps)
    position = modo.LocatorSuperType(mover).position
    position.x.set(-3.0, time=0, key=True)
    position.x.set(3.0, time=4 / fps, key=True)
    render = scene.renderItem
    for name, value in (('first', 2), ('last', 2), ('step', 1), ('resX', 480), ('resY', 270)):
        render.channel(name).set(value)
    modo.LocatorSuperType(scene.renderCamera).position.set((0, 0, 4))
    modo.LocatorSuperType(scene.renderCamera).rotation.set((0, 0, 0))
    scene.renderCamera.channel('motionBlur').set(1)
    sun = scene.addItem('sunLight')
    if variant:
        sun.channel('radiance').set(.5)
        for item in scene.items('environment'):
            item.channel('visCam').set(variant != 'hidden')
            result.setdefault('environment seen', []).append(item.channel('visCam').get())
    lx.eval('select.time %g' % (2 / fps))
    lx.eval('moonray.page preview')
    later(3000, begin)


def begin():
    from moonray_modo.panel import Panel
    panel = next(widget for widget in QtWidgets.QApplication.allWidgets() if isinstance(widget, Panel))
    held['panel'] = panel
    panel._store(denoising=dict(panel._settings_values()['denoising'], engine='optix', final=True))
    panel.preferences.set('camera_light_lpe', variant != 'switch-off')
    next_run()


def ask(prefix, kind):
    panel = held['panel']
    from moonray_modo import output_dialog
    real = output_dialog.AnimationDialog

    class Answered(real):
        def exec_(self):
            self.folder.setText(str(out / 'frames'))
            self.prefix.setText(prefix)
            self.digits.setValue(3)
            self.first.setValue(2)
            self.last.setValue(2)
            self.type.setCurrentIndex(self.type.findData(kind))
            return True
    output_dialog.AnimationDialog = Answered
    try:
        panel.render_animation()
    finally:
        output_dialog.AnimationDialog = real


def next_run():
    panel = held['panel']
    if not held['to do']:
        panel.preferences.set('xpu2/renderer', 'xpu2')
        panel.preferences.set('camera_light_lpe', True)
        panel._store(aovs=held['aovs at the start'])
        result['done'] = True
        return
    engine, name, kind, alpha = held['to do'].pop(0)
    held.setdefault('aovs at the start', panel._settings_values().get('aovs'))
    panel.preferences.set('xpu2/renderer', 'xpu' if engine == 'xpu' else 'xpu2')
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel._store(aovs=(['alpha', 'environment_background'] if variant == 'background' else ['alpha']) if alpha else [])
    prefix = held['prefix'] = engine + '_' + name
    ask(prefix, kind)
    later(1000, lambda: wait(600))


def wait(tries):
    panel = held['panel']
    if panel.sequence is not None and panel.sequence.running and tries > 0:
        later(500, lambda: wait(tries - 1))
        return
    later(1500, finished)


def finished():
    panel = held['panel']
    prefix = held['prefix']
    (out / (prefix + '-log.txt')).write_text(panel.renderer.log, encoding='utf-8', errors='replace')
    result['runs'][prefix] = {'status': panel.status.text(), 'xpu2': getattr(panel.renderer.session, 'xpu2_active', None), 'aovs': panel._settings_values().get('aovs'),
                              'files': sorted(path.name for path in (out / 'frames').iterdir() if path.name.startswith(prefix + '.'))}
    next_run()


# Here, in the script's own command: Modo refuses a scene's edits from a timer.
guarded(setup)()
save()
