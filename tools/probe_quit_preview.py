# python
"""Does Modo quit cleanly with the preview window open? PROBE_QUIT_STEP: 'open' opens it and quits; 'rendered' renders
once (MoonRay) first. The exit code is the answer (1 is a clean scripted quit, 3221225477 a crash)."""
import os
import time
import lx
from PySide2 import QtCore, QtWidgets

step = os.environ.get('PROBE_QUIT_STEP', 'open')
import faulthandler
import pathlib
_out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\quit-preview')
_out.mkdir(parents=True, exist_ok=True)
_fault = open(str(_out / ('fault-%s.txt' % step)), 'w')
faulthandler.enable(file=_fault, all_threads=True)
lx.eval('item.create mesh')
lx.eval('tool.set prim.cube on'); lx.eval('tool.apply'); lx.eval('tool.set prim.cube off')
if os.environ.get('PROBE_TRACE'):
    # Which of the scene listener's callbacks fire, recorded in order.
    from moonray_modo import changes as _changes
    _fired = []
    for _name in [n for n in dir(_changes.Changes) if n.startswith('sil_')]:
        _orig = getattr(_changes.Changes, _name)

        def _wrap(self, *args, _orig=_orig, _name=_name):
            _fired.append(_name)
            (_out / 'fired.txt').write_text('\n'.join(_fired))
            return _orig(self, *args)
        setattr(_changes.Changes, _name, _wrap)
lx.eval('moonray.open')


def panel():
    # The kit's own list: looking through QApplication.allWidgets() is itself what made Modo crash as it quit.
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def go():
    if step == 'submit-stop':
        p = panel()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        p.render_once()
        QtCore.QTimer.singleShot(300, lambda: panel().stop())
        QtCore.QTimer.singleShot(6000, lambda: lx.eval('!app.quit'))
        return
    if step in ('capture', 'capture-moonray'):
        p = panel()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr' if step == 'capture' else 'moonray'))
        try:
            p._capture_preview()
        except Exception as exc:
            (_out / 'capture.txt').write_text(repr(exc))
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step == 'event':
        lx.eval('item.create locator')
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step == 'seq':
        # PROBE_SEQ: comma-separated pieces run in order: color, stored, complete, buffer.
        for piece in os.environ.get('PROBE_SEQ', '').split(','):
            try:
                if piece == 'color':
                    from moonray_modo import modo_color
                    modo_color.refresh()
                elif piece == 'stored':
                    from moonray_modo import properties
                    properties.scene_settings()
                elif piece == 'complete':
                    from moonray_modo import scene_settings, properties
                    scene_settings.complete(properties.scene_settings())
                elif piece == 'buffer':
                    panel().buffer.currentData()
            except Exception as exc:
                (_out / 'capture.txt').write_text(repr(exc))
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step in ('color', 'stored', 'complete'):
        try:
            if step == 'complete':
                from moonray_modo import scene_settings, properties
                scene_settings.complete(properties.scene_settings())
            elif step == 'color':
                from moonray_modo import modo_color
                modo_color.refresh()
            else:
                from moonray_modo import properties
                properties.scene_settings()
        except Exception as exc:
            (_out / 'capture.txt').write_text(repr(exc))
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step == 'allwidgets':
        len(QtWidgets.QApplication.allWidgets())
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step == 'wait':
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step in ('settings', 'snap'):
        p = panel()
        try:
            if step == 'settings':
                p._settings_values()
            else:
                from moonray_modo import host
                host.snapshot()
        except Exception as exc:
            (_out / 'capture.txt').write_text(repr(exc))
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step == 'notify':
        from moonray_modo import property_notifications
        property_notifications.notify()
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
        return
    if step in ('rendered', 'ipr'):
        p = panel()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray' if step == 'rendered' else 'moonlightipr'))
        p.render_once()
        began = time.monotonic()

        def wait():
            if getattr(panel(), '_rendering', False) and time.monotonic() - began < 120:
                QtCore.QTimer.singleShot(1000, wait); return
            # PROBE_CLEAN: what is undone before quitting, to find what a render leaves that crashes Modo's exit.
            clean = os.environ.get('PROBE_CLEAN', '')
            if 'dispose' in clean:
                import time as _t, traceback as _tb
                start = _t.monotonic()
                try:
                    panel().dispose()
                    (_out / 'dispose.txt').write_text('ok %.2f s' % (_t.monotonic() - start))
                except Exception:
                    (_out / 'dispose.txt').write_text(_tb.format_exc())
            if 'clients' in clean:
                from moonray_modo import property_notifications
                property_notifications.Notifier.clients.clear()
            if 'watchers' in clean:
                from moonray_modo import property_notifications
                property_notifications.watchers.clear()
            if 'gc' in clean:
                import gc
                gc.collect()
            QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))
        QtCore.QTimer.singleShot(3000, wait)
    else:
        QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(6000, go)
