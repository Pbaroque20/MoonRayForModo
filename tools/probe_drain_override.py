# python
"""Isolated GUI test: the MoonRay Source Override "Stop finishes the tiles in hand".

A ball is rendered with MoonRay at many samples and stopped part way by hand, twice: with the switch on, the plugin
asks MoonRay to finish the tiles in hand (the renderer says it is draining); with it off, it does not, and stops as
MoonRay's own stop does. What the renderer did and the status it ended on are noted each time."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/drain-override'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'runs': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def switch(on):
    from moonray_modo import native
    QtCore.QSettings('MoonRayForModo', native.settings_name()).setValue('drain_tiles', on)
    return native.drain_tiles()


def run(steps, index=0):
    if index >= len(steps):
        switch(True)
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


def start(on):
    def go():
        panel = panel_widget()
        panel.preferences.set('runtime', str(runtime))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        result['runs'].append({'switch': on, 'read_back': switch(on)})
        panel.start.click()
    return go


def stop():
    panel = panel_widget()
    panel.stop()
    QtWidgets.QApplication.processEvents()
    result['runs'][-1]['draining_after_stop'] = bool(getattr(panel.renderer, 'draining', False))


def settle():
    panel = panel_widget()
    result['runs'][-1]['status_after'] = panel.status.text()
    result['runs'][-1]['picture_kept'] = not panel.preview.image.isNull()
    save()


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 32')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([(start(True), 12000), (stop, 15000), (settle, 1000),
                                            (start(False), 12000), (stop, 15000), (settle, 1000)]))
