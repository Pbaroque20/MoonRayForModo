"""Exercise real Qt renderer cancellation, replacement, image delivery and cleanup."""
from pathlib import Path
import json
import os
import shutil
import sys
modo = Path(r'C:\Program Files\Modo16.1v9\modo')
extra = modo / 'resrc/python3kit/extra64'
sys.path.insert(0, str(extra / 'Python/Scripts'))
dll_paths = [os.add_dll_directory(str(path)) for path in (modo, extra)]
from PySide2 import QtCore

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla
from moonray_modo.render import Renderer

glass_test = '--glass' in sys.argv
results = root / ('test-results/glass-live-process' if glass_test else 'test-results/live-process')
results.mkdir(parents=True, exist_ok=True)
app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
renderer = Renderer()
snapshot = {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 35, 'film_mm': 36},
            'materials': {'red': {'color': [.8, .06, .025], 'roughness': .5, 'metallic': 0}},
            'meshes': [{'name': 'Live process triangle', 'material': 'red',
                        'vertices': [[-1, -1, -3], [1, -1, -3], [0, 1, -3]], 'faces': [[0, 1, 2]]}],
            'lights': []}
report = {'passed': False, 'starts': 0, 'images': [], 'errors': []}
if glass_test:
    snapshot = json.loads((root/'test-results/glass/scene.json').read_text())


def end(error=None):
    if error:
        report['errors'].append(str(error))
    (results / 'renderer.log').write_text(renderer.log, encoding='utf-8')
    renderer.close()
    report['process_stopped'] = renderer.process.state() == QtCore.QProcess.NotRunning
    report['temporary_files_removed'] = not Path(renderer.directory.name).exists()
    report['passed'] = bool(report['starts'] == 2 and report['images'] == [2] and
                            report['process_stopped'] and report['temporary_files_removed'] and not report['errors'])
    (results / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    app.exit(0 if report['passed'] else 1)


def started():
    report['starts'] += 1
    if report['starts'] == 1:
        # The first native process is running. Replace it before image delivery.
        QtCore.QTimer.singleShot(20, replace)


def replace():
    if renderer.process.state() != QtCore.QProcess.Running:
        end('Initial renderer stopped before the cancellation test.')
        return
    snapshot['meshes'][0]['vertices'][2][0] = .5
    renderer.submit(snapshot, root / 'runtime/native-avx', 96, 96, 1, 1, 2)


def image_ready(path):
    report['images'].append(renderer.generation)
    shutil.copy2(path, results / 'replacement.png')


renderer.process.started.connect(started)
renderer.image_ready.connect(image_ready)
renderer.failed.connect(end)
renderer.finished.connect(lambda _: QtCore.QTimer.singleShot(0, end))
QtCore.QTimer.singleShot(60000, lambda: end('Native Qt lifecycle test timed out.'))
renderer.submit(snapshot, root / 'runtime/native-avx', 512, 512, 8, 1, 2)
code = app.exec_()
print(json.dumps(report, indent=2))
raise SystemExit(code)
