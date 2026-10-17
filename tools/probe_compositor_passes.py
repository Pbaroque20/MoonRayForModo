# python
"""Isolated GUI test: the compositor built from render passes and from light groups.

Two balls under Modo's sun, the sun labelled "sun" in the scene's light controls. The compositor's editor is opened,
Build > From Light Passes pressed: the outputs it adds to the scene and the graph it lays out are noted and the editor
saved as a picture. A MoonRay render follows, and its Composite buffer is compared with its beauty. Then Build > From
Light Groups (the question whether to replace the graph answered yes), a render, and the same comparison."""
import json
import pathlib
import subprocess
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-passes-gui'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def compare():
    """The Composite buffer against the beauty, by the image tool."""
    from moonray_modo import native
    files = (panel_widget().renderer.buffers.frame or {}).get('files', {})
    if 'composite' not in files or 'beauty' not in files:
        return 'no composite: %s' % sorted(files)
    import shutil
    kept = out / ('buffers_%d' % len(result['steps']))
    kept.mkdir(exist_ok=True)
    for key, path in files.items():
        if pathlib.Path(path).is_file():
            shutil.copyfile(str(path), str(kept / (key + pathlib.Path(path).suffix)))
    done = subprocess.run([str(runtime / 'oiiotool.exe'), str(files['beauty']), '--ch', '0,1,2', str(files['composite']), '--ch', '0,1,2', '--diff'],
                          env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return [l.strip() for l in done.stdout.decode(errors='replace').splitlines() if 'Mean' in l or l.strip() in ('PASS', 'FAILURE', 'WARNING')]


def note(name):
    panel, editor = panel_widget(), held.get('editor')
    stored = panel._settings_values_stored()
    graph = stored.get('compositor') or {}
    result['steps'].append({'step': name, 'outputs': [entry['name'] for entry in stored.get('custom_aovs', [])],
                            'nodes': sorted(n['type'] for n in graph.get('nodes', {}).values()),
                            'buffers': sorted({n['parameters'].get('buffer') for n in graph.get('nodes', {}).values() if n['type'] == 'input'}),
                            'info': editor.info.text() if editor else None})
    if editor:
        editor.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(3000)
def open_and_build_passes():
    panel = panel_widget()
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    sun = next(item for item in modo.Scene().items('sunLight'))
    production = dict(panel._settings_values().get('production') or {})
    production['lights'] = {sun.id: {'label': 'sun'}}
    result['stored_production'] = panel._store(production=production)
    panel.open_compositor()
    from moonray_modo import compositor_editor
    held['editor'] = compositor_editor._open.get('editor')
    # The chooser Build opens: shown, saved as a picture, and three passes picked from it with the Remainder.
    def pick(parent, title, intro, options, ticked):
        dialog = compositor_editor.PassChooser(parent, title, intro, options, ticked)
        dialog.show()
        QtWidgets.QApplication.processEvents()
        dialog.grab().save(str(out / '00_chooser.png'))
        picked = [i for i, (label, name, expression) in enumerate(options) if label in ('Emission', 'Direct diffuse', 'Direct glossy')]
        result['chooser'] = {'offered': [label for label, name, expression in options], 'ticked': sorted(ticked), 'picked': picked}
        dialog.close()
        return picked, True
    compositor_editor.choose = pick
    held['editor'].build('passes')
    held['editor'].frame(everything=True)


@step(90000)
def render_passes():
    note('built_from_passes')
    panel_widget().start.click()


@step(3000)
def compare_passes():
    result['passes_composite_vs_beauty'] = compare()
    note('passes_rendered')
    # Yes to replacing the graph there.
    QtWidgets.QMessageBox.question = staticmethod(lambda *args, **kw: QtWidgets.QMessageBox.Ok)
    from moonray_modo import compositor_editor
    compositor_editor.choose = lambda parent, title, intro, options, ticked: (sorted(ticked), True)
    held['editor'].build('groups')
    held['editor'].frame(everything=True)


@step(90000)
def render_groups():
    note('built_from_groups')
    panel_widget().start.click()


@step(1000)
def finish():
    result['groups_composite_vs_beauty'] = compare()
    note('groups_rendered')
    held['editor'].close()
    panel_widget().stop()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
