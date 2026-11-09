# python
"""GUI: edits that change nothing must not start realtime again. The bump-node scene (test-results/bump-node/
bump_node.lxo: two MoonShine spheres and a floor) followed in realtime (PROBE_ENGINE: moonlightipr, or xpu2 for RT with
MoonRay XPU2); then, a few seconds apart, edits that change nothing and, after each kind, one that does (the control):
a MoonRay material form field entered at its value; a stored 0.30000000000000004 entered as the 0.3 the field shows;
graph editor fields entered at the value stored and at the start value shown; a Modo material channel set to its value.
Every scene sent to the renderer is written down with the phase it came in, and every refresh of the graph editor's
own preview. Writes test-results/noop-edits/<engine>.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
engine_name = os.environ.get('PROBE_ENGINE') or 'moonlightipr'
out = root / 'test-results/noop-edits'
out.mkdir(parents=True, exist_ok=True)
result = {'engine': engine_name, 'phases': [], 'submits': [], 'graph_previews': [], 'expect': {}}
held = {'began': time.time(), 'phase': 'opening'}


def save():
    (out / (engine_name + '.json')).write_text(json.dumps(result, indent=1, default=str))


def at():
    return round(time.time() - held['began'], 2)


def phase(name, restart_expected):
    held['phase'] = name
    result['phases'].append((at(), name))
    result['expect'][name] = restart_expected
    save()


def named(name):
    """The scene's two MoonShine materials ('Bumped Shine', the one whose graph has a Bump node, and 'Smooth Shine'),
    or any other item by its name."""
    if name in ('Bumped Shine', 'Smooth Shine'):
        from moonray_modo import properties
        for item in modo.Scene().iterItems():
            if item.type == 'material.moonrayMoonShine':
                bumped = 'bump' in ((properties.read(item).get('node_graph') or {}).get('nodes') or {})
                if bumped == (name == 'Bumped Shine'):
                    return item
    return next(i for i in modo.Scene().iterItems() if i.name == name)


def workspace():
    return next(i for i in modo.Scene().iterItems() if i.name == 'Probe Workspace')


def schematic_create():
    lx.eval('schematic.createWorkspace "Probe Workspace"')


def schematic_add():
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == 'Smooth')
    lx.eval('schematic.addItem item:{%s} group:{%s} posX:100 posY:100' % (mesh.id, workspace().id))
    result['schematic_items'] = [(i.name, i.type) for i in modo.Scene().iterItems() if i.type in ('schmNode', 'assembly')]


def schematic_move():
    node = next(i for i in modo.Scene().iterItems() if i.type == 'schmNode')
    lx.eval('schematic.nodePosition node:{%s} x:300 y:200' % node.id)


def schematic_remove():
    mesh = next(i for i in modo.Scene().items('mesh') if i.name == 'Smooth')
    lx.eval('schematic.remItem item:{%s} group:{%s}' % (mesh.id, workspace().id))


def log_notices(changes):
    """Every notice Modo gives the realtime listener, by phase: its name, and the item's type or the graph's name."""
    import lx as host
    scenes = host.service.Scene()

    def describe(args):
        said = []
        for arg in args[:3]:
            try:
                said.append(scenes.ItemTypeName(host.object.Item(arg).Type()))
                continue
            except Exception:
                pass
            try:
                said.append('graph:' + host.object.SceneGraph(arg).Name())
            except Exception:
                pass
        return said
    for name in [n for n in dir(changes) if n.startswith('sil_')]:
        original = getattr(changes, name)
        if not callable(original):
            continue

        def logged(*args, _name=name, _original=original):
            was = changes.full
            answer = _original(*args)
            try:
                said = describe(args)
                if _name.startswith('sil_Link'):
                    try:
                        said.insert(0, 'graph=' + host.object.SceneGraph(args[0]).Name())
                    except Exception as exc:
                        said.insert(0, 'graph?%s' % exc)
                result.setdefault('notices', []).append((held['phase'], _name, said, 'FULL' if changes.full and not was else ''))
            except Exception:
                pass
            return answer
        setattr(changes, name, logged)


def form_command(shader, key):
    from moonray_modo import shader_library
    types = [''] + sorted(shader_library.catalog())
    keys = sorted(shader_library.catalog()[shader]['attributes'])
    return 'moonray.material.attr%d_%d' % (types.index(shader), keys.index(key))


def shown(item, key):
    from moonray_modo import properties, node_defaults, shader_library
    spec = shader_library.catalog()['DwaBaseMaterial']['attributes'][key]
    return properties.read(item).get('native_parameters', {}).get(key, node_defaults.start('DwaBaseMaterial', key, spec))


def form_same():
    item = named('Smooth Shine')
    lx.eval('select.item {%s} set' % item.id)
    value = shown(item, 'roughness')
    result['form_same_value'] = value
    lx.eval('%s %s' % (form_command('DwaBaseMaterial', 'roughness'), repr(float(value))))


def noisy_setup():
    from moonray_modo import properties
    item = named('Smooth Shine')
    settings = properties.read(item)
    settings.setdefault('native_parameters', {})['specular'] = 0.30000000000000004
    graph = settings.get('node_graph')
    if graph:
        graph['nodes'][graph['root']].setdefault('parameters', {})['specular'] = 0.30000000000000004
    # Through the kit's own command, as the graph editor writes: a tag may only be set within a command.
    lx.eval('moonray.material.applyGraph {%s} %s' % (item.id, properties.encode(settings)))
    result['specular_stored'] = properties.read(item).get('native_parameters', {}).get('specular')


def form_rounded():
    item = named('Smooth Shine')
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('%s 0.3' % form_command('DwaBaseMaterial', 'specular'))
    result['specular_after'] = shown(item, 'specular')


def form_change():
    item = named('Smooth Shine')
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('%s 0.7' % form_command('DwaBaseMaterial', 'roughness'))


def open_graph():
    from moonray_modo import node_editor
    editor = held['editor'] = node_editor.open_editor(named('Bumped Shine'))
    preview = editor.material_preview
    original = preview.graph_changed

    def counted(*a, **k):
        result['graph_previews'].append((at(), held['phase']))
        return original(*a, **k)
    preview.graph_changed = counted


def graph_same():
    from moonray_modo import nodes, node_defaults
    editor = held['editor']
    editor.set_value('bump', 'amplitude', -1, 0.01)
    spec = nodes.specs('DwaBaseMaterial')['roughness']
    editor.set_value('surface', 'roughness', -1, node_defaults.start('DwaBaseMaterial', 'roughness', spec))
    result['graph_same_amplitude'] = editor.graph['nodes']['bump']['parameters'].get('amplitude')
    result['graph_same_roughness_stored'] = 'roughness' in (editor.graph['nodes']['surface'].get('parameters') or {})


def graph_change():
    held['editor'].set_value('bump', 'amplitude', -1, 0.02)


def channel_same():
    material = next(i for i in modo.Scene().iterItems() if i.type == 'advancedMaterial' and i.name == 'Base Material')
    value = material.channel('diffAmt').get()
    result['channel_same_value'] = value
    lx.eval('item.channel advancedMaterial$diffAmt %s item:{%s}' % (repr(float(value)), material.id))


def channel_change():
    material = next(i for i in modo.Scene().iterItems() if i.type == 'advancedMaterial' and i.name == 'Base Material')
    lx.eval('item.channel advancedMaterial$diffAmt %s item:{%s}' % (repr(float(material.channel('diffAmt').get()) * 0.5), material.id))


def realtime_on():
    panel = held['panel']
    # As the RT button is pressed: realtime on, and the preview starts following the scene.
    if not panel.rt.isChecked():
        panel.rt.click()
    QtCore.QTimer.singleShot(8000, lambda: result.update(started={'following': panel._following, 'rendering': panel._rendering,
                                                                    'status': panel.status.text(), 'engine': panel.preview_engine.currentData(),
                                                                    'runtime': panel.runtime_path()}))


def finish():
    try:
        held['panel'].stop()
        editor = held.get('editor')
        if editor is not None:
            editor.close()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    # By phase: how many scenes reached the renderer, and whether the phase expected any.
    counts = {}
    for _, name in result['submits']:
        counts[name] = counts.get(name, 0) + 1
    result['by_phase'] = {name: {'submits': counts.get(name, 0), 'restart_expected': expected,
                                 'readings': sum(1 for _, p, _ in result.get('captures', []) if p == name),
                                 'whole_readings': sum(1 for _, p, reuse in result.get('captures', []) if p == name and not reuse),
                                 'graph_previews': sum(1 for _, p in result['graph_previews'] if p == name)}
                          for name, expected in result['expect'].items()}
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


STEPS = [(0, 'realtime on', True, realtime_on),
         (25, 'form: roughness entered at its value', False, form_same),
         (37, 'setup: specular stored as 0.30000000000000004', True, noisy_setup),
         (52, 'form: specular entered as 0.3', False, form_rounded),
         (64, 'form: roughness to 0.7 (control)', True, form_change),
         (79, 'graph editor opened', False, open_graph),
         (91, 'graph: amplitude and roughness entered as shown', False, graph_same),
         (103, 'graph: amplitude to 0.02 (control)', True, graph_change),
         (118, 'Modo channel: diffuse amount set to its value', False, channel_same),
         (130, 'Modo channel: diffuse amount halved (control)', True, channel_change),
         (145, 'schematic: workspace made', False, schematic_create),
         (155, 'schematic: mesh added to it', False, schematic_add),
         (165, 'schematic: node moved', False, schematic_move),
         (175, 'schematic: mesh taken out of the workspace', False, schematic_remove),
         (190, 'done', False, finish)]


def guarded(name, expected, step):
    phase(name, expected)
    try:
        step()
    except Exception:
        result.setdefault('errors', []).append((name, traceback.format_exc()))
    save()


def begin():
    try:
        from moonray_modo.panel import live_panels
        panel = held['panel'] = live_panels()[0]
        # The kit's own runtime: only it carries MoonLightIPR.
        panel.preferences.set('runtime', str(root / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'))
        if engine_name == 'xpu2':
            panel.preferences.set('xpu2/renderer', 'xpu2')
            panel._store(execution_mode='xpu')
            panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        else:
            panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        # A scene sent to the renderer: realtime's _submit, which a reading that changed nothing never reaches. Every
        # reading of the scene (_capture) is written down too: an edit taken for a change to the scene is read whole.
        submit = panel._submit

        def counted(*a, **k):
            result['submits'].append((at(), held['phase']))
            return submit(*a, **k)
        panel._submit = counted
        capture = panel._capture

        def captured(*a, **k):
            result.setdefault('captures', []).append((at(), held['phase'], bool(a and a[0])))
            return capture(*a, **k)
        panel._capture = captured
        log_notices(panel.changes)
        held['began'] = time.time()
        for seconds, name, expected, step in STEPS:
            QtCore.QTimer.singleShot(int(seconds * 1000), lambda n=name, e=expected, s=step: guarded(n, e, s))
    except Exception:
        result['error'] = traceback.format_exc()
    save()


try:
    lx.eval('scene.open {%s} normal' % (root / 'test-results/bump-node/bump_node.lxo'))
    lx.eval('moonray.open')
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
