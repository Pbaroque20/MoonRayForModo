"""Check the private kit's preview session with XPU2 chosen, headless, with Modo's Python and Qt (offscreen):

    <Modo python> -S check_xpu2_session_qt.py <scene.rdla> <output.json> [refused-scene.rdla]

Uses the test preview settings (MOONRAY_MODO_PREFERENCES=TestPreview), never the user's, and puts back what it set.
A scene XPU2 renders should come back from XPU2 ("XPU2 preview session" in the log, pictures, ready); a scene it
refuses should come back from MoonRay, with XPU2's reason in the status."""
import json
import os
import sys
import time
from pathlib import Path

os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
KIT = Path(__file__).resolve().parent / 'MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from PySide2 import QtCore, QtWidgets  # noqa: E402

app = QtWidgets.QApplication([])
from moonray_modo import native  # noqa: E402
from moonray_modo.persistent import Session  # noqa: E402

store = QtCore.QSettings('MoonRayForModo', 'TestPreview')
before = store.value('xpu2/renderer', None)
store.setValue('xpu2/renderer', 'xpu2')
store.sync()


def run(scene, seconds=120):
    record = {'status': [], 'ready': [], 'failed': [], 'pictures': 0, 'log': ''}
    session = Session()
    session.status.connect(lambda s: record['status'].append(s))
    session.ready.connect(lambda g: record['ready'].append(g))
    session.failed.connect(lambda s: record['failed'].append(s))
    session.output.connect(lambda s: record.__setitem__('log', record['log'] + s))

    def picture(packet):
        record['pictures'] += 1
    session.memory_image.connect(picture)
    runtime = Path(native.default_runtime())
    session.submit(Path(scene).read_text(encoding='utf-8'), runtime, 4, 'xpu', 1, 32)
    end = time.monotonic() + seconds
    while time.monotonic() < end and not record['ready'] and not record['failed']:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)
    record['xpu2_active_at_end'] = getattr(session, 'xpu2_active', None)
    record['refused'] = getattr(session, 'xpu2_refused', None)
    session.close()
    record['log'] = record['log'][-3000:]
    return record


try:
    results = {'accepted': run(sys.argv[1])}
    if len(sys.argv) > 3:
        results['refused'] = run(sys.argv[3])
finally:
    if before is None:
        store.remove('xpu2/renderer')
    else:
        store.setValue('xpu2/renderer', before)
    store.sync()
Path(sys.argv[2]).write_text(json.dumps(results, indent=2), encoding='utf-8')
for name, r in results.items():
    print(name, 'ready', r['ready'], 'failed', r['failed'], 'pictures', r['pictures'], 'refused', r['refused'],
          'xpu2 at end', r['xpu2_active_at_end'])
    print('  status:', r['status'][-3:])
