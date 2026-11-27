"""Shader Tree processing textures as nodes of a MoonShine graph (Move Shader Tree Textures to MoonShine Graphs): Occlusion,
Curvature, the Gradient by any input the kit follows (Slope, Incidence Angle, the distances, the screen, Back Facing,
Texture U and V under a Solid or Planar projection, Surface ID, a channel beneath), Variation by Item, Mesh Part and
Particle, Tension, the Weight Map Texture and Enhance: Modo's EasyGrad. No Modo here.

layers.collect reads each of them as a layer of kind 'gradient', whose 'gradient' record says what it reads ('input')
and how its colour (and alpha) follows: graph.bindings draws it through gradients.emit. Here it becomes a Modo Procedural
node (nodes.MAPS 'modo_procedural') holding that record, as JSON, in its gradient parameter, which nodes.emit draws through
the same gradients.emit; its alpha a second one that reads the record's alpha. What the gradient reads is made where the
scene is read, as for the layer: the scans of the materials for Occlusion, Tension, Variation and weight maps look into
the node's record (gradients.in_graph). MoonLightIPR reads the node back as the layer (moonlightipr_materials.
graph_expression).

CHECKS and FOREGROUNDS are keyed by key(layer): ('gradient', what it reads). A gradient that reads a channel beneath it
(an effect's name: Enhance: Modo's EasyGrad, a Gradient on Diffuse Amount, Roughness...) is given that channel's value
beneath it as layer['_beneath'] (a Value: ('n', node) or ('c', [r, g, b])), which is wired into the node's Input."""
import json

from . import shader_tree_transfer as transfer
from .gradients import reduced
from .textures import EFFECTS

# What a gradient may read that the graph has the same way: worked out at each point by MoonRay's maps ('@sample',
# '@curvature'), or a value on the meshes the scene's reading makes ('@vmap': Occlusion, Tension, Variation, weight maps,
# Surface ID).
SURFACE = ('@vmap', '@sample', '@curvature')
# Channels beneath that the graph does not hold as a value to read.
UNREAD = {'bump': 'a Bump height, which the graph turns into a normal and does not keep',
          'coatBump': 'a Clearcoat Bump height, which the graph turns into a normal and does not keep',
          'displace': 'a Displacement height, which the graph does not keep beneath its layers',
          'groupMask': "a group's mask, which the graph does not keep as a channel",
          'layerMask': 'a Layer Mask, which the graph does not keep as a channel'}
CHANNELS = tuple(sorted(effect for effect in EFFECTS if effect not in UNREAD))


def key(layer):
    """The key of CHECKS and FOREGROUNDS for a layer: ('gradient', what it reads), or its kind for any other layer."""
    if layer.get('kind') != 'gradient':
        return layer.get('kind')
    return ('gradient', (layer.get('gradient') or {}).get('input'))


def reads_beneath(layer):
    """The channel beneath a gradient layer that it reads (its value is layer['_beneath']), or None."""
    source = (layer.get('gradient') or {}).get('input')
    return source if source in CHANNELS else None


def what(layer):
    """The layer's kind in words, for a reason."""
    data = layer.get('gradient') or {}
    for name, words in (('occlusion', 'an Occlusion'), ('tension', 'a Tension'), ('variation', 'a Variation')):
        if name in data:
            return words
    if data.get('input') == '@curvature':
        return 'a Curvature'
    if data.get('luminance'):
        return 'an EasyGrad'
    return 'a Gradient'


def check(layer, effect):
    """Refused where the graph cannot draw this processing texture as the Shader Tree does."""
    data = layer.get('gradient')
    if not isinstance(data, dict) or not data.get('positions') or len(data.get('colors') or ()) != len(data['positions']):
        raise transfer.Refused('a gradient that could not be read')
    if 'alpha' in data and len(data['alpha']) != len(data['positions']):
        raise transfer.Refused('a gradient whose alpha could not be read')
    if effect in ('normal', 'bump', 'normalCoat', 'coatBump'):
        raise transfer.Refused('%s layer as a %s: only images move onto the normal input' % (what(layer), transfer.effect_name(effect)))
    source = data.get('input')
    if 'texture' in data:
        # The weight is made from the mesh's UVs as the material's UV map reads them; a graph's material names none.
        raise transfer.Refused('a Gradient on Texture %s by its UV map: the mesh is read with the UV map its material names, '
                               'which a graph does not' % 'UV'[int(data['texture'].get('axis', 0))])
    if source in UNREAD:
        raise transfer.Refused('%s layer that reads %s' % (what(layer), UNREAD[source]))
    if source in ('@texture_value', '@held'):
        raise transfer.Refused('a Gradient on Texture Value or Clip Distance is a constant (layers.collect)')
    if source not in SURFACE and source not in CHANNELS:
        raise transfer.Refused('%s layer driven by %s, which has no node' % (what(layer), data.get('label') or source))
    if source == '@vmap' and not data.get('vmap'):
        raise transfer.Refused('a Weight Map Texture that names no weight map')


def record(data):
    """A gradient's record as the node holds it: MoonRay's RampMap holds 10 points (gradients.reduced), which is what
    gradients.emit lays and MoonLightIPR reads (Compiler.ramp), so 10 are kept; JSON, its keys in order."""
    return json.dumps(reduced(data), sort_keys=True, separators=(',', ':'))


def foreground(builder, layer, effect, alpha_of=None):
    """(value, mask) of a processing texture: a Modo Procedural node of its gradient, and its alpha (None where it has
    none), as graph.bindings draws the layer. Its Invert is laid in the gradient's colours (one less each), as the
    Shader Tree's lays one less the gradient, which is the same at every point."""
    check(layer, effect)
    identity = layer['identity']
    data = dict(layer['gradient'])
    inputs = {}
    source = reads_beneath(layer)
    if source is not None:
        beneath = layer.get('_beneath')
        if beneath is None:
            raise transfer.Refused('%s layer that reads the %s beneath it, which was not given' % (what(layer), transfer.effect_name(source)))
        inputs['input'] = beneath
    label = layer.get('name') or identity
    tag = {'effect': effect, 'reads': str(data.get('input'))}
    alpha = data.get('alpha')
    colours = data['colors']
    if layer.get('invert'):
        colours = [[1.0 - float(v) for v in colour] for colour in colours]
    value = builder.add(identity, 'gradient', 'modo_procedural', {'gradient': record(dict(data, colors=colours)), 'output': 0}, inputs,
                        label=label, data=tag)
    mask = None
    if alpha is not None:
        # The alpha as graph.bindings lays it: the gradient again, its colours its alpha (reduced as that is).
        held = record(dict(data, colors=[[float(a)] * 3 for a in alpha]))
        mask = builder.add(identity, 'gradient_alpha', 'modo_procedural', {'gradient': held, 'output': 1}, inputs, label=label + ' alpha', data=tag)
    return value, mask


# Every input a moved gradient may read, each to the same check and node.
KEYS = [('gradient', source) for source in SURFACE + CHANNELS]
CHECKS = {name: check for name in KEYS}
FOREGROUNDS = {name: foreground for name in KEYS}


# MoonLightIPR: the node read back as the layer it was (moonlightipr_materials.graph_expression).
def layer_of(node, with_alpha=False):
    """A Modo Procedural node that holds a gradient as the layer's gradient record (kind 'gradient'), and whether it
    gives the gradient's alpha (output 1): ({'kind': 'gradient', 'gradient': data}, alpha), or None for any other node.
    The colour's record keeps its alpha only with_alpha: where the node's alpha node lays it (alpha_of_node)."""
    from .gradients import in_graph
    data = in_graph(node)
    if data is None or not data.get('positions'):
        return None
    alpha = int((node.get('parameters') or {}).get('output', 0)) == 1
    if alpha:
        if 'alpha' not in data:
            return {'kind': 'constant', 'value': [1.0, 1.0, 1.0]}, True
        data = dict(data, colors=[[float(a)] * 3 for a in data['alpha']])
    if not with_alpha:
        data.pop('alpha', None)
    return {'kind': 'gradient', 'gradient': data}, alpha


def alpha_of_node(graph, colour, mask):
    """Whether the mask node is the alpha of the colour node's gradient, as foreground makes them: the same record
    but for its colours, both read from the same input."""
    from .gradients import in_graph
    members = graph['nodes']
    a, b = members.get(colour) or {}, members.get(mask) or {}
    first, second = in_graph(a), in_graph(b)
    if first is None or second is None or 'alpha' not in first:
        return False
    if int((a.get('parameters') or {}).get('output', 0)) != 0 or int((b.get('parameters') or {}).get('output', 0)) != 1:
        return False
    if (a.get('inputs') or {}).get('input') != (b.get('inputs') or {}).get('input'):
        return False
    rest = lambda data: {k: v for k, v in data.items() if k not in ('positions', 'colors', 'alpha')}  # noqa: E731
    return rest(first) == rest(second)
