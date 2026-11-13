"""Solo, for the preview only (as Octane's): one node of a material graph shown on the meshes that wear the material,
as a light of its colour, or only the meshes of one material, or only the selected meshes, rendered. Final renders,
exports and the scene are left alone; the preview window takes it at each render (panel), as it takes clay.

The state is kept here while Modo runs, and the preview windows listening (LISTENERS) render again when it changes."""
import copy

STATE = {}
LISTENERS = []


def current():
    """What is soloed: {'kind': 'node', 'material': item id, 'node': graph node, 'label'}, {'kind': 'material',
    'materials': [item ids], 'label'} or {'kind': 'meshes', 'meshes': [item ids], 'label'}; None for nothing."""
    return dict(STATE) if STATE.get('kind') else None


def _scene_closed(key):
    # What was soloed names items by id, which the next scene may have too: a scene closing ends the solo.
    if STATE.get('kind'):
        clear()


def _set(state):
    if state:
        try:
            from . import scene_watch
            scene_watch.watch(_scene_closed)
        except Exception:
            pass
    STATE.clear()
    STATE.update(state or {})
    for listener in list(LISTENERS):
        try:
            listener()
        except Exception:
            pass


def solo_node(material_id, node, label=''):
    _set({'kind': 'node', 'material': str(material_id), 'node': str(node), 'label': label or str(node)})


def solo_materials(material_ids, label=''):
    _set({'kind': 'material', 'materials': [str(i) for i in material_ids], 'label': label or 'material'})


def solo_meshes(mesh_ids, label=''):
    _set({'kind': 'meshes', 'meshes': [str(i) for i in mesh_ids], 'label': label or 'meshes'})


def clear():
    _set(None)


def is_node(material_id, node):
    return STATE.get('kind') == 'node' and STATE.get('material') == str(material_id) and STATE.get('node') == str(node)


def _rows(material):
    return material.get('material_stack') or [material]


def _owned(material, ids):
    return any(str(row.get('base_layer_id')) in ids for row in _rows(material) if isinstance(row, dict))


def shown_graph(graph, node):
    """The graph with its output made a light of the node's colour (DwaEmissiveMaterial's emission), or, for a material
    node, that material; its displacement kept. None where the node is not one that has a colour to show."""
    from . import nodes
    if not isinstance(graph, dict) or node not in (graph.get('nodes') or {}):
        return None
    made = copy.deepcopy(graph)
    category = nodes.category(made['nodes'][node]['type'])
    if category == 'material':
        made['root'] = node
        return made
    if category != 'map':
        return None
    key = '__solo__'
    while key in made['nodes']:
        key += '_'
    made['nodes'][key] = {'type': 'DwaEmissiveMaterial', 'parameters': {'show_emission': True}, 'inputs': {'emission': node},
                          'position': [0, 0]}
    made['root'] = key
    return made


def apply(scene, state=None):
    """The scene as the preview renders it while something is soloed (state, else current()); as it was otherwise."""
    state = state if state is not None else current()
    if not state or not isinstance(scene, dict):
        return scene
    from . import face_tags
    scene = dict(scene)
    materials = dict(scene.get('materials') or {})
    if state['kind'] == 'node':
        for tag, material in materials.items():
            for row in _rows(material):
                if not isinstance(row, dict) or str(row.get('base_layer_id')) != state['material'] or not row.get('node_graph'):
                    continue
                graph = shown_graph(row['node_graph'], state['node'])
                if graph is None:
                    continue
                shown = {k: v for k, v in row.items() if k != 'material_stack'}
                shown.update(node_graph=graph, node_override=True)
                if graph['nodes'][graph['root']]['type'] == 'DwaEmissiveMaterial':
                    shown.update(native_shader='DwaEmissiveMaterial', native_parameters={'show_emission': True})
                materials[tag] = shown
                break
        scene['materials'] = materials
        return scene
    if state['kind'] == 'material':
        wanted = {tag for tag, material in materials.items() if isinstance(material, dict) and _owned(material, set(state['materials']))}

        def kept(mesh):
            return any((tag if tag in materials else '') in wanted for tag in face_tags.worn(mesh))
    else:
        ids = set(state['meshes'])

        def kept(mesh):
            return str(mesh.get('identity', '')).split('|')[0] in ids or str(mesh.get('item', '')) in ids
    scene['meshes'] = [mesh for mesh in scene.get('meshes') or [] if kept(mesh)]
    if scene.get('extra_geometry'):
        scene['extra_geometry'] = [extra for extra in scene['extra_geometry'] if kept(extra)]
    return scene
