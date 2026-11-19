# python
"""Does Modo quit cleanly after a working session with the kit: the preview open, MoonLightIPR in realtime for a few
seconds, a MoonRay light and a material made? The exit code is the answer (1 a clean scripted quit, 3221225477 a crash);
quit-release.json says what quit_release held and whether it let go before Modo finalized Python.
PROBE_QUIT_TAG names the run's files."""
import json
import os
import pathlib
import lx
from PySide2 import QtCore

tag = os.environ.get('PROBE_QUIT_TAG', 'run')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\quit-release')
out.mkdir(parents=True, exist_ok=True)
report = {'tag': tag}


def note(**values):
    report.update(values)
    (out / ('quit-release-%s.json' % tag)).write_text(json.dumps(report, indent=2))


try:
    from moonray_modo import quit_release
    note(kit_has_quit_release=True, hooked_at_load=bool(quit_release._hooked[0]), listeners_at_load=len(quit_release._LISTENERS),
         forgets_at_load=len(quit_release._FORGET))
except ImportError:
    quit_release = None
    note(kit_has_quit_release=False)

lx.eval('item.create mesh')
lx.eval('tool.set prim.cube on'); lx.eval('tool.apply'); lx.eval('tool.set prim.cube off')
if not os.environ.get('PROBE_QUIT_NOPANEL'):
    lx.eval('moonray.open')


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def realtime():
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    if not p.rt.isChecked():
        p.rt.click()
    note(realtime=p.rt.isChecked())


def edit():
    for command in ('moonray.entity.add SphereLight', 'select.drop item', 'select.item Camera set', 'select.drop item'):
        try:
            lx.eval(command)
        except Exception as exc:
            note(**{'failed_' + command.split()[0]: repr(exc)})


_plain = []


def library_closed():
    # The asset library opened and closed again, as an artist does: its window is kept, hidden.
    lx.eval('moonray.library')
    from moonray_modo import asset_browser
    QtCore.QTimer.singleShot(1500, asset_browser._dialog.close)


def plain_window():
    # A bare Qt window of Python's, none of the kit's code in it.
    from PySide2 import QtWidgets
    window = QtWidgets.QWidget()
    window.setWindowTitle('probe')
    window.resize(300, 200)
    window.show(); window.raise_(); window.activateWindow()
    _plain.append(window)
    return window


def windows():
    # PROBE_QUIT_EXTRA: the kit's other windows too, the way an artist leaves them: a graph editor opened and closed,
    # another left open, Rhizome, Convert LXO to RDL and the asset library left open.
    import modo
    from moonray_modo import node_editor
    materials = [item for item in modo.Scene().items('advancedMaterial')]
    note(materials=len(materials))
    chosen = os.environ.get('PROBE_QUIT_EXTRA', '1')
    for step, run in (('graph_closed', lambda: node_editor.open_editor(materials[0]).close()),
                      ('graph_open', lambda: node_editor.open_editor(materials[0])),
                      ('rhizome', lambda: lx.eval('moonray.rhizome')),
                      ('convert', lambda: lx.eval('moonray.lxo.convert')),
                      ('library', lambda: lx.eval('moonray.library')),
                      ('library_closed', library_closed),
                      ('plain', plain_window), ('plain_closed', lambda: plain_window().close())):
        if chosen != '1' and step not in chosen.split(','):
            continue
        try:
            run()
            note(**{step: True})
        except Exception as exc:
            note(**{step: repr(exc)[:200]})


def wrappers():
    """Qt objects of Python's still standing, by class. Read from the wrappers Python holds only: asking a Qt object of
    Modo's for anything (its parent, the list of windows) makes Python wrap it, and Modo crashed as it quit for that alone
    (PySide marks each such object, and the mark calls into Python when Modo frees the object at the very end)."""
    try:
        import shiboken2
        listed = shiboken2.getAllValidWrappers()
    except Exception as exc:
        return {'error': repr(exc)[:200]}
    held = {}
    for wrapper in listed:
        kind = type(wrapper).__module__ + '.' + type(wrapper).__name__
        held[kind] = held.get(kind, 0) + 1
    return dict(sorted(held.items(), key=lambda pair: -pair[1])[:60])


def modo_objects():
    """Qt objects Modo made that Python holds a wrapper of, by Qt class and object name (nothing more is asked)."""
    try:
        import shiboken2
        from PySide2 import QtCore
        listed = shiboken2.getAllValidWrappers()
    except Exception as exc:
        return [repr(exc)[:200]]
    return ['%s "%s"' % (w.metaObject().className(), w.objectName()) for w in listed
            if isinstance(w, QtCore.QObject) and not shiboken2.createdByPython(w)]


def at_exit():
    # Python's exit, run before the kit's own (atexit runs the last registered first): the kit's windows standing then,
    # found among the wrappers Python holds.
    try:
        import shiboken2
        from PySide2 import QtWidgets
        standing = [type(w).__module__ + '.' + type(w).__name__ for w in shiboken2.getAllValidWrappers()
                    if isinstance(w, QtWidgets.QWidget) and (type(w).__module__ or '').startswith('moonray_') and w.isWindow()]
    except Exception as exc:
        standing = repr(exc)[:200]
    note(atexit_ran=True, kit_windows_at_exit=standing, modo_objects_at_exit=modo_objects())


def last_look():
    # Run on aboutToQuit after the kit's own handlers were connected: what quit_release let go of.
    import atexit
    atexit.register(at_exit)
    note(wrappers_at_quit=wrappers())
    if quit_release is not None:
        note(released=bool(quit_release.released[0]), listeners_left=len(quit_release._LISTENERS),
             hooked=bool(quit_release._hooked[0]))
    else:
        note(released=None)


def quit_now():
    if not os.environ.get('PROBE_QUIT_NOPANEL'):
        p = panel()
        if p.rt.isChecked():
            p.rt.click()
    QtCore.QCoreApplication.instance().aboutToQuit.connect(last_look)
    note(quitting=True)
    lx.eval('!app.quit')


if not os.environ.get('PROBE_QUIT_NOPANEL'):
    QtCore.QTimer.singleShot(1500, realtime)
    QtCore.QTimer.singleShot(6000, edit)
if os.environ.get('PROBE_QUIT_EXTRA'):
    QtCore.QTimer.singleShot(8000, windows)
    QtCore.QTimer.singleShot(16000, quit_now)
else:
    QtCore.QTimer.singleShot(11000, quit_now)
