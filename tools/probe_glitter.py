# python
"""Isolated GUI test: glitter as a user would turn it on, to find where it crashes.

A sphere is given DwaBaseMaterial; Show Glitter and Glitter are set through the material's own form commands, as the
form sets them. The preview then renders with MoonRay, then with MoonLightIPR, then the graph editor is opened on the
material (its MoonRay Widget renders it). Each step is written to test-results/glitter/gui.json as it is reached, so a
crash shows as the last step reached; the preview window is pictured after each render."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/glitter'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'steps': []}
held = {}


def save():
    (out / 'gui.json').write_text(json.dumps(result, indent=1, default=str))


def note(step, **found):
    result['steps'].append(dict(step=step, **found))
    save()


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def picture(name):
    try:
        panel_widget().window().grab().save(str(out / ('gui_%s.png' % name)))
    except Exception:
        pass


def render(engine):
    def step():
        panel = panel_widget()
        if 'runtime' not in held:
            held['runtime'] = panel.preferences.store.value('runtime')
            panel.preferences.set('runtime', str(runtime))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
        note('render ' + engine + ' started')
        panel.start.click()
    return step


def rendered(engine):
    def step():
        panel = panel_widget()
        note('render ' + engine + ' after waiting', status=panel.status.text(), notices=panel.warnings.toPlainText()[:600])
        if engine == 'moonray':
            # The preview session's own scene files, kept for MoonRay to be run on outside Modo.
            import shutil
            kept = out / 'session'
            shutil.rmtree(kept, ignore_errors=True)
            try:
                shutil.copytree(str(panel.renderer.session.root), str(kept))
                note('session files kept', files=sorted(path.name for path in kept.iterdir()))
            except Exception:
                note('session files not kept', error=traceback.format_exc())
        picture(engine)
        try:
            panel.stop()
        except Exception:
            pass
    return step


def graph_editor():
    note('graph editor opening')
    from moonray_modo.node_editor import open_editor
    held['editor'] = open_editor(modo.Scene().item(held['material']))


def graph_editor_after():
    note('graph editor open after waiting')
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('gui_graph_%d.png' % index)))


def run(steps, index=0):
    if index >= len(steps):
        try:
            panel = panel_widget()
            if held.get('runtime') is None:
                panel.preferences.store.remove('runtime')
            else:
                panel.preferences.store.setValue('runtime', held['runtime'])
        except Exception:
            pass
        note('finished')
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        note('error', error=traceback.format_exc())
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    from moonray_modo import shader_library, properties
    scene = modo.Scene()
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    material = scene.selected[0]
    held['material'] = material.id
    names = [''] + sorted(shader_library.catalog())
    i = names.index('DwaBaseMaterial')
    keys = sorted(shader_library.catalog()['DwaBaseMaterial']['attributes'])
    for key, value in (('show_glitter', 'true'), ('glitter', '1.0')):
        command = 'moonray.material.attr%d_%d' % (i, keys.index(key))
        lx.eval('%s %s' % (command, value))
    note('glitter set', stored=properties.read(material).get('native_parameters'))
    # The scene as the plugin writes it, for MoonRay to be run on outside Modo (tools/check_glitter.py --scene).
    import os
    if os.environ.get('MOONRAY_PROBE_EXPORT'):
        from moonray_modo import host, rdla
        (out / 'gui_scene.rdla').write_text(rdla.scene_text(host.snapshot(), 320, 180, 2, 0.15, str(out / 'gui_scene.exr')), encoding='utf-8')
    lx.eval('moonray.render.samples 2')
    # Every scene the preview hands its MoonRay session, kept as text (test-results/glitter/sent_<id>_<kind>.rdla).
    from moonray_modo import persistent
    original = persistent.Session._write_scene

    def kept_write(self, request, suffix, text, payload=None):
        try:
            body = text if text is not None else (payload or b'').decode('utf-8', errors='replace')
            (out / ('sent_%s_%s.rdla' % (request['id'], suffix))).write_text(body, encoding='utf-8')
        except Exception:
            pass
        return original(self, request, suffix, text, payload)
    persistent.Session._write_scene = kept_write
    for old in out.glob('sent_*.rdla'):
        old.unlink()
    lx.eval('moonray.open')
    note('preview opened')
except Exception:
    note('setup error', error=traceback.format_exc())
QtCore.QTimer.singleShot(6000, lambda: run([(render('moonray'), 30000), (rendered('moonray'), 1000),
                                            (render('moonlightipr'), 15000), (rendered('moonlightipr'), 1000),
                                            (graph_editor, 20000), (graph_editor_after, 1000)]))
