"""The graph editor's presets: selected nodes with the wires between them, or a whole network with its outputs and override
layers, kept as files of their own for use in any scene: %APPDATA%\\MoonRayForModo\\Graph Presets. A texture is kept by the
path it has; where it is not on the machine that opens the preset, the render says so as for any scene."""
import copy
import json
import os
import re
import tempfile
import uuid
from pathlib import Path

FORMAT = 1
SELECTION, NETWORK = 'selection', 'network'
LABELS = {SELECTION: 'selected nodes', NETWORK: 'whole network'}


def folder():
    return Path(os.environ.get('APPDATA', tempfile.gettempdir())) / 'MoonRayForModo' / 'Graph Presets'


def file_for(name):
    """The file a preset of this name is kept in. Characters Windows does not take in a file name become underscores."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
    if not stem:
        raise ValueError('A preset needs a name')
    return folder() / (stem + '.json')


def capture(graph, chosen=None):
    """What a preset keeps of a graph: all of it, or the chosen nodes and only the wires between them."""
    if chosen is None:
        return {'format': FORMAT, 'kind': NETWORK, 'graph': copy.deepcopy(graph)}
    kept = {}
    for identity in chosen:
        node = copy.deepcopy(graph['nodes'][identity])
        node['inputs'] = {key: source for key, source in (node.get('inputs') or {}).items() if source in chosen}
        kept[identity] = node
    return {'format': FORMAT, 'kind': SELECTION, 'graph': {'version': graph.get('version', 1), 'nodes': kept}}


def save(name, preset):
    """Keep a preset under this name, replacing one that had it. Written whole or not at all."""
    path = file_for(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        staged.write_text(json.dumps(dict(preset, name=name), indent=1, sort_keys=True), encoding='utf-8')
        staged.replace(path)
    finally:
        if staged.exists():
            staged.unlink()
    return path


def read(path):
    preset = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(preset, dict) or preset.get('format') != FORMAT or preset.get('kind') not in LABELS \
            or not isinstance((preset.get('graph') or {}).get('nodes'), dict):
        raise ValueError('Not a graph preset of this version: ' + Path(path).name)
    return preset


def listed():
    """[(name, kind, path)] of the presets kept, by name. A file that cannot be read is left out."""
    found = []
    try:
        paths = list(folder().glob('*.json'))
    except OSError:
        return found
    for path in paths:
        try:
            preset = read(path)
        except (OSError, ValueError):
            continue
        found.append((str(preset.get('name') or path.stem), preset['kind'], path))
    return sorted(found, key=lambda row: row[0].casefold())


def added_to(graph, preset, at):
    """Put a preset's nodes into a graph, under new identities and centred on a point; its identities in the graph. A
    network's outputs and override layers stay behind: the graph keeps its own."""
    nodes = preset['graph']['nodes']
    made = {identity: 'node_' + uuid.uuid4().hex[:12] for identity in nodes}
    places = [node.get('position') or [0, 0] for node in nodes.values()]
    middle = [(min(p[i] for p in places) + max(p[i] for p in places)) / 2 for i in (0, 1)] if places else [0, 0]
    for identity, node in nodes.items():
        node = copy.deepcopy(node)
        x, y = node.get('position') or [0, 0]
        node['position'] = [x - middle[0] + at[0], y - middle[1] + at[1]]
        node['inputs'] = {key: made[source] for key, source in (node.get('inputs') or {}).items() if source in made}
        graph['nodes'][made[identity]] = node
    return list(made.values())


def network_of(preset):
    """The graph a network preset was saved as."""
    return copy.deepcopy(preset['graph'])
