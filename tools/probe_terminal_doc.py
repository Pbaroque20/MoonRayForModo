# python
"""Isolated GUI test: a picture of the MoonRay Terminal at work, for the docs (docs/images/terminal.png).

Opens the Terminal from the MoonRay menu's command, renders a small scene with MoonRay through a followed QProcess, as
the renderer starts moonray.exe, then has the plugin compose a stereo pair's red/cyan picture with oiiotool, and saves
a picture of the Terminal window alone once both have ended."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/terminal'
out.mkdir(parents=True, exist_ok=True)
pictures = root / 'test-results/doc-042'
result = {}

try:
    from PySide2 import QtCore, QtWidgets
    from moonray_modo import native, stereo, terminal
    runtime = native.find_runtime(str(pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'))
    lx.eval('moonray.terminal')
    window = terminal._window
    window.resize(1100, 620)
    process = QtCore.QProcess()
    terminal.watch(process, 'MoonRay')
    process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
    process.readyReadStandardOutput.connect(process.readAllStandardOutput)
    environment = QtCore.QProcessEnvironment()
    for key, value in native.environment(runtime).items():
        environment.insert(key, value)
    process.setProcessEnvironment(environment)
    process.setWorkingDirectory(str(out))
    process.setProgram(str(runtime / 'moonray.exe'))
    process.setArguments(native.arguments(str(pictures / 'crease_creased.rdla'), str(out / 'creased.exr'), 0, 'scalar'))
    process.start()
    while not process.waitForFinished(100):
        QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()
    stereo.composite(runtime, 'anaRedCyan', pictures / 'stereo_left.exr', pictures / 'stereo_right.exr', out / 'redcyan.exr')
    for _ in range(10):
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(100)
    window.refresh()
    window.blink = True
    window._show_prompt()
    QtWidgets.QApplication.processEvents()
    window.grab().save(str(out / 'terminal_doc.png'))
    result['ends'] = [(source, text) for _, _, kind, source, text in terminal.entries() if kind in ('end', 'fail')]
    result['busy'] = terminal.busy()
    across = window.text.horizontalScrollBar()
    result['sideways'] = {'value': across.value(), 'maximum': across.maximum()}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report_doc.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
