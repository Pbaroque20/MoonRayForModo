"""Images on a native material's inputs, kept in its node graph.

The material's properties form and the graph editor both work on the one graph the material
stores: choosing an image in the form wires an image node to the input, and the graph editor
shows that node; wiring one in the editor shows in the form. Nothing here touches Modo.
"""
import copy
import os
import uuid
from . import nodes

# The inputs the form offers an image for, in the order they are usually reached for.
INPUTS = ('albedo', 'roughness', 'metallic', 'emission', 'transmission', 'transmission_color', 'clearcoat',
          'clearcoat_roughness', 'anisotropy', 'scattering_color', 'input_normal', 'presence')
# Inputs that hold a colour, whose images are read as sRGB; the rest are data.
COLOURS = ('albedo', 'emission', 'transmission_color', 'scattering_color', 'metallic_color')


def offered(shader):
    """The inputs of a shader that an image can be chosen for in its form."""
    try:
        attributes = nodes.specs(shader)
    except ValueError:
        return []
    return [key for key in INPUTS if key in attributes and nodes.connectable(shader, key)]


def graph_of(settings):
    """The material's graph, or a new one holding just the material as it stands."""
    graph = settings.get('node_graph')
    if graph:
        return copy.deepcopy(graph)
    return nodes.new(settings.get('native_shader') or 'DwaBaseMaterial', copy.deepcopy(settings.get('native_parameters') or {}))


def source(graph, key):
    """The node an input reads its image from, looking through a normal map node; or None."""
    root = graph['nodes'][graph['root']]
    node = graph['nodes'].get(root.get('inputs', {}).get(key))
    if node is not None and node['type'] == 'normalmap':
        return graph['nodes'].get(node.get('inputs', {}).get('in'))
    return node


def image(settings, key):
    """What is wired to an input: ('image', path), ('node', type) for anything else, or None."""
    graph = settings.get('node_graph')
    if not graph or graph.get('root') not in graph.get('nodes', {}):
        return None
    node = source(graph, key)
    if node is None:
        return ('node', 'normalmap') if graph['nodes'][graph['root']].get('inputs', {}).get(key) else None
    values = node.get('parameters', {})
    if node['type'] == 'image':
        return ('image', values.get('file', ''))
    if node['type'] == 'ImageMap':
        return ('image', values.get('texture', ''))
    return ('node', node['type'])


def label(found):
    """A few words for the form about what an input reads."""
    if found is None:
        return '(none)'
    kind, value = found
    if kind == 'image':
        return os.path.basename(str(value).replace('\\', '/')) or '(image with no file)'
    return 'Graph: ' + value


def place(graph, column, row):
    """A spot to the left of the material for a new node."""
    x, y = graph['nodes'][graph['root']].get('position', [300, 50])
    return [x - 260 * column, y + 120 * row]


def set_image(settings, key, path):
    """The graph with an image on an input: the file of the image node already there, or a new
    image node wired to it."""
    graph = graph_of(settings)
    root = graph['nodes'][graph['root']]
    node = source(graph, key)
    path = str(path).replace('\\', '/')
    if node is not None and node['type'] == 'image':
        node.setdefault('parameters', {})['file'] = path
        return graph
    if node is not None and node['type'] == 'ImageMap':
        node.setdefault('parameters', {})['texture'] = path
        return graph
    row = INPUTS.index(key) if key in INPUTS else len(root.get('inputs', {}))
    identity = 'node_' + uuid.uuid4().hex[:12]
    graph['nodes'][identity] = {'type': 'image', 'parameters': {'file': path, 'srgb': key in COLOURS}, 'inputs': {},
                                'position': place(graph, 2 if key == 'input_normal' else 1, row)}
    wired = identity
    if key == 'input_normal':
        # A normal map is read through a node that turns its colours into directions.
        wired = 'node_' + uuid.uuid4().hex[:12]
        graph['nodes'][wired] = {'type': 'normalmap', 'parameters': {}, 'inputs': {'in': identity}, 'position': place(graph, 1, row)}
    root.setdefault('inputs', {})[key] = wired
    root.setdefault('parameters', {}).pop(key, None)
    return graph


def clear_image(settings, key):
    """The graph with nothing wired to an input. Nodes left feeding nothing are removed."""
    graph = graph_of(settings)
    root = graph['nodes'][graph['root']]
    if key not in root.get('inputs', {}):
        return graph
    # Only the nodes that fed this input are candidates; other unwired nodes are the user's.
    chain = [root['inputs'].pop(key)]
    inner = graph['nodes'].get(chain[0], {})
    if inner.get('type') == 'normalmap' and inner.get('inputs', {}).get('in'):
        chain.append(inner['inputs']['in'])
    for identity in chain:
        used = {value for node in graph['nodes'].values() for value in node.get('inputs', {}).values()}
        used |= {graph['root'], graph.get('displacement')}
        for layer in graph.get('overrides', []):
            used |= set(layer.get('inputs', {}).values()) | {layer.get('node')}
        node = graph['nodes'].get(identity)
        if node is not None and identity not in used and node['type'] in ('image', 'ImageMap', 'normalmap'):
            graph['nodes'].pop(identity)
    return graph
