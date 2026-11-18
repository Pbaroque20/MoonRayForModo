# python
"""Isolated GUI test of MoonRay > Convert LXO to RDL: the window opened by its command, two scenes added, converted into
one folder as RDLB while Modo goes on, each scene's state and what was written, and a picture of the window.
Writes test-results/lxo-convert-window/."""
import json
import pathlib
import shutil
import traceback
import lx
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/lxo-convert-window'
shutil.rmtree(out, ignore_errors=True)
(out / 'rdl').mkdir(parents=True, exist_ok=True)
SCENES = [r'C:\Users\Raphael Tobar\Downloads\9Spheres_test_16_1\9Spheres_test_16_1_bundled.lxo',
          r'C:\Users\Raphael Tobar\Downloads\Oekovolt']
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
            quit_soon()
        save()
    return run


def open_window():
    lx.eval('moonray.lxo.convert')
    from moonray_modo import lxo_convert_window
    window = held['window'] = lxo_convert_window._window
    window.add(SCENES)
    window.beside.setCurrentIndex(window.beside.findData('folder'))
    window.folder.setText(str(out / 'rdl'))
    window.format.setCurrentIndex(window.format.findData('rdlb'))
    window.at_once.setValue(2)
    result['scenes listed'] = [window.scenes.topLevelItem(i).text(0) for i in range(window.scenes.topLevelItemCount())]
    window.start()
    result['started'] = window.status.text()
    held['began'] = QtCore.QTime.currentTime()
    QtCore.QTimer.singleShot(1000, guarded(watch))


def watch(tries=[300]):
    window = held['window']
    tries[0] -= 1
    if window.batch is not None and window.batch.running and tries[0] > 0:
        # Modo's own thread stays free meanwhile: this timer keeps its time.
        held.setdefault('ticks', 0)
        held['ticks'] += 1
        QtCore.QTimer.singleShot(1000, guarded(watch))
        return
    result['seconds'] = held['began'].secsTo(QtCore.QTime.currentTime())
    result['ticks while converting'] = held.get('ticks', 0)
    result['status'] = window.status.text()
    result['rows'] = [[window.scenes.topLevelItem(i).text(c) for c in range(3)] for i in range(window.scenes.topLevelItemCount())]
    result['files'] = sorted(p.name for p in (out / 'rdl').iterdir())
    window.scenes.setCurrentItem(window.scenes.topLevelItem(0))
    result['log of the first'] = window.log.toPlainText()[:600]
    window.grab().save(str(out / 'window.png'))
    quit_soon()


def quit_soon():
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


save()
QtCore.QTimer.singleShot(5000, guarded(open_window))
