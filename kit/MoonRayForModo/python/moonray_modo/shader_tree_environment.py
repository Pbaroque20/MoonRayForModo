"""An Environment's Shader Tree layers as a MoonShine graph (MoonRay > Move Shader Tree Textures to MoonShine Graphs), so
that Modo holds its images no more.

The graph is kept in the environment item's kit settings (properties, under KEY), as a material's is in its own. Its
output is a modo_environment node whose Color is the top layer; each layer is a Modo Blend (modo_blend: its blend mode
and opacity) laying what the layer is (its Foreground: an Environment Image, an Environment Sky, an Environment
Procedural, or a colour) over the layers beneath it (its Background, the next Modo Blend down). Every node made here
carries the layer's identity (shader_tree_transfer.NODE_KEY, an identity starting with PREFIX), so that a later run finds
it again.

The kit draws such a graph as it draws the layers it was made from: environments.collect reads each of its layers
(drawn_layers) through stand-ins for the layer, its Texture Locator and its clip (Stand) whose channels are the node's
values, so that the environment is composed by the very reading and composing of Shader Tree layers the kit renders
with (environment_layers), for MoonRay, XPU2 (the same scene) and MoonLightIPR alike. A node that names a Texture
Locator still in the scene is placed by it, live: turning it turns the HDRI as before. A Physical Sky is lit by its Sun
Light as the layer was.

run() moves the layers of an environment with an image layer into its graph, whole (one without an image is left as
it is, WITHOUT_IMAGES): an environment with a layer the graph cannot draw as the
Shader Tree does (one in a group, a mask, a texture Gradient layer) stays in the Shader Tree, said in the report, and
one that had a graph has its layers put back. A layer the kit does not read at all (it renders nothing) stays where it
is, with its reason. Run again, the graph is brought up to date with its layers (switched off, read as on, their images
as their nodes name them): a layer whose channels are as they were keeps its nodes as they are, edits in the graph
included; one that changed is read anew; a layer that is gone takes its nodes with it."""
import copy
import json

from . import nodes, shader_tree_transfer as transfer

KEY = 'environment_graph'
ROOT = 'environment'
OUTPUT, IMAGE, SKY, PROCEDURAL = nodes.ENVIRONMENT_NODES
VERSION = 1
# Whether an environment with no image layer (a gradient, a sky, colours) is moved too: off, it is left as it is, as
# nothing of it is unloaded and a layer switched off is no longer shown in Modo's viewport. On for the tests.
WITHOUT_IMAGES = False
# A stand-in's identity: never a scene item's, so that what the kit holds of its channels for one reading is its own.
STAND = 'mrenv|'

# Node value -> the Modo channel(s) it stands for.
LOCATOR = (('projection', 'projType'), ('axis', 'projAxis'), ('wrap', ('wrapU', 'wrapV')), ('uv_rotation', 'uvRotation'),
           ('uv_matrix', ('m00', 'm01', 'm02', 'm10', 'm11', 'm12')), ('tile_u', 'tileU'), ('tile_v', 'tileV'),
           ('hardness', 'triplanarBlending'), ('random_offset', 'randOffset'))
IMAGE_CHANNELS = (('gamma', 'gamma'), ('brightness', 'brightness'), ('contrast', 'contrast'), ('low', 'min'), ('high', 'max'),
                  ('swizzling', 'swizzling'), ('rgba', 'rgba'), ('alpha', 'alpha'), ('flip_red', 'redInv'), ('flip_green', 'greenInv'),
                  ('flip_blue', 'blueInv'), ('invert', 'invert'))
SKY_CHANNELS = (('type', 'type'), ('zenith', 'zenColor'), ('sky', 'skyColor'), ('ground', 'gndColor'), ('nadir', 'nadColor'),
                ('sky_exponent', 'skyExp'), ('ground_exponent', 'gndExp'), ('normalize', 'normalize'), ('gamma', 'clampedGamma'),
                ('albedo', 'albedo'), ('disc', 'disc'), ('inscatter', 'inscatter'), ('invert', 'invert'))
PROCEDURAL_CHANNELS = (('pattern', 'type'), ('transition', 'transWidth'), ('bias', 'bias'), ('gain', 'gain'), ('color1', 'color1'),
                       ('color2', 'color2'), ('alpha1', 'alpha1'), ('alpha2', 'alpha2'), ('invert', 'invert'))
COLOURS = ('zenith', 'sky', 'ground', 'nadir', 'color1', 'color2')
# The layer types each node stands for.
ROLES = {'imageMap': ('image', IMAGE), 'envMaterial': ('sky', SKY), 'grid': ('procedural', PROCEDURAL), 'dots': ('procedural', PROCEDURAL)}
PROJECTIONS = ('spherical', 'planar', 'cylindrical', 'cubic', 'box', 'lightprobe', 'triplanar', 'front', 'uv', 'implicitUV', 'none')


def blend_names():
    from .layers import BLENDS
    return sorted(BLENDS, key=BLENDS.get)


def default(kind, name):
    return copy.deepcopy(nodes.MAPS[kind][name][1])


def typed(kind, name, value):
    """A channel's value as the node keeps it (its type in nodes.MAPS); its default where the channel has none."""
    if value is None:
        return default(kind, name)
    spec = nodes.MAPS[kind][name][0]
    if spec == 'String':
        return str(value)
    if spec == 'Bool':
        return bool(value)
    if spec == 'Int':
        from .environment_projections import axis_number
        return int(axis_number(value)) if name == 'axis' else int(value)
    if spec == 'Float':
        return float(value)
    if spec == 'Rgb':
        from .channel_values import rgb
        return rgb(value, name)
    return [float(v) for v in value]


def describe(kind, result):
    """The Environment nodes' choices and notes, for the graph editor (nodes.specs)."""
    if kind in (IMAGE, PROCEDURAL):
        result['projection']['enum'] = {name: name for name in PROJECTIONS}
        result['axis']['enum'] = {'X': 0, 'Y': 1, 'Z': 2}
        for key in ('tile_u', 'tile_v'):
            result[key]['enum'] = {name.title(): name for name in ('repeat', 'reset', 'mirror', 'edge')}
        result['locator']['comment'] = ('The Texture Locator that places it, while it is in the scene (turn it to turn the image); '
                                        'empty or gone, the values below place it.')
        result['locator_matrix']['comment'] = "The Texture Locator's world matrix when the layer moved."
        result['wrap']['comment'] = "Horizontal and Vertical Wrap, as the Texture Locator's."
        result['uv_rotation']['comment'] = 'UV Rotation, in radians.'
        result['uv_matrix']['comment'] = "The locator's UV transform (m00 m01 m02 m10 m11 m12)."
        result['hardness']['comment'] = 'Triplanar Blending Hardness.'
    if kind == IMAGE:
        for key in ('alpha', 'rgba'):
            result[key]['enum'] = {name.title(): name for name in ('use', 'ignore', 'only', 'red', 'green', 'blue')}
        result['file']['comment'] = 'The image file (a latitude-longitude HDRI for a Spherical projection).'
        result['color_space']['comment'] = "The clip's colour space, as Modo names it; (default) reads HDR files as linear, others as sRGB."
        result['alpha']['comment'] = "The layer's Alpha: Use lays it by the image's alpha, where the image has one."
        result['low']['comment'] = 'Low Value: what the image\'s black comes out as.'
        result['high']['comment'] = 'High Value: what the image\'s white comes out as.'
    if kind == SKY:
        result['type']['enum'] = {'Constant': 'constant', '2 Color Gradient': 'grad2', '4 Color Gradient': 'grad4',
                                  'CIE Overcast Sky': 'overcast', 'Physical Sky': 'physical'}
        result['sun']['comment'] = ('The Sun Light of a Physical Sky (its item); empty, the one the environment\'s MoonRay '
                                    'settings name, or the scene\'s one Sun Light.')
        result['gamma']['comment'] = 'Physical Sky: its Clamped Gamma.'
        result['disc']['comment'] = "Physical Sky: the sun's disc, seen by the camera."
    if kind == PROCEDURAL:
        result['kind']['enum'] = {'Grid': 'grid', 'Dots': 'dots'}
        result['pattern']['enum'] = {name.title(): name for name in ('line', 'square', 'triangle', 'hexagon')}
        result['width']['comment'] = 'Line Width of a Grid, Dot Width of Dots.'
    if kind == OUTPUT:
        result['color']['comment'] = "The environment's colour: wire the top layer's Modo Blend here."


# Drawing a graph: the kit's own reading of Shader Tree layers, given stand-ins whose channels are the nodes' values.
class _Value:
    def __init__(self, value):
        self.value = value

    def get(self, *args):
        return self.value


class _Links:
    def __init__(self, items):
        self._items = list(items)

    def forward(self, *args):
        return list(self._items)

    def reverse(self, *args):
        return []


class Stand:
    """An item environments.collect reads as a Shader Tree layer, a Texture Locator or a clip, its channels given."""

    def __init__(self, identity, name, kind, values, parent=None, links=(), matrix=None):
        self.id = identity
        self.name = name
        self.type = kind
        self.parent = parent
        self._values = values
        self._links = list(links)
        if matrix is not None:
            self.held_matrix = [float(v) for v in matrix]  # host.world_matrix

    def channel(self, name):
        return _Value(self._values[name]) if name in self._values else None

    def itemGraph(self, name):
        return _Links(self._links if name == 'shadeLoc' else [])

    def children(self):
        return []

    def readTag(self, *args):
        raise LookupError('no tag')


def stored(environment):
    """An environment item's graph, or None."""
    try:
        from . import properties
        graph = properties.peek(environment).get(KEY)
    except Exception:
        return None
    return graph if isinstance(graph, dict) and graph.get('nodes') else None


def check(graph):
    """ValueError where a graph's nodes are not of the kinds and values they say."""
    from . import shader_library
    members = graph.get('nodes')
    if not isinstance(members, dict) or graph.get('root') not in members:
        raise ValueError('it has no output')
    for identity, node in members.items():
        schema = nodes.specs(node.get('type'))
        for key, value in (node.get('parameters') or {}).items():
            if key not in schema:
                raise ValueError('%s has no value %s' % (identity, key))
            shader_library.typed(value, schema[key])
        for key, source in (node.get('inputs') or {}).items():
            if source not in members:
                raise ValueError('%s is wired to a node that is not there' % identity)


def drawn_layers(scene, environment, warnings):
    """The layers environments.collect reads for an environment drawn by its graph, top first (stand-ins); None for one
    without a graph (its Shader Tree layers are read)."""
    graph = stored(environment)
    if graph is None:
        return None
    try:
        check(graph)
        made = stand_ins(scene, environment, graph)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        warnings.append('Environment %s: its MoonShine graph cannot be drawn (%s); it is drawn black.' % (environment.name, exc))
        return []
    try:
        left_on(environment, graph, warnings)
    except Exception:
        pass
    return made


def left_on(environment, graph, warnings):
    """Said: layers on in the Shader Tree beside a graph, which draws in their place."""
    from .host import channel
    from .layers import ordered_items
    known = set(recorded(graph)) | set((graph.get(transfer.META_KEY) or {}).get('left') or ())
    for item in ordered_items(environment):
        if item.type == 'mask' or item.id in known:
            continue
        if channel(item, 'enable', 1) and channel(item, 'render', 1) and channel(item, 'effect', None) is not None:
            warnings.append('Environment %s: the layer %s is on in the Shader Tree, but the environment is drawn by its MoonShine graph; '
                            'run Move Shader Tree Textures to MoonShine Graphs again to move it.' % (environment.name, item.name))


def stand_ins(scene, environment, graph):
    members = graph['nodes']
    root = members[graph['root']]
    if root.get('type') != OUTPUT:
        raise ValueError('its output is a %s, not an Environment Output' % root.get('type'))
    names = blend_names()
    made = []
    current = (root.get('inputs') or {}).get('color')
    if current is None:
        colour = (root.get('parameters') or {}).get('color')
        if colour and any(colour):
            made.append(colour_stand(environment, graph['root'], 'Color', colour, 'normal', 1.0))
        return made
    seen = set()
    while current is not None:
        if current in seen:
            raise ValueError('its layers are wired in a loop')
        seen.add(current)
        node = members[current]
        inputs = node.get('inputs') or {}
        values = node.get('parameters') or {}
        if node['type'] == 'modo_blend':
            if 'opacity' in inputs or 'mask' in inputs:
                raise ValueError('a Modo Blend (%s) whose Opacity or Mask is wired: an environment takes numbers there' % label(node, current))
            blend = int(values.get('blend', 0))
            if not 0 <= blend < len(names):
                raise ValueError('a Modo Blend with an unknown blend mode %d' % blend)
            opacity = float(values.get('opacity', 1)) * float(values.get('mask', 1))
            if opacity > 0:
                made.append(layer_stand(scene, environment, members, current, node, inputs.get('fg'), names[blend], opacity))
            here, current = current, inputs.get('bg')
            if current is None:
                beneath = values.get('bg', [0, 0, 0])
                if any(beneath):
                    made.append(colour_stand(environment, here + '|bg', label(node, here) + ' background', beneath, 'normal', 1.0))
        else:
            made.append(layer_stand(scene, environment, members, current, None, current, 'normal', 1.0))
            current = None
    return made


def label(node, identity):
    return node.get('label') or (node.get(transfer.NODE_KEY) or {}).get('name') or identity


class StandIdentity(str):
    """A stand-in layer's identity: the text of the layer it was made from (so that what the kit composes, and the
    picture it caches by it, is named as the layer's was: the same environment is not composed again for the move), yet
    never equal to the layer's own identity, so that what the kit holds of the layer's channels for a reading
    (host.channel, layers.texture_groups) is never taken for the stand-in's, nor the stand-in's for the layer's."""

    def __new__(cls, text, owner):
        made = str.__new__(cls, text)
        made.owner = owner
        return made

    def __eq__(self, other):
        return isinstance(other, StandIdentity) and str.__eq__(self, other) and self.owner == other.owner

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash(('stand', str(self), self.owner))

    def __reduce__(self):
        return (StandIdentity, (str(self), self.owner))


def stand_id(environment, identity, node=None):
    """A stand-in's identity: a layer's, as the layer the node was made from had it (StandIdentity)."""
    layer = (node or {}).get(transfer.NODE_KEY, {}).get('layer') if transfer.ours(identity, node) else None
    return StandIdentity(layer or STAND + environment.id + '|' + str(identity), environment.id)


def colour_stand(environment, identity, name, colour, blend, opacity, node=None):
    values = {'effect': 'envColor', 'blend': blend, 'opacity': float(opacity), 'invert': False}
    values.update({'color.' + axis: float(v) for axis, v in zip('RGB', colour)})
    return Stand(stand_id(environment, identity, node), name, 'constant', values, environment)


def layer_stand(scene, environment, members, identity, blend_node, source, blend, opacity):
    """A stand-in for the layer a Modo Blend (or a node wired straight to the output) lays."""
    name = label(blend_node or members[source], identity)
    common = {'effect': 'envColor', 'blend': blend, 'opacity': float(opacity)}
    if source is None:
        colour = (blend_node.get('parameters') or {}).get('fg', [1, 1, 1])
        return colour_stand(environment, identity, name, colour, blend, opacity, blend_node)
    node = members[source]
    kind = node['type']
    values = dict(default_values(kind), **(node.get('parameters') or {}))
    if kind == 'constant':
        return colour_stand(environment, identity, name, values.get('value', [.5, .5, .5]), blend, opacity, blend_node)
    if (node.get('inputs') or {}):
        raise ValueError('%s has wired inputs, which an environment does not draw' % label(node, source))
    sid = stand_id(environment, identity, blend_node if blend_node is not None else node)
    if kind == IMAGE:
        channels = dict(common, **{modo: values[param] for param, modo in IMAGE_CHANNELS})
        clip = Stand(STAND + environment.id + '|' + sid + '|clip', name + ' clip', 'videoStill', {'filename': values['file'], 'colorspace': values['color_space']})
        return Stand(sid, name, 'imageMap', channels, environment, [locator_for(scene, sid, name, values), clip])
    if kind == PROCEDURAL:
        if values['kind'] not in ('grid', 'dots'):
            raise ValueError('an Environment Procedural of kind %s; Grid and Dots are drawn' % values['kind'])
        channels = dict(common, **{modo: values[param] for param, modo in PROCEDURAL_CHANNELS if param not in COLOURS})
        for param in ('color1', 'color2'):
            channels.update({PROCEDURAL_NAMES[param] + '.' + axis: float(v) for axis, v in zip('RGB', values[param])})
        channels['lineWidth' if values['kind'] == 'grid' else 'dotWidth'] = values['width']
        return Stand(sid, name, values['kind'], channels, environment, [locator_for(scene, sid, name, values)])
    if kind == SKY:
        channels = dict(common, **{modo: values[param] for param, modo in SKY_CHANNELS if param not in COLOURS})
        for param in ('zenith', 'sky', 'ground', 'nadir'):
            channels.update({SKY_NAMES[param] + '.' + axis: float(v) for axis, v in zip('RGB', values[param])})
        links = []
        sun = live(scene, values.get('sun'), 'sunLight')
        if sun is not None:
            links.append(sun)
        return Stand(sid, name, 'envMaterial', channels, environment, links)
    raise ValueError('a %s node, which an environment does not draw' % kind)


SKY_NAMES = dict(SKY_CHANNELS)
PROCEDURAL_NAMES = dict(PROCEDURAL_CHANNELS)


def default_values(kind):
    return {key: copy.deepcopy(value[1]) for key, value in nodes.MAPS.get(kind, {}).items()}


def live(scene, identity, kind):
    """The scene's item of this identity and type, or None."""
    if not identity:
        return None
    try:
        item = scene.item(identity)
    except (LookupError, RuntimeError, AttributeError, TypeError):
        return None
    try:
        return item if item is not None and item.type == kind else None
    except (LookupError, RuntimeError, AttributeError):
        return None


def locator_for(scene, sid, name, values):
    """The Texture Locator a node is placed by: the one it names, while it is in the scene; otherwise one standing in
    for it with the node's values."""
    held = live(scene, values.get('locator'), 'txtrLocator')
    if held is not None:
        return held
    channels = {}
    for param, modo in LOCATOR:
        if isinstance(modo, tuple):
            channels.update({name: value for name, value in zip(modo, values[param])})
        else:
            channels[modo] = values[param]
    return Stand(STAND + str(sid) + '|locator', name + ' locator', 'txtrLocator', channels, None, (), values['locator_matrix'])


# Reading layers into nodes.
def locator_values(locator):
    from .host import channel, world_matrix
    found = {'locator': locator.id, 'locator_matrix': [float(v) for v in world_matrix(locator)]}
    for param, modo in LOCATOR:
        if isinstance(modo, tuple):
            spec = default(IMAGE, param)
            found[param] = [float(channel(locator, name, fallback)) for name, fallback in zip(modo, spec)]
        else:
            found[param] = typed(IMAGE, param, channel(locator, modo, None))
    return found


def linked(item, kind):
    try:
        return next((i for i in item.itemGraph('shadeLoc').forward() if i.type == kind), None)
    except (LookupError, RuntimeError, AttributeError):
        return None


def layer_values(item):
    """(node type, its values, the image's record) of a layer the kit read, from its channels; the node type None for a
    colour, its values then the colour."""
    from .host import channel, color
    kind = item.type
    if kind == 'constant':
        colour = color(item, 'color', (0, 0, 0))
        if channel(item, 'invert', 0):
            colour = [1 - v for v in colour]
        return None, [float(v) for v in colour], None
    role, node = ROLES[kind]
    if node == IMAGE:
        values = {param: typed(IMAGE, param, channel(item, modo, None)) for param, modo in IMAGE_CHANNELS}
        clip = linked(item, 'videoStill')
        values['file'] = str(channel(clip, 'filename', '') or '')
        values['color_space'] = str(channel(clip, 'colorspace', '(default)') or '(default)')
        values.update(locator_values(linked(item, 'txtrLocator')))
        # Read with the image its node names (or the one a stand-in clip is for): that record, as it is.
        held = item._source if type(item).__name__ == '_Layer' else None  # shader_tree_scene._Layer
        record = dict(held) if held else {'filename': values['file'], 'colorspace': values['color_space'], 'clip': clip.name}
        return node, values, record
    if node == PROCEDURAL:
        values = {param: typed(PROCEDURAL, param, color(item, modo, default(PROCEDURAL, param)) if param in COLOURS else channel(item, modo, None))
                  for param, modo in PROCEDURAL_CHANNELS}
        values['kind'] = kind
        values['width'] = float(channel(item, 'lineWidth' if kind == 'grid' else 'dotWidth', .1))
        values.update(locator_values(linked(item, 'txtrLocator')))
        return node, values, None
    values = {param: typed(SKY, param, color(item, modo, default(SKY, param)) if param in COLOURS else channel(item, modo, None))
              for param, modo in SKY_CHANNELS if param != 'albedo'}
    from .channel_values import rgb
    values['albedo'] = rgb(channel(item, 'albedo', .2), 'Physical sky ground albedo')
    sun = linked(item, 'sunLight')
    values['sun'] = sun.id if sun is not None else ''
    return node, values, None


def recorded(graph):
    """{layer identity: its image's record or None} of the layers a graph holds (and those it keeps the images of)."""
    found = {}
    for identity, node in ((graph or {}).get('nodes') or {}).items():
        if transfer.ours(identity, node):
            record = node[transfer.NODE_KEY]
            if record.get('source') or record['layer'] not in found:
                found[record['layer']] = record.get('source')
    for identity, source in (((graph or {}).get(transfer.META_KEY) or {}).get('kept') or {}).items():
        found.setdefault(identity, source)
    return found


def foreign(graph):
    """Whether a graph holds nodes this command did not make (beside its output)."""
    return any(not transfer.ours(identity, node) and identity != graph.get('root') for identity, node in (graph.get('nodes') or {}).items())


def refusal(entries, names):
    """Why an environment's layers cannot become a graph that draws them as the Shader Tree does, or None."""
    for entry in entries:
        name = names.get(entry.get('layer_identity'), entry.get('layer_identity'))
        if entry.get('groups'):
            return 'its layer %s is in a group, which the graph does not lay' % name
        if entry.get('effect', 'envColor') != 'envColor':
            return 'its layer %s is a %s, not an Environment Color layer' % (name, transfer.effect_name(entry.get('effect')))
        if entry.get('kind') == 'gradient':
            return 'its layer %s is a Gradient layer, which the graph does not lay' % name
    return None


def build(environment, entries, items, old, kept=None, left=None):
    """The graph for an environment's layers (environments.collect's entries for them, top first; items: identity ->
    the layer read), its nodes kept from old where their layer reads as it did. kept: {layer: its image's record} of
    layers it holds that read no more (switched off, their clips gone); left: {layer: why} of those that stay on."""
    from .host import channel
    names = blend_names()
    builder = transfer.Builder()
    previous = {i: n for i, n in ((old or {}).get('nodes') or {}).items() if transfer.ours(i, n)}

    def add(owner, role, kind, values, name, record=None, inputs=None):
        made = builder.add(owner, role, kind, values, inputs, label=name, data={'read': copy.deepcopy(values), 'source': record})
        node = builder.nodes[made[1]]
        if record is None:
            node[transfer.NODE_KEY].pop('source')
        held = previous.get(made[1])
        if held is not None and held.get('type') == kind and same((held.get(transfer.NODE_KEY) or {}).get('read'), values):
            # Its layer reads as it did when this node was made: the node as it is now (edits made in the graph kept).
            node['parameters'] = copy.deepcopy(held.get('parameters') or {})
            if held.get('label'):
                node['label'] = held['label']
        return made

    below = None
    order = []
    for entry in reversed(entries):
        item = items[entry['layer_identity']]
        kind, values, record = layer_values(item)
        mode = channel(item, 'blend', 'normal')
        over = {'blend': names.index(mode) if mode in names else 0, 'opacity': float(channel(item, 'opacity', 1))}
        inputs = {}
        if kind is None:
            over['fg'] = values
        else:
            inputs['fg'] = add(item.id, ROLES[item.type][0], kind, values, item.name, record)
        if below is not None:
            inputs['bg'] = below
        below = add(item.id, 'over', 'modo_blend', over, item.name, None, inputs)
        order.append(item.id)
    graph = {'version': 1, 'root': ROOT, 'nodes': dict(builder.nodes), 'overrides': []}
    root = {'type': OUTPUT, 'parameters': {}, 'inputs': {'color': below[1]} if below else {}}
    held_root = ((old or {}).get('nodes') or {}).get(ROOT) or {}
    root['position'] = list(held_root.get('position') or [300, 50])
    graph['nodes'][ROOT] = root
    meta = {'environment': environment.id, 'version': VERSION, 'layers': list(reversed(order))}
    if kept:
        meta['kept'] = dict(kept)
    if left:
        meta['left'] = dict(left)
    graph[transfer.META_KEY] = meta
    if old:
        for identity, node in graph['nodes'].items():
            if identity in previous and 'position' in previous[identity]:
                node['position'] = list(previous[identity]['position'])
        transfer.place(graph, False)
    else:
        nodes.arrange(graph)
    return graph


def same(a, b):
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def children_for(environment, held):
    """The layers of an environment as the command reads them: those on, and those its graph holds (switched off by an
    earlier run), read as on and with the images their nodes name where their clips are gone."""
    from .host import channel
    from .layers import ordered_items
    from . import shader_tree_scene as scene_side
    found = []
    for item in ordered_items(environment):
        if item.type == 'mask':
            continue
        mine = item.id in held
        if not channel(item, 'render', 1) or not float(channel(item, 'opacity', 1)) > 0:
            continue
        if not mine and not channel(item, 'enable', 1):
            continue
        clip, folder = scene_side.image_of(item)
        stand = scene_side.placeholder_source(clip, folder)
        if mine:
            source = None
            if item.type == 'imageMap' and ((clip, folder) == (None, None) or stand):
                source = held[item.id] or stand
            found.append(scene_side._Layer(item, source, True))
        elif stand:
            found.append(scene_side._Layer(item, stand, force_on=False))
        else:
            found.append(item)
    return found


def put_back(scene, environment, held, report):
    """An environment's layers its graph holds put back in the Shader Tree, as they were: on, with their images."""
    import lx
    from . import shader_tree_scene as scene_side
    from .host import channel
    for identity, source in held.items():
        layer = _item(scene, identity)
        if layer is None:
            continue
        if layer.type == 'imageMap' and scene_side.image_of(layer) == (None, None):
            if source and scene_side.restore(scene, layer, source):
                report.restored.append(layer.name)
            else:
                report.left.append((layer.name, 'its image %s could not be loaded again; load it by hand' % ((source or {}).get('filename') or '')))
            continue
        if not channel(layer, 'enable', 1):
            lx.eval('item.channel textureLayer$enable true item:{%s}' % layer.id)
            report.restored.append(layer.name)


def _item(scene, identity):
    try:
        return scene.item(identity)
    except (LookupError, RuntimeError, AttributeError, TypeError):
        return None


def run(scene, report):
    """Move each environment's Shader Tree layers into its MoonShine graph (see the module's description), in the
    undoable step of the command that calls it, its lines in report (shader_tree_scene.Report). Returns {identity:
    item} of the layers the graphs hold now, for shader_tree_scene.unload (the environment's layers are not among the
    Render item's descendants it is handed): the clips only they use are taken out, one a material's layer uses too
    only where that layer has moved as well."""
    import lx
    from . import host, properties
    from . import shader_tree_scene as scene_side
    from .environments import collect
    freed = {}
    reading = {}
    for environment in scene.items('environment', superType=False):
        settings = properties.read(environment)
        graph = settings.get(KEY) if isinstance(settings.get(KEY), dict) else None
        if graph and foreign(graph):
            report.left.append((environment.name, 'its environment graph has nodes of its own; it is left as it is'))
            continue
        held = recorded(graph)
        reading[environment.id] = (environment, settings, graph, held, children_for(environment, held))
    warnings = []
    channels = host._CHANNELS
    forced = {}
    if channels is not None:
        # Read as on, whatever is held of the layers for the reading that holds them (as shader_tree_scene.read_layers).
        for _, _, _, _, children in reading.values():
            for child in children:
                if isinstance(child, scene_side._Layer) and child._on:
                    forced[child.id] = channels.get((child.id, 'enable'), scene_side._MISSING)
                    channels[(child.id, 'enable')] = True
    try:
        found = {entry['identity']: entry for entry in collect(scene, warnings, read=lambda item: reading[item.id][4] if item.id in reading else [])}
    finally:
        if channels is not None:
            for identity, value in forced.items():
                if value is scene_side._MISSING:
                    channels.pop((identity, 'enable'), None)
                else:
                    channels[(identity, 'enable')] = value
    for identity, (environment, settings, graph, held, children) in reading.items():
        if identity not in found:
            continue  # not rendered (hidden, dark, a Backplate's): left as it is
        entries = found[identity]['layers']
        items = {child.id: child for child in children}
        names = {child.id: child.name for child in children}
        read_ids = {entry['layer_identity'] for entry in entries}
        unread = {}
        for child in children:
            if child.id not in read_ids:
                prefix = 'Environment %s: ' % child.name
                why = next((w[len(prefix):].rstrip('.') for w in warnings if w.startswith(prefix)), None)
                unread[child.id] = why or 'the kit does not render it (a group it is in is off)'
        if not graph and not WITHOUT_IMAGES and not any(entry.get('kind') == 'image' for entry in entries):
            continue  # no image to unload: left as it is, and shown in Modo's viewport as it is
        why = refusal(entries, names)
        if why is not None:
            if graph:
                put_back(scene, environment, held, report)
                settings.pop(KEY, None)
                if scene_side.rewritten(environment, settings):
                    report.updated.append(environment.name)
            report.left.append((environment.name, why))
            continue
        kept = {i: held[i] for i in unread if i in held and held[i]}
        left = {i: why for i, why in unread.items() if i not in held}
        if not entries:
            if graph:
                put_back(scene, environment, {i: s for i, s in held.items() if i in unread}, report)
                settings.pop(KEY, None)
                if scene_side.rewritten(environment, settings):
                    report.updated.append(environment.name)
            for child_id, reason in left.items():
                report.left.append((names.get(child_id, child_id), reason))
            continue
        made = build(environment, entries, items, graph, kept, left)
        settings[KEY] = made
        if scene_side.rewritten(environment, settings):
            (report.updated if graph else report.made).append(environment.name)
            if graph:
                before = {i for i, n in graph['nodes'].items() if transfer.ours(i, n)}
                after = {i for i, n in made['nodes'].items() if transfer.ours(i, n)}
                report.removed_nodes += len(before - after)
        for entry in entries:
            layer = _item(scene, entry['layer_identity'])
            if layer is None:
                continue
            freed[layer.id] = layer
            if host.channel(layer, 'enable', 1):
                lx.eval('item.channel textureLayer$enable false item:{%s}' % layer.id)
                report.moved.append((layer.name, environment.name))
        for child_id, reason in unread.items():
            report.left.append((names.get(child_id, child_id), reason + ('; it stays switched off, its image kept in the graph' if child_id in kept else '')))
    return freed
