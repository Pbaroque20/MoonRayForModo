# python
"""Command line: Move Shader Tree Textures to MoonShine Graphs (moonray.material.moveShaderTreeTextures) on
MOONRAY_PROBE_SCENE (default the scene tools/probe_cl_shader_tree_scene.py writes). Writes to MOONRAY_PROBE_OUT:
  before.rdla, after.rdla   the scene as MoonRay is given it before and after the command (rendered outside Modo);
  report.json               the command's report; the clips, layers and graphs at each step; a run again that should
                            change nothing; undo and redo; edits (a layer added, one moved to another material, one's effect
                            changed, one deleted, polygons retagged) and a run after them;
  after.lxo                 the scene after the first run.
The command, app.undo and app.redo are run between this probe's phases at Modo's own prompt, where they make and take back
undo steps, which a script's commands do not (tools/launch_cl_steps.py), in this order:
  probe  moonray.material.moveShaderTreeTextures  probe  moonray.material.moveShaderTreeTextures  probe  app.undo  probe
  app.undo  probe  app.redo  app.redo  probe (makes the edits)  moonray.material.moveShaderTreeTextures  probe
MOONRAY_PROBE_STEPS=<name> stops after the first run (graphs-<name>.json, after-<name>.rdla), for the loader's comparison;
MOONRAY_PROBE_OPENED=1 leaves the scene open as it is (opened by the loader) instead of opening MOONRAY_PROBE_SCENE."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree')
source = pathlib.Path(os.environ.get('MOONRAY_PROBE_SCENE') or out / 'shader_tree.lxo')
steps = os.environ.get('MOONRAY_PROBE_STEPS', 'all')
opened = os.environ.get('MOONRAY_PROBE_OPENED') == '1'
report = {}


def save():
    (out / ('report.json' if steps == 'all' else 'report-%s.json' % steps)).write_text(json.dumps(report, indent=1, default=str))


def state():
    from moonray_modo import properties, material_override, shader_tree_transfer as transfer
    scene = modo.Scene()
    held = {'clips': sorted(c.name for c in scene.items('videoStill')), 'folders': sorted(f.name for f in scene.items('imageFolder')),
            'layers': {}, 'graphs': {}}
    for layer in scene.items('imageMap'):
        held['layers'][layer.name] = bool(layer.channel('enable').get())
    for item in scene.items('advancedMaterial', superType=True):
        settings = properties.read(item)
        graph = settings.get('node_graph') if material_override.enabled(settings) else None
        if graph:
            held['graphs'][item.name] = graph
    return held


def summary(held):
    from moonray_modo import shader_tree_transfer as transfer
    return {name: {'ours': sorted(i for i, n in graph['nodes'].items() if transfer.ours(i, n)),
                   'inputs': graph['nodes'][graph['root']].get('inputs')} for name, graph in held['graphs'].items()}


def export(name):
    from moonray_modo import host, rdla
    with host.by_engine('moonray'):
        snapshot = host.snapshot(evaluated_geometry=True)
    render = modo.Scene().renderItem
    text = rdla.scene_text(snapshot, int(render.channel('resX').get()), int(render.channel('resY').get()), 6, 0.0, str(out / (name + '.exr')))
    (out / (name + '.rdla')).write_text(text, encoding='utf-8')
    report[name + ' warnings'] = snapshot.get('warnings')


def ran(label):
    """The command's report and the scene's state after the run just made at the prompt."""
    from moonray_modo import shader_tree_scene
    report[label + ' report'] = list(shader_tree_scene.LAST_REPORT)
    held = state()
    report[label + ' state'] = {'clips': held['clips'], 'folders': held['folders'], 'layers': held['layers'], 'graphs': summary(held)}
    save()
    return held


def same(a, b):
    return json.dumps(a['graphs'], sort_keys=True) == json.dumps(b['graphs'], sort_keys=True) and a['clips'] == b['clips'] \
        and a['folders'] == b['folders'] and a['layers'] == b['layers']


import builtins
held = getattr(builtins, '_shader_tree_probe', None)
if held is None:
    held = builtins._shader_tree_probe = {'phase': 0, 'report': report}
held['phase'] += 1
phase = held['phase']
report = held['report']
try:
    if phase == 1:
        if not opened:
            lx.eval('scene.open {%s} normal' % source)
        held['initial'] = state()
        report['initial'] = {'clips': held['initial']['clips'], 'layers': held['initial']['layers'], 'graphs': summary(held['initial'])}
        if steps == 'all':
            export('before')
    elif phase == 2:
        first = held['first'] = ran('first')
        (out / ('graphs-%s.json' % ('first' if steps == 'all' else steps))).write_text(json.dumps(first['graphs'], indent=1, sort_keys=True, default=str))
        if steps != 'all':
            export('after-' + steps)
    elif phase == 3:
        again = ran('again')
        (out / 'graphs-again.json').write_text(json.dumps(again['graphs'], indent=1, sort_keys=True, default=str))
        report['again unchanged'] = same(again, held['first'])
    elif phase in (4, 5):
        undone = state()
        report['undo %d' % (phase - 3)] = {'as before the command': same(undone, held['initial']), 'as after the first run': same(undone, held['first']),
                                           'clips': undone['clips'], 'folders': undone['folders']}
    elif phase == 6:
        report['redo: as after the first run'] = same(state(), held['first'])
        export('after')
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'after.lxo'))
        # Edits: a layer added (Shared), a moved layer taken to another material (grey: Blend to Repeat), one's effect changed
        # (Tags' roughness to metallic), one deleted (Shared's colour), polygons retagged (Shared's cube to Tags).
        scene = modo.Scene()
        layers = {layer.name: layer for layer in scene.items('imageMap')}
        masks = {m.channel('ptag').get(): m for m in scene.items('mask', superType=False)}
        lx.eval('clip.addStill {%s}' % (out / 'images' / 'rough.png'))
        rough = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == 'rough.png')
        added = scene.addItem('imageMap', name='added rough (Image)')
        added.setParent(masks['Shared'], len(list(masks['Shared'].children())))
        graph = lx.object.ItemGraph(lx.object.Scene(added._item.Context()).GraphLookup('shadeLoc'))
        graph.AddLink(added._item, rough._item)
        added.channel('effect').set('rough')
        locator = next(i for i in added.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
        locator.channel('projType').set('uv')
        locator.channel('uvMap').set('Texture')
        layers['grey (Image)'].setParent(masks['Repeat'], len(list(masks['Repeat'].children())))
        layers['rough (Image)'].channel('effect').set('metallic')
        lx.eval('select.item {%s} set' % layers['colour (Image) (2)'].id)
        lx.eval('!item.delete')
        shared = next(m for m in scene.items('mesh') if m.name == 'Shared')
        lx.eval('select.item {%s} set' % shared.id)
        lx.eval('select.type polygon')
        lx.eval('select.all')
        lx.eval('poly.setMaterial {Tags}')
        lx.eval('select.type item')
        report['edits'] = 'made'
    elif phase == 7:
        edited = ran('edited')
        export('edited')
        (out / 'graphs-edited.json').write_text(json.dumps(edited['graphs'], indent=1, sort_keys=True, default=str))
except Exception:
    report['error phase %d' % phase] = traceback.format_exc()
save()
