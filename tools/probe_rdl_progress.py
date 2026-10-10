# python
"""Isolated GUI test: opening a large MoonRay scene says how far it has come.

The import dialog is given a scene (PROBE_RDL, a large one) and what it says under its report is written down every
two seconds until the scene is ready to import: opening the files with how much has been read, describing, receiving,
and working out what to import."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rdl-progress'
out.mkdir(parents=True, exist_ok=True)
result = {'said': []}
held = {'started': time.time()}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def watch():
    try:
        dialog = held['dialog']
        said = [round(time.time() - held['started']), dialog.stage.isVisible(), dialog.stage.text(), dialog.bar.maximum(), dialog.bar.value()]
        if not result['said'] or result['said'][-1][2:4] != said[2:4] or len(result['said']) % 10 == 0:
            result['said'].append(said)
        if 'picture' not in held and dialog.bar.maximum() == 1000 and dialog.bar.value() > 100:
            dialog.grab().save(str(out / 'opening.png'))
            held['picture'] = True
        running = dialog.process.state() != QtCore.QProcess.NotRunning
        if running and time.time() - held['started'] < 840:
            QtCore.QTimer.singleShot(2000, watch)
            return
        result['ready'] = dialog.import_button.isEnabled()
        result['report'] = dialog.report.toPlainText()[:300]
        result['hidden_after'] = not dialog.stage.isVisible() and not dialog.bar.isVisible()
        result['seconds'] = round(time.time() - held['started'])
        dialog.close()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


def begin():
    try:
        from moonray_modo import rdl_import_dialog
        settings = QtCore.QSettings('MoonRayForModo', 'NativePreview')
        held['runtime'] = settings.value('runtime', '')
        settings.setValue('runtime', str(root / 'runtime/steady-0350-pool'))
        rdl_import_dialog.show(os.environ['PROBE_RDL'])
        held['dialog'] = rdl_import_dialog._dialog
        # The window's choices are shared with the user's own Modo: put back what was stored, now the reader has started.
        settings.setValue('runtime', held['runtime'])
        held['started'] = time.time()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    save()
    QtCore.QTimer.singleShot(1000, watch)


QtCore.QTimer.singleShot(3000, begin)
