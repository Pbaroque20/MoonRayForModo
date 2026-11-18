# python
"""Isolated GUI test of Render Animation's engine: MoonRay (XPU) and MoonRay (XPU2), in a new scene with a cube (frames 1-2),
the preview set to MoonRay XPU in the test preferences (xpu2/renderer xpu), so that MoonRay (XPU2) has to ask for XPU2 by
name. Records, for each, whether the preview's session rendered the frames and with XPU2, what the window offers, and the
frames written; then the preference is put back. Writes test-results/animation-engine/report.json."""
import json
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/animation-engine'
shutil.rmtree(out, ignore_errors=True)
(out / 'frames').mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
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
    from moonray_modo import native, output_dialog, sequence_plan
    # MoonRay XPU renders the preview: MoonRay (XPU2) must ask for XPU2 by name.
    store = QtCore.QSettings('MoonRayForModo', native.settings_name())
    held['renderer_kept'] = store.value('xpu2/renderer')
    store.setValue('xpu2/renderer', 'xpu')
    result['preview xpu2'] = native.xpu2()
    result['xpu2 in the kit'] = native.xpu2_available()
    result['shaders'] = native.xpu2_shaders_state()[0]
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    dialog = output_dialog.AnimationDialog(panel.settings, panel, sequence_plan.window_values({}, panel._animation_scene()))
    result['window engines'] = [(dialog.engine.itemText(i), dialog.engine.itemData(i), dialog.engine.model().item(i).isEnabled()) for i in range(dialog.engine.count())]
    result['window opens with'] = dialog.engine.currentData()
    result['old choice opens as'] = output_dialog.AnimationDialog(panel.settings, panel, dict(sequence_plan.window_values({}, panel._animation_scene()), engine='moonray')).engine.currentData()
    panel.renderer.session.output.connect(said)
    run('xpu2')


def said(text):
    for line in text.splitlines():
        if 'XPU2' in line or 'xpu2' in line:
            held.setdefault('said', []).append(line[:200])


def run(engine):
    panel = held['panel']
    from moonray_modo import output_dialog
    real = output_dialog.AnimationDialog

    class Answered(real):
        def exec_(self):
            self.folder.setText(str(out / 'frames'))
            self.prefix.setText('by_' + engine)
            self.first.setValue(1)
            self.last.setValue(2)
            self.motion.setChecked(False)
            self.engine.setCurrentIndex(self.engine.findData(engine))
            result['runs'].setdefault(engine, {})['summary'] = self.summary.text()
            return True
    output_dialog.AnimationDialog = Answered
    try:
        panel.render_animation()
    finally:
        output_dialog.AnimationDialog = real
    held['said'] = []
    held['watched'] = {'session': set(), 'xpu2': set(), 'programs': set()}
    later(300, lambda: watch(engine, 240))


def watch(engine, tries):
    panel = held['panel']
    renderer = panel.renderer
    seen = held['watched']
    seen['session'].add(bool(renderer.using_session))
    seen['xpu2'].add(getattr(renderer.session, 'xpu2_active', None) if renderer.using_session else None)
    for process in (renderer.process, getattr(renderer.session, 'process', None)):
        if process is not None and process.state() != QtCore.QProcess.NotRunning:
            seen['programs'].add(pathlib.Path(process.program()).name)
    if panel.sequence is not None and panel.sequence.running and tries > 0:
        later(250, lambda: watch(engine, tries - 1))
        return
    record = result['runs'][engine]
    record.update({key: sorted(str(v) for v in value) for key, value in seen.items()})
    record['said'] = held['said'][:6]
    record['status'] = panel.status.text()
    record['files'] = sorted(p.name for p in (out / 'frames').iterdir() if p.name.startswith('by_' + engine))
    record['output_xpu2 after'] = getattr(renderer.session, 'output_xpu2', None)
    save()
    if engine == 'xpu2':
        later(1500, lambda: run('xpu'))
    else:
        finish()


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    try:
        from moonray_modo import native
        store = QtCore.QSettings('MoonRayForModo', native.settings_name())
        if held.get('renderer_kept') is None:
            store.remove('xpu2/renderer')
        else:
            store.setValue('xpu2/renderer', held['renderer_kept'])
        result['preference put back'] = store.value('xpu2/renderer')
    except Exception:
        result.setdefault('errors', []).append('finish: ' + traceback.format_exc())
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


save()
# Scene edits at the probe's top level: from a Qt timer Modo refuses them (addMesh: bad result).
guarded(setup)()
