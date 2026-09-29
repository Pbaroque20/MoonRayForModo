# python
"""Real installed-kit render/edit test; run inside graphical Modo 16.1v9.

Creates a separate unsaved test scene and leaves its preview open for inspection.
Success requires two different rendered images, with the second requested by the
panel's live scene polling after an actual Modo mesh transform edit.
"""
import hashlib
import json
from pathlib import Path
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

ROOT = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
RESULTS = ROOT / 'test-results/live-preview'
RESULTS.mkdir(parents=True, exist_ok=True)
report = {'app_version': lx.eval('query platformservice appversion ?'),
          'passed': False, 'images': []}
state = {'panel': None, 'mesh': None, 'phase': 0, 'done': False}


def save_report():
    (RESULTS / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


def fail(message):
    if state['done']:
        return
    state['done'] = True
    report['error'] = str(message)
    if state['panel'] is not None:
        panel = state['panel']
        (RESULTS / 'renderer.log').write_text(panel.renderer.log, encoding='utf-8')
        panel.live.setChecked(False)
        panel.stop()
    save_report()


def image_ready(path):
    if state['done']:
        return
    try:
        phase = state['phase']
        target = RESULTS / ('before.png' if phase == 0 else 'after.png')
        shutil.copy2(path, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        report['images'].append({'path': str(target), 'sha256': digest,
                                 'generation': state['panel'].renderer.generation})
        if phase == 0:
            state['phase'] = 1
            # Wait until the first QProcess completion handler has returned.
            QtCore.QTimer.singleShot(500, edit_mesh)
        else:
            if digest == report['images'][0]['sha256']:
                raise RuntimeError('The live edit did not change the rendered image.')
            panel = state['panel']
            report['visible'] = panel.isVisible()
            report['runtime'] = panel.runtime.text()
            report['passed'] = bool(report['visible'] and report['app_version'] == 1619)
            (RESULTS / 'renderer.log').write_text(panel.renderer.log, encoding='utf-8')
            state['done'] = True
            save_report()
    except Exception:
        fail(traceback.format_exc())


def edit_mesh():
    try:
        # Timer callbacks are outside a Modo undo transaction. A native command
        # establishes the edit context that direct channel writes require.
        lx.eval('select.item {%s} set' % state['mesh'].id)
        lx.eval('transform.channel pos.X 0.65')
        report['mesh_edit_applied'] = True
        save_report()
        # Deliberately do not call render_once; the live timer must detect this.
    except Exception:
        fail(traceback.format_exc())


def start():
    try:
        from moonray_modo.panel import Panel
        panels = [w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel) and w.isVisible()]
        if not panels:
            raise RuntimeError('The installed MoonRay preview did not open.')
        panel = state['panel'] = panels[0]
        panel.runtime.setText(str(ROOT / 'runtime/native-avx'))
        panel.size.setCurrentIndex(3)
        panel.samples.setValue(1)
        panel.environment.setValue(1)
        panel.threads.setValue(2)
        panel.renderer.failed.connect(fail)
        panel.renderer.image_ready.connect(image_ready)
        panel.live.setChecked(True)
        QtCore.QTimer.singleShot(180000, lambda: fail('Live preview test timed out.'))
    except Exception:
        fail(traceback.format_exc())


try:
    if report['app_version'] != 1619 or lx.service.Platform().IsHeadless():
        raise RuntimeError('This test requires graphical Modo 16.1v9.')
    lx.eval('scene.new')
    scene = modo.Scene()
    camera = scene.renderCamera
    camera.position.set((0, 0, 0))
    camera.rotation.set((0, 0, 0))
    camera.channel('focalLen').set(0.035)
    scene.renderItem.channel('resX').set(96)
    scene.renderItem.channel('resY').set(96)
    mesh = state['mesh'] = scene.addMesh('MoonRay live preview test')
    geometry = mesh.geometry
    for position in ((-1, -1, -3), (1, -1, -3), (0, 1, -3)):
        geometry.vertices.new(position)
    geometry.polygons.new((0, 1, 2))
    geometry.setMeshEdits()
    from moonray_modo.panel import Panel
    if not any(isinstance(w, Panel) and w.isVisible() for w in QtWidgets.QApplication.allWidgets()):
        lx.eval('moonray.open')
    QtCore.QTimer.singleShot(2000, start)
    save_report()
except Exception:
    fail(traceback.format_exc())
