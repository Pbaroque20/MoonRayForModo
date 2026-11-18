# python
"""GUI check that the alpha is blurred by depth of field as the picture is, in stills and in animations, with MoonRay XPU,
MoonRay XPU2 and MoonLightIPR: a cube 4 units from a camera focused at 1 unit with a wide aperture (f/0.5), so that its
edges are soft, nothing behind it. Stills: Render EXR for MoonRay XPU and XPU2 (still_<engine>.exr), and for MoonLightIPR
a Render with its Alpha buffer shown and saved (still_moonlightipr_alpha.png, with its beauty). Animations: Render
Animation of frames 1 and 2 with each engine (anim/<engine>.000001.exr...). How soft each alpha is is measured afterwards,
outside Modo. Writes test-results/alpha-dof/report.json."""
import json
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/alpha-dof'
shutil.rmtree(out, ignore_errors=True)
(out / 'anim').mkdir(parents=True, exist_ok=True)
result = {'runs': []}
held = {'to do': [('still', 'xpu'), ('still', 'xpu2'), ('still', 'moonlightipr'), ('anim', 'xpu'), ('anim', 'xpu2'), ('anim', 'moonlightipr')]}


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
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', 1), ('sizeY', 1), ('sizeZ', 1)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    render = scene.renderItem
    for name, value in (('first', 1), ('last', 2), ('step', 1), ('resX', 320), ('resY', 180)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    modo.LocatorSuperType(camera).position.set((0, 0, 4))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    for name, value in (('dof', True), ('fStop', 0.5), ('focusDist', 1.0)):
        camera.channel(name).set(value)
    result['camera'] = {name: camera.channel(name).get() for name in ('dof', 'fStop', 'focusDist')}
    scene.addItem('sunLight')
    lx.eval('moonray.page preview')
    later(3000, next_run)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def next_run():
    p = held['panel'] = panel()
    if not held['to do']:
        finish()
        return
    kind, engine = held['now'] = held['to do'].pop(0)
    if engine != 'moonlightipr':
        held.setdefault('renderer_kept', p.preferences.get('xpu2/renderer'))
        p.preferences.set('xpu2/renderer', engine)
    if p.ipr_mode.isChecked():
        p.ipr_mode.setChecked(False)
    p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr' if engine == 'moonlightipr' else 'moonray'))
    later(1500, still if kind == 'still' else animation)


def still():
    p = held['panel']
    engine = held['now'][1]
    if engine == 'moonlightipr':
        p.render_once()
    else:
        # As Render EXR does once its file is chosen (panel_tools.render_final).
        p.stop()
        p._output_view()
        scene = p._capture_output()
        p._submit(dict(scene, _xpu2_output=True), str(out / ('still_%s.exr' % engine)))
    held['tries'] = 0
    later(1500, wait_still)


def wait_still():
    p = held['panel']
    held['tries'] += 1
    busy = p._rendering or p._output_busy()
    if busy and held['tries'] < 1200:
        later(500, wait_still)
        return
    record = {'kind': 'still', 'engine': held['now'][1], 'status': p.status.text(), 'label': p.image_info.text(), 'seconds': held['tries'] * 0.5}
    result['runs'].append(record)
    if held['now'][1] == 'moonlightipr':
        p.preview.image.save(str(out / 'still_moonlightipr_beauty.png'))
        p.buffer.setCurrentIndex(p.buffer.findData('alpha'))
        later(3000, keep_alpha)
        return
    later(1500, next_run)


def keep_alpha():
    p = held['panel']
    p.preview.image.save(str(out / 'still_moonlightipr_alpha.png'))
    result['runs'][-1]['alpha shown'] = p.buffer.currentData()
    p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
    later(1500, next_run)


def animation():
    p = held['panel']
    engine = held['now'][1]
    from moonray_modo import output_dialog
    real = output_dialog.AnimationDialog

    class Answered(real):
        def exec_(self):
            self.folder.setText(str(out / 'anim'))
            self.prefix.setText(engine)
            self.first.setValue(1)
            self.last.setValue(2)
            self.motion.setChecked(False)
            self.engine.setCurrentIndex(self.engine.findData(engine))
            self.type.setCurrentIndex(self.type.findData(None))
            return True
    output_dialog.AnimationDialog = Answered
    try:
        p.render_animation()
    finally:
        output_dialog.AnimationDialog = real
    held['tries'] = 0
    later(1500, wait_animation)


def wait_animation():
    p = held['panel']
    held['tries'] += 1
    if p.sequence is not None and p.sequence.running and held['tries'] < 1200:
        later(500, wait_animation)
        return
    engine = held['now'][1]
    result['runs'].append({'kind': 'anim', 'engine': engine, 'status': p.status.text(),
                           'files': sorted(f.name for f in (out / 'anim').iterdir() if f.name.startswith(engine + '.'))})
    later(1500, next_run)


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    try:
        if 'renderer_kept' in held:
            panel().preferences.set('xpu2/renderer', held['renderer_kept'] or 'xpu2')
    except Exception:
        result.setdefault('errors', []).append('finish: ' + traceback.format_exc())
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


save()
# Scene edits here, at the probe's top level: Modo refuses them from a Qt timer.
guarded(setup)()
