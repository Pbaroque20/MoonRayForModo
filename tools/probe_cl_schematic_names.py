# python
"""Command line: what Modo's Schematic is made of, for telling its edits apart from the scene's. Modo's commands whose
names start with schematic., the scene's item types and graphs whose names suggest the Schematic (schm, workspace,
schematic), and, after a workspace is made and a mesh added to it, what items and graph links that made. Writes
test-results/schematic-names/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\schematic-names')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    commands = lx.service.Command()
    names = []
    for index in range(commands.CommandCount()):
        try:
            name = commands.CommandByIndex(index).Name()
        except Exception:
            continue
        if 'schem' in name.lower() or 'workspace' in name.lower():
            names.append(name)
    result['commands'] = sorted(names)
    scenes = lx.service.Scene()
    types = []
    for index in range(scenes.ItemTypeCount()):
        try:
            name = scenes.ItemTypeName(scenes.ItemTypeByIndex(index))
        except Exception:
            continue
        if any(word in name.lower() for word in ('schm', 'schem', 'workspace', 'wksp')):
            types.append(name)
    result['item_types'] = sorted(types)
    lx.eval('scene.new')
    scene = modo.Scene()
    before = {i.id for i in scene.iterItems()}
    mesh = scene.addMesh('Probe Mesh')
    steps = []
    for command in ('schematic.createWorkspace "Probe Workspace"', 'schematic.create "Probe Workspace"', 'schematic.addWorkspace'):
        try:
            lx.eval(command)
            steps.append((command, 'ok'))
            break
        except Exception as exc:
            steps.append((command, str(exc)))
    lx.eval('select.item {%s} set' % mesh.id)
    for command in ('schematic.addItem', 'schematic.addItem {%s}' % mesh.id):
        try:
            lx.eval(command)
            steps.append((command, 'ok'))
            break
        except Exception as exc:
            steps.append((command, str(exc)))
    result['steps'] = steps
    made = [i for i in scene.iterItems() if i.id not in before]
    result['made'] = [(i.name, i.type, i.id) for i in made]
    graphs = {}
    for item in made + [mesh]:
        for index in range(lx.object.Scene(scene).GraphCount()):
            graph = lx.object.Scene(scene).GraphByIndex(index)
            name = graph.Name()
            try:
                item_graph = lx.object.ItemGraph(graph)
                fwd = item_graph.FwdCount(item)
                rev = item_graph.RevCount(item)
            except Exception:
                continue
            if fwd or rev:
                graphs.setdefault(item.name, []).append((name, fwd, rev))
    result['graphs'] = graphs
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
