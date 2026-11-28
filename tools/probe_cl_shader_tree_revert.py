# python
"""Command line: Shader Tree -> MoonShine and back (MoonShine -> Shader Tree, moonray.material.revertShaderTreeTextures) on
MOONRAY_PROBE_SCENE, with the graphs edited between. Run by tools/launch_cl_steps.py in this order, the commands at Modo's
own prompt so that each is an undo step:
  probe  moonray.material.moveShaderTreeTextures  probe  moonray.material.revertShaderTreeTextures  probe  app.undo  probe
Phase 1 notes the Shader Tree (each layer: on, its image file, effect, opacity, blend; each material: its MoonShine
override, whether it has a graph). Phase 2 notes it converted, then edits the graphs: the first converted Modo Texture
node's opacity set to 0.5, a Modo Texture node of an image added to the first converted graph, and a Constant Color node there.
Phase 3 notes it reverted and compares with phase 1 (that layer's opacity 0.5 expected, a new layer expected); phase 4
after the undo. Writes report.json to MOONRAY_PROBE_OUT."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a1b7a7f9b3e570cb4\test-results\shader-tree-revert')
out.mkdir(parents=True, exist_ok=True)
source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
path = out / 'report.json'
report = json.loads(path.read_text()) if path.exists() else {}
if not report.get('phase') or report.get('phase') >= 4:
    report = {'phase': 0}
report['phase'] += 1
phase = report['phase']


def save():
    path.write_text(json.dumps(report, indent=1, default=str))


def state():
    from moonray_modo import properties, material_override, shader_tree_scene
    scene = modo.Scene()
    layers, materials = {}, {}
    for item in scene.items('imageMap') + scene.items('constant'):
        clip, folder = shader_tree_scene.image_of(item)
        def ch(name, default=None):
            try:
                return item.channel(name).get()
            except Exception:
                return default
        layers[item.id] = {'name': item.name, 'on': bool(ch('enable', 1)), 'file': ch and (clip.channel('filename').get() if clip is not None else (folder.name if folder else None)),
                           'effect': ch('effect'), 'opacity': round(float(ch('opacity', 1)), 4), 'blend': ch('blend'), 'parent': item.parent.id if item.parent else None}
    for item in scene.items('advancedMaterial'):
        settings = properties.read(item)
        materials[item.id] = {'name': item.name, 'override': bool(material_override.enabled(settings)), 'graph': bool(settings.get('node_graph'))}
    return {'layers': layers, 'materials': materials}


def edit():
    from moonray_modo import properties, material_override, shader_tree_transfer as transfer, modo_texture
    scene = modo.Scene()
    # A material in a group of its own first: a new layer is made there (not at the top of the Shader Tree).
    for item in sorted(scene.items('advancedMaterial'), key=lambda i: i.parent is None or i.parent.type != 'mask'):
        settings = properties.read(item)
        graph = settings.get('node_graph') if material_override.enabled(settings) else None
        if not graph:
            continue
        mine = [(i, n) for i, n in graph['nodes'].items() if transfer.ours(i, n) and n.get('type') == modo_texture.KIND
                and (n.get('parameters') or {}).get('kind') == 'imageMap']
        if not mine:
            continue
        identity, node = mine[0]
        node.setdefault('parameters', {})['opacity'] = 0.5
        added = dict(type=modo_texture.KIND, parameters=dict(node['parameters'], opacity=1.0, effect='rough'))
        graph['nodes']['user_texture'] = added
        graph['nodes']['user_add'] = {'type': 'ConstantColorMap', 'parameters': {}}
        properties.write(item, material_override.synchronize(settings, graph))
        return {'material': item.name, 'node': identity, 'layer': node[transfer.NODE_KEY].get('layer')}
    return None


try:
    if phase == 1:
        lx.eval('!scene.open {%s} normal' % source)
        report['before'] = state()
    elif phase == 2:
        report['converted'] = state()
        report['edited'] = edit()
    elif phase == 3:
        from moonray_modo import shader_tree_revert
        report['revert_report'] = list(shader_tree_revert.LAST_REPORT)
        now = state()
        report['reverted'] = now
        before = report['before']
        diffs = []
        for identity, held in before['layers'].items():
            got = now['layers'].get(identity)
            if got is None:
                diffs.append((held['name'], 'gone'))
                continue
            for key in ('on', 'file', 'effect', 'opacity', 'blend', 'parent'):
                if got[key] != held[key]:
                    diffs.append((held['name'], key, held[key], got[key]))
        new = [held['name'] for identity, held in now['layers'].items() if identity not in before['layers']]
        materials = [(held['name'], key, held[key], now['materials'].get(identity, {}).get(key))
                     for identity, held in before['materials'].items() for key in ('override', 'graph')
                     if now['materials'].get(identity, {}).get(key) != held[key]]
        report['layer_differences'] = diffs
        report['new_layers'] = new
        report['material_differences'] = materials
    elif phase == 4:
        report['undone'] = state()
        report['undo_as_converted'] = report['undone'] == report['converted'] or {
            'layers_same': report['undone']['layers'] == report['converted']['layers'],
            'materials_same': report['undone']['materials'] == report['converted']['materials']}
except Exception:
    report['error_%d' % phase] = traceback.format_exc()
save()
