# python
"""Isolated GUI test: the MoonRay Terminal from the MoonRay menu's command, following MoonRay as the plugin starts it.

Opens the Terminal with moonray.terminal, starts MoonRay's help through a followed QProcess, as the renderer starts
moonray.exe, and the scene reader's version through subprocess from the plugin's own code, waits for both to end,
and saves a picture of the Terminal window alone (test-results/terminal/terminal.png) and its text."""
import json
import pathlib
import traceback
import lx

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/terminal'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    from PySide2 import QtCore, QtWidgets
    from moonray_modo import native, terminal
    lx.eval('moonray.terminal')
    window = terminal._window
    result['opened'] = window is not None and window.isVisible()
    runtime = native.find_runtime(str(pathlib.Path.home() / "AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime"))
    result['runtime'] = str(runtime)
    process = QtCore.QProcess()
    terminal.watch(process, 'MoonRay')
    process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
    process.readyReadStandardOutput.connect(process.readAllStandardOutput)
    environment = QtCore.QProcessEnvironment()
    for key, value in native.environment(runtime).items():
        environment.insert(key, value)
    process.setProcessEnvironment(environment)
    process.setProgram(str(runtime / 'moonray.exe'))
    process.setArguments(['-help'])
    process.start()
    process.waitForFinished(60000)
    QtWidgets.QApplication.processEvents()
    # A program the plugin starts through Python's subprocess, from its own module.
    from moonray_modo import stereo
    try:
        stereo.composite(runtime, 'anaRedCyan', out / 'missing_left.exr', out / 'missing_right.exr', out / 'none.exr')
    except ValueError as exc:
        result['composite'] = str(exc)[:120]
    for _ in range(12):
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(100)
    window.refresh()
    QtWidgets.QApplication.processEvents()
    entries = terminal.entries()
    result['commands'] = [(source, text[:160]) for _, _, kind, source, text in entries if kind == 'command']
    result['ends'] = [(source, text) for _, _, kind, source, text in entries if kind in ('end', 'fail')]
    result['lines'] = len(entries)
    result['prompt'] = {'busy': terminal.busy(), 'running': {str(k): v[0] for k, v in terminal._running.items()}, 'text': window.prompt.text(),
                        'visible': window.prompt.isVisible(), 'height': window.prompt.height()}
    window.resize(1000, 560)
    QtWidgets.QApplication.processEvents()
    window.blink = True
    window._show_prompt()
    QtWidgets.QApplication.processEvents()
    window.grab().save(str(out / 'terminal.png'))
    (out / 'terminal.txt').write_text(window.lines(), encoding='utf-8')
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
