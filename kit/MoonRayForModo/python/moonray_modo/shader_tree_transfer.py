"""Shader Tree image layers as nodes of a material's MoonShine graph (MoonRay > Move Shader Tree Textures to MoonShine
Graphs): what each layer becomes, how a graph is brought up to date with what its layers are now, and the constant values
a Modo material renders with. No Modo here: shader_tree_scene reads the scene and writes it.

A layer read by layers.collect (a dict: its effect, opacity, blend, image, UV placement, groups) becomes an Image node
and the nodes that lay it over what is beneath it as the Shader Tree does (graph.bindings): a Mix for its opacity and
alpha, a node for its blend mode, the colour corrections. Every node made here carries NODE_KEY with the identity of the
layer it stands for, and an identity that starts with PREFIX, so that a later run finds it again to update or remove
it; a node without both is someone's own and is never touched. Anything a graph cannot say the same way is a Refused,
with the reason, and stays in the Shader Tree."""
import copy
import math
import re
import struct

PREFIX = 'st_'
NODE_KEY = 'shader_tree'
META_KEY = 'shader_tree_transfer'
VERSION = 1

# What a layer's effect drives on a DwaBaseMaterial output, as the kit's two readings of Shader Tree layers have it:
# 'modo' for a Modo material, as moonshine.emit draws it (its colour also the metal's colour), 'native' for a material
# that already renders a graph of its own, as shader_library.emit lays layers on a native material.
INPUTS = {
    'modo': {'diffCol': ('albedo', 'metallic_color'), 'rough': ('roughness',), 'metallic': ('metallic',), 'lumiCol': ('emission',),
             'coatAmt': ('clearcoat',), 'coatRough': ('clearcoat_roughness',), 'dissolve': ('presence',),
             'normal': ('input_normal',), 'bump': ('input_normal',)},
    'native': {'diffCol': ('albedo',), 'rough': ('roughness',), 'metallic': ('metallic',), 'lumiCol': ('emission',),
               'coatAmt': ('clearcoat',), 'coatRough': ('clearcoat_roughness',), 'dissolve': ('presence',),
               'normal': ('input_normal',), 'bump': ('input_normal',)}}
EFFECT_NAMES = {'diffCol': 'Diffuse Color', 'rough': 'Roughness', 'metallic': 'Metallic', 'lumiCol': 'Luminous Color',
                'coatAmt': 'Clearcoat Amount', 'coatRough': 'Clearcoat Roughness', 'dissolve': 'Dissolve', 'normal': 'Normal',
                'bump': 'Bump', 'layerMask': 'Layer Mask', 'groupMask': 'Group Mask'}
# Shader Tree repeat modes as the Image node's address modes.
ADDRESS = {'repeat': 'periodic', 'edge': 'clamp', 'mirror': 'mirror', 'reset': 'constant'}
# Blend modes the graph has nodes for (math nodes, or a Clamp for darken and lighten). The rest stay in the Shader Tree.
# Every blend mode a Shader Tree layer has, as the Modo Blend node draws it (layers.BLENDS).
BLENDS = ('normal', 'multiply', 'add', 'subtract', 'screen', 'divide', 'difference', 'darken', 'lighten', 'overlay', 'hardlight',
          'exclusion', 'softlight', 'colordodge', 'colorburn')
BIG = 1e30


class Refused(ValueError):
    """A layer (or a material) that stays in the Shader Tree, and why, in words for an artist."""


def node_id(layer, role):
    """The identity of the node made for a layer's role: the same at every run, so a run can tell its nodes."""
    return PREFIX + re.sub(r'[^0-9A-Za-z]', '_', str(layer)) + '_' + role


def ours(identity, node):
    """Whether a graph node was made by this command (its identity and its tag both say so)."""
    return isinstance(identity, str) and identity.startswith(PREFIX) and isinstance(node, dict) and isinstance(node.get(NODE_KEY), dict)


def effect_name(effect):
    return EFFECT_NAMES.get(effect, effect)


class Builder:
    """The nodes a plan makes. A value is ('n', node identity) or ('c', [r, g, b])."""

    def __init__(self):
        self.nodes = {}

    def add(self, owner, role, kind, parameters=None, inputs=None, label=None, data=None):
        identity = node_id(owner, role)
        if identity in self.nodes:
            raise ValueError('node made twice: ' + identity)
        node = {'type': kind, 'parameters': dict(parameters or {}), 'inputs': {}, NODE_KEY: dict(data or {}, layer=str(owner), role=role)}
        for key, value in (inputs or {}).items():
            wire(node, key, value)
        if label:
            node['label'] = label
        self.nodes[identity] = node
        return ('n', identity)


def wire(node, key, value, scalar=False):
    """A value into a node's input: wired where it is a node, set where it is a number."""
    if value[0] == 'n':
        node['inputs'][key] = value[1]
        node['parameters'].pop(key, None)
    else:
        colour = [float(v) for v in value[1]]
        node['parameters'][key] = sum(colour) / 3.0 if scalar else colour


def rgb(value):
    if isinstance(value, (int, float)):
        return [float(value)] * 3
    value = [float(v) for v in value]
    return value * 3 if len(value) == 1 else value[:3]


# Image files: whether they hold an alpha channel, read from their headers. None where it cannot be told.
def file_alpha(path):
    try:
        with open(path, 'rb') as handle:
            head = handle.read(65536)
    except OSError:
        return None
    suffix = str(path).lower().rsplit('.', 1)[-1]
    if head[:8] == b'\x89PNG\r\n\x1a\n' and len(head) >= 26:
        kind = head[25]
        if kind in (4, 6):
            return True
        # A palette or a colour with a transparency chunk before the pixels.
        end = head.find(b'IDAT')
        return b'tRNS' in head[:end if end > 0 else len(head)]
    if head[:3] == b'\xff\xd8\xff':
        return False
    if head[:2] in (b'II', b'MM') and len(head) >= 8:
        return _tiff_alpha(head)
    if head[:4] == b'\x76\x2f\x31\x01':
        return _exr_alpha(head)
    if suffix in ('hdr', 'pic') or head[:10] in (b'#?RADIANCE', b'#?RGBE\n\x00\x00\x00'[:10]):
        return False
    if suffix == 'tga' and len(head) >= 18:
        return bool(head[17] & 0x0f) or head[16] == 32
    if head[:2] == b'BM' and len(head) >= 30:
        return struct.unpack('<H', head[28:30])[0] == 32
    return None


def _tiff_alpha(head):
    try:
        order = '<' if head[:2] == b'II' else '>'
        offset = struct.unpack(order + 'I', head[4:8])[0]
        if offset + 2 > len(head):
            return None
        count = struct.unpack(order + 'H', head[offset:offset + 2])[0]
        samples, extra, photometric = 1, False, None
        for index in range(count):
            at = offset + 2 + 12 * index
            if at + 12 > len(head):
                return None
            tag, kind, number = struct.unpack(order + 'HHI', head[at:at + 8])
            value = struct.unpack(order + ('H' if kind == 3 else 'I'), head[at + 8:at + (10 if kind == 3 else 12)])[0]
            if tag == 277:
                samples = value
            elif tag == 338:
                extra = True
            elif tag == 262:
                photometric = value
        colours = 3 if photometric in (2, 6) else 1
        return extra or samples > colours
    except struct.error:
        return None


def _exr_alpha(head):
    at = head.find(b'channels\x00chlist\x00')
    if at < 0:
        return None
    at += len(b'channels\x00chlist\x00') + 4
    names = []
    while at < len(head) and head[at] != 0:
        end = head.find(b'\x00', at)
        if end < 0:
            return None
        names.append(head[at:end].decode('ascii', 'replace'))
        at = end + 1 + 16
    return any(name == 'A' or name.endswith('.A') for name in names)


def placement(layer):
    """How a layer lays its image on its UV map: [a, b, c, d] and [e, f], u' = a u + b v + e and v' = c u + d v + f, as
    coordinates.transform_uv moves the UVs (its UV matrix, then its rotation, then its repeats)."""
    a, b, c, d, e, f = [float(v) for v in layer.get('uv_matrix', [1, 0, 0, 0, 1, 0])]
    angle = float(layer.get('rotation', 0))
    co, si = math.cos(angle), math.sin(angle)
    sx, sy = [float(v) for v in layer.get('scale', [1, 1])]
    matrix = [sx * (co * a - si * d), sx * (co * b - si * e), sy * (si * a + co * d), sy * (si * b + co * e)]
    offset = [sx * (co * c - si * f), sy * (si * c + co * f)]
    tidy = lambda v: 0.0 if abs(v) < 1e-12 else round(v, 12)
    return [tidy(v) for v in matrix], [tidy(v) for v in offset]


def corrections_identity(corrections):
    from .texture_controls import affine
    corrections = corrections or {}
    gain, offset = affine(corrections)
    return abs(float(corrections.get('gamma', 1)) - 1) < 1e-9 and abs(gain - 1) < 1e-9 and abs(offset) < 1e-9


class Plan:
    """What one graph's moved layers become: the nodes; each value the Shader Tree would hand the material (keys: graph.bindings'
    names, 'diffuseColor', 'roughness', 'normal'...) as a node; what each output input is wired to (connect() fills these in
    for a Modo material from its own MoonRay text; for a native one plan() does); the layers moved and the layers left
    with their reasons."""

    def __init__(self):
        self.builder = Builder()
        self.keys = {}
        self.displacement = None
        self.shader = 'DwaBaseMaterial'
        self.inputs = {}
        self.moved = []
        self.left = []


# What each effect's layers drive, by graph.bindings' names for the values it hands a material.
AMOUNTS = {'diffCol': 'diffAmt', 'specCol': 'specAmt', 'lumiCol': 'lumiAmt'}
KEYS = {'diffCol': ('diffuseColor',), 'diffAmt': ('diffuseColor',), 'specCol': ('specularColor',),
        'specAmt': ('specularColor', 'specularAmount'), 'lumiCol': ('emissiveColor',), 'lumiAmt': ('emissiveColor',),
        'dissolve': ('presence',), 'stencil': ('presence',), 'normal': ('normal',), 'bump': ('normal',),
        'normalCoat': ('coatNormal',), 'coatBump': ('coatNormal',), 'subsAmt': ('subsurfaceAmount',), 'ior': ('ior',),
        'rough': ('roughness',), 'metallic': ('metallic',), 'coatAmt': ('clearcoat',), 'coatRough': ('clearcoatRoughness',),
        'tranAmt': ('transmission',), 'tranCol': ('transmissionColor',), 'tranRough': ('refractionRoughness',),
        'subsCol': ('subsurfaceColor',), 'aniso': ('anisotropy',), 'diffRough': ('diffuseRoughness',)}
DRIVERS = ('driverA', 'driverB', 'driverC', 'driverD')
# The values a native material's output takes them as (shader_library.emit), where its name is not the same.
NATIVE_NAMES = {'diffuseColor': ('albedo',), 'emissiveColor': ('emission',), 'transmissionColor': ('transmission_color',),
                'refractionRoughness': ('independent_transmission_roughness',), 'clearcoatRoughness': ('clearcoat_roughness',),
                'subsurfaceColor': ('scattering_color',), 'specularAmount': ('specular',), 'specularColor': ('metallic_color',),
                'normal': ('input_normal',), 'diffuseRoughness': ('diffuse_roughness',)}
# Effects whose layers stay where they are and hold nothing else back: Modo moves the mesh by a Displacement layer itself for
# MoonRay and XPU2 (host.modo_displaces), which a graph's displacement would do otherwise.
STAYING = {}
BLEND_NUMBERS = {'normal': 0, 'normalblend': 0, 'multiply': 1, 'add': 2, 'subtract': 3, 'screen': 4, 'divide': 5, 'difference': 6,
                 'darken': 7, 'lighten': 8, 'overlay': 9, 'hardlight': 10, 'exclusion': 11, 'softlight': 12, 'colordodge': 13,
                 'colorburn': 14}


def plan(material, layers, bases, profile='modo', post=None, alpha_of=None, blocked=None, wired=None, strict=None, scopes=None):
    """The nodes for a material's layers (layers.collect's dicts, in the order Modo applies them, bottom first).

    material: the material's identity (base nodes are tagged with it). bases: each effect's value beneath every layer
    (graph.defaults_for). profile: 'modo' (a Modo material: its output's inputs come from connect()) or 'native' (a material
    that renders a graph or a native shader already: shader_library.emit's names). post: 'bump_strength' (the material's Bump
    Amplitude). alpha_of: path -> whether the image has an alpha channel (None: not known). blocked: {effect: reason} for
    effects that must stay in the Shader Tree whatever their layers are. wired: output inputs someone else's node drives
    already, whose layers stay.

    A layer the graph cannot draw as the Shader Tree does is left (Plan.left), and with it every layer of its effect, as a
    graph input takes over all of an effect's layers (shader_library.emit). Under strict (by default for 'modo') a
    material whose layers cannot all move is refused whole (Refused): one of its layers left in the Shader Tree would be
    drawn otherwise beside a graph. Layers of STAYING effects stay with their reason and hold nothing back."""
    post = post or {}
    alpha_of = alpha_of or (lambda path: None)
    blocked = dict(blocked or {})
    wired = set(wired or ())
    by_effect = {}
    reasons = {}
    for layer in layers:
        by_effect.setdefault(layer.get('effect'), []).append(layer)
    # Groups masked by a Group Mask inside them or a Layer Mask on them: a normal there would be mixed, which it cannot be.
    masked = {layer.get('mask_target') for layer in layers if layer.get('effect') == 'layerMask'}
    masked |= {layer['groups'][-1]['id'] for layer in layers if layer.get('effect') == 'groupMask' and layer.get('groups')}
    for layer in layers:
        effect = layer.get('effect')
        if effect == 'layerMask' or effect in STAYING:
            continue
        try:
            check(layer, effect, alpha_of, by_effect, masked)
        except Refused as exc:
            reasons[layer['identity']] = str(exc)
            blocked.setdefault(effect, str(exc))
    names = {}
    for effect in by_effect:
        for key in KEYS.get(effect, ()):
            for name in (NATIVE_NAMES.get(key, (key,)) if profile == 'native' else (key,)):
                names.setdefault(effect, set()).add(name)
    for effect in list(by_effect):
        taken = sorted(name for name in names.get(effect, ()) if name in wired)
        if taken and effect not in blocked:
            blocked[effect] = 'the graph wires %s with a node of its own, which draws in place of these layers' % taken[0].replace('_', ' ')
    # Effects that make one value go together (a colour and its amount, Dissolve and Stencil, Normal and Bump).
    for key in {k for effect in by_effect for k in KEYS.get(effect, ())}:
        sharing = [effect for effect in by_effect if key in KEYS.get(effect, ())]
        why = next((blocked[e] for e in sharing if e in blocked), None)
        if why is not None:
            for effect in sharing:
                blocked.setdefault(effect, why)
    # A layer mask goes with the layer it masks; a mask of a group goes with the group's layers.
    for layer in layers:
        if layer.get('effect') != 'layerMask':
            continue
        target = layer.get('mask_target')
        covered = [other for other in layers if other.get('identity') == target]
        grouped = [other for other in layers if any(group['id'] == target for group in other.get('groups', []))]
        effects = {other.get('effect') for other in covered + grouped}
        layer['_effects'] = effects
        try:
            if not covered and not grouped:
                raise Refused('it masks a layer that does not move with it')
            check(dict(layer, effect='layerMask'), 'layerMask', alpha_of, by_effect, masked)
        except Refused as exc:
            reasons[layer['identity']] = str(exc)
            for effect in effects:
                blocked.setdefault(effect, 'its Layer Mask %s: %s' % (layer.get('name', layer['identity']), exc))
    # A driver goes with what reads it: a Gradient on Driver A left leaves Driver A's layers too, and the other way round.
    for driver in DRIVERS:
        readers = [layer for layer in layers if (layer.get('gradient') or {}).get('input') == driver]
        if driver in blocked:
            for layer in readers:
                reasons.setdefault(layer['identity'], 'it reads %s, whose layers stay: %s' % (driver, blocked[driver]))
                blocked.setdefault(layer.get('effect'), reasons[layer['identity']])
    result = Plan()
    for layer in layers:
        effect = layer.get('effect')
        if effect in STAYING:
            result.left.append((layer['identity'], STAYING[effect]))
            continue
        effects = layer.get('_effects', {effect}) if effect == 'layerMask' else {effect}
        why = next((blocked[e] for e in effects if e in blocked), None)
        if why is not None or layer['identity'] in reasons or (effect == 'layerMask' and not effects):
            result.left.append((layer['identity'], reasons.get(layer['identity']) or why))
    refusing = [(identity, why) for identity, why in result.left if name_of_effect(layers, identity) not in STAYING]
    if refusing and (profile == 'modo' if strict is None else strict):
        raise Refused('; '.join('%s: %s' % (name_of(layers, identity), why) for identity, why in refusing))
    gone = {identity for identity, _ in result.left}
    moving = [layer for layer in layers if layer['identity'] not in gone]
    if not moving:
        return result
    build(result, material, moving, bases, profile, post, alpha_of, scopes)
    result.moved = [layer['identity'] for layer in moving]
    if profile == 'native':
        for key, value in result.keys.items():
            for name in NATIVE_NAMES.get(key, (key,)):
                result.inputs[name] = value
    return result


def name_of(layers, identity):
    return next((layer.get('name') or identity for layer in layers if layer.get('identity') == identity), identity)


def name_of_effect(layers, identity):
    return next((layer.get('effect') for layer in layers if layer.get('identity') == identity), None)


def hooks(layer):
    """(check, foreground) another module has for a layer's kind (gradients that read a vertex map, a driver or a channel;
    processing textures; image sequences and clip choices), or (None, None)."""
    from . import shader_tree_masks as masks, shader_tree_processing as processing
    key = masks.layer_key(layer)
    if key is not None:
        return masks.CHECKS.get(key), masks.FOREGROUNDS[key]
    key = processing.key(layer)
    if key in processing.FOREGROUNDS:
        return processing.CHECKS.get(key), processing.FOREGROUNDS[key]
    return None, None


MOVING_EFFECTS = set(KEYS) | set(DRIVERS) | {'layerMask', 'groupMask', 'displace'}
PROJECTIONS = ('uv', 'planar', 'cubic', 'spherical', 'cylindrical', 'front')


def check(layer, effect, alpha_of, by_effect, masked=()):
    """Refused where the graph cannot draw this layer as the Shader Tree does. A layer the kit reads (layers.collect) is
    drawn by the Modo Texture node by the Shader Tree's own code (graph.layer_over): only an effect the material is handed
    nothing for, and a kind the drawing does not know, are refused."""
    if effect not in MOVING_EFFECTS and layer.get('kind') != 'materialBase':
        raise Refused('its effect %s has no input on the graph yet' % effect_name(effect))
    kind = layer.get('kind', 'imageMap')
    if kind == 'materialBase':
        return
    if kind == 'imageMap' and not layer.get('path'):
        raise Refused('it has no image')
    if layer.get('blend', 'normal') not in BLEND_NUMBERS:
        raise Refused('its blend mode %s is not one the kit draws' % layer.get('blend'))
    for group in layer.get('groups', []):
        if group.get('blend', 'normal') not in BLEND_NUMBERS:
            raise Refused('its group blends by %s, which the kit does not draw' % group.get('blend'))


def projection(builder, layer):
    """The Modo Projection node a layer's image reads its coordinates through, or None where it lays the image on its UV map
    as it is (only repeats, which the Image node's scale gives)."""
    identity = layer['identity']
    kind = layer.get('projection', 'uv')
    matrix, offset = placement(layer)
    if kind == 'uv' and not (matrix[1] or matrix[2] or any(offset)) and not layer.get('_bumped'):
        return None
    parameters = {'projection': kind, 'uv_map': layer.get('uv_map', '') if kind == 'uv' else '',
                  'uv_matrix': [float(v) for v in layer.get('uv_matrix', [1, 0, 0, 0, 1, 0])], 'rotation': float(layer.get('rotation', 0)),
                  'scale': [float(v) for v in layer.get('scale', [1, 1])]}
    if kind != 'uv':
        axis = layer.get('axis', 2)
        parameters['axis'] = {'x': 0, 'y': 1, 'z': 2}.get(axis, axis) if isinstance(axis, str) else int(axis)
        parameters['locator_matrix'] = [float(v) for v in layer['locator_matrix']]
    return builder.add(identity, 'uv', 'modo_projection', parameters, label=(layer.get('name') or identity) + ' coordinates')


def finished(builder, layer, value):
    """A layer's value with its colour corrections and inversion after it, as graph.bindings does them."""
    identity = layer['identity']
    if layer.get('corrections') and not corrections_identity(layer.get('corrections')):
        from .texture_controls import affine
        gain, shift = affine(layer['corrections'])
        value = builder.add(identity, 'gamma', 'ColorCorrectGammaMap', {'gamma': float(layer['corrections'].get('gamma', 1))}, {'input': value})
        value = builder.add(identity, 'gain', 'ColorCorrectGainOffsetMap', {'gain': float(gain), 'offset': float(shift)}, {'input': value})
    if layer.get('invert'):
        value = builder.add(identity, 'invert', 'modo_blend', {'blend': 3}, {'bg': ('c', [1.0] * 3), 'fg': value})
    return value


def image(builder, layer, effect, alpha_of):
    """(foreground, alpha mask or None) of an image or constant layer: its value with its channel, corrections,
    flips and inversion, as graph.bindings works it out."""
    if layer.get('kind') == 'constant':
        value = rgb(layer.get('value', [1, 1, 1]))
        if layer.get('invert'):
            value = [1 - v for v in value]
        return ('c', value), None
    identity = layer['identity']
    channel = layer.get('image_channel', 'use')
    corrected = not corrections_identity(layer.get('corrections'))
    flips = [bool(layer.get('flip_' + c)) for c in ('red', 'green', 'blue')]
    invert_in_image = bool(layer.get('invert')) and not corrected and not any(flips)
    parameters = {'file': layer['path'], 'srgb': bool(layer.get('srgb', False)), 'color_space': layer.get('color_space', '') or '',
                  'uv_map': layer.get('uv_map', ''), 'uaddressmode': ADDRESS[layer.get('tile_u', 'repeat')],
                  'vaddressmode': ADDRESS[layer.get('tile_v', 'repeat')], 'default': [0.0, 0.0, 0.0],
                  'channel': {'red': 1, 'green': 2, 'blue': 3, 'only': 4}.get(channel, 0), 'invert': invert_in_image}
    try:
        from .shader_tree_clips import image_parameters
        parameters.update(image_parameters(layer) or {})
    except ImportError:
        pass
    coordinates = projection(builder, layer)
    matrix, _ = placement(layer)
    parameters['scale'] = [1.0, 1.0] if coordinates else [matrix[0], matrix[3]]
    label = layer.get('name') or identity
    value = builder.add(identity, 'image', 'image', parameters, {'texcoord': coordinates} if coordinates else None, label=label,
                        data={'source': layer.get('_source'), 'effect': effect})
    mask = None
    tiles = (layer.get('tile_u', 'repeat'), layer.get('tile_v', 'repeat'))
    alpha = alpha_of(layer['path']) if channel in ('use', 'ignore') else None
    if (channel == 'use' and alpha is not False) or 'reset' in tiles:
        # Its alpha, which the layer blends by (and nothing beyond a Reset image's edges).
        mask = builder.add(identity, 'alpha', 'image', dict(parameters, channel=4, invert=False),
                           {'texcoord': coordinates} if coordinates else None, label=label + ' alpha')
    if any(flips):
        value = builder.add(identity, 'flip', 'multiply', {}, {'in1': value, 'in2': ('c', [-1.0 if f else 1.0 for f in flips])})
        value = builder.add(identity, 'flip_offset', 'add', {}, {'in1': value, 'in2': ('c', [1.0 if f else 0.0 for f in flips])})
    if corrected:
        from .texture_controls import affine
        gain, shift = affine(layer['corrections'])
        value = builder.add(identity, 'gamma', 'ColorCorrectGammaMap', {'gamma': float(layer['corrections'].get('gamma', 1))}, {'input': value})
        value = builder.add(identity, 'gain', 'ColorCorrectGainOffsetMap', {'gain': float(gain), 'offset': float(shift)}, {'input': value})
    if layer.get('invert') and not invert_in_image:
        value = builder.add(identity, 'invert', 'modo_blend', {'blend': 3}, {'bg': ('c', [1.0] * 3), 'fg': value})
    return value, mask


def procedural(builder, layer, effect, beneath):
    """(foreground, alpha mask or None) of a procedural layer drawn through the object (Modo's Solid projection), as
    ModoProceduralMap draws it for the Shader Tree (graph.bindings)."""
    identity = layer['identity']
    solid = layer['solid_map']
    rows = [float(v) for row in solid['rows'] for v in row]
    parameters = {'pattern': int(solid['pattern']), 'type': int(solid['type']), 'settings': [float(v) for v in solid['settings']],
                  'color1': rgb(solid['color1']), 'color2': rgb(solid['color2']), 'alpha1': float(solid['alpha1']),
                  'alpha2': float(solid['alpha2']), 'rows': rows, 'output': 0, 'process': bool(solid.get('process'))}
    inputs = {'input': beneath} if solid.get('process') else None
    label = layer.get('name') or identity
    value = builder.add(identity, 'procedural', 'modo_procedural', parameters, inputs, label=label, data={'effect': effect})
    mask = None
    if float(solid['alpha1']) != 1 or float(solid['alpha2']) != 1:
        mask = builder.add(identity, 'procedural_alpha', 'modo_procedural', dict(parameters, output=1), inputs, label=label + ' alpha')
    return finished(builder, layer, value), mask


def foreground(builder, layer, effect, alpha_of, beneath=None, drivers=None):
    """(foreground, alpha mask or None) of a layer, by its kind: a hook's (shader_tree_masks, shader_tree_processing,
    shader_tree_clips), a procedural's, an image's or a constant's."""
    from .shader_tree_clips import hooks as clip_hooks
    clip_foreground = clip_hooks(layer)[1]
    if clip_foreground is not None:
        return clip_foreground(builder, layer, effect, alpha_of)
    _, hook = hooks(layer)
    if hook is not None:
        from . import shader_tree_processing as processing, shader_tree_masks as masks
        if masks.layer_key(layer) is not None:
            return hook(builder, layer, effect, alpha_of, drivers=drivers)
        source = processing.reads_beneath(layer)
        if source is not None:
            layer = dict(layer, _beneath=drivers.get(source) if drivers and source in drivers else beneath(source))
        return hook(builder, layer, effect, alpha_of)
    if layer.get('kind') not in ('imageMap', 'constant') and layer.get('solid_map'):
        return procedural(builder, layer, effect, beneath(effect))
    return image(builder, layer, effect, alpha_of)


def laid(builder, owner, role, below, above, blend, opacity, masks):
    """above laid over below as a Shader Tree layer is (ModoTextureMap: blend, opacity, mask), by a Modo Blend node."""
    masks = [mask for mask in masks if mask is not None]
    number = BLEND_NUMBERS[blend]
    opacity = float(opacity)
    if number == 0 and opacity >= 1 and not masks:
        return above
    weight = masks[0] if masks else None
    for index, mask in enumerate(masks[1:]):
        weight = builder.add(owner, '%s_mask%d' % (role, index + 1), 'modo_blend', {'blend': 1}, {'bg': weight, 'fg': mask})
    node = builder.add(owner, role, 'modo_blend', {'blend': number, 'opacity': opacity}, {'bg': below, 'fg': above})
    if weight is not None:
        wire(builder.nodes[node[1]], 'mask', weight, scalar=True)
    return node


def texture(builder, layer, below, mask=None, read=None):
    """A layer as one Modo Texture node over what lies beneath it (below), further masked by mask (a Layer Mask's node),
    reading read where it is a gradient or a process on another channel."""
    from . import modo_texture
    parameters = modo_texture.parameters_of(layer)
    inputs = {'bg': below}
    if mask is not None:
        inputs['mask'] = mask
    if read is not None:
        inputs['input'] = read
    label = layer.get('name') or layer['identity']
    return builder.add(layer['identity'], 'texture', modo_texture.KIND, parameters, inputs, label=label,
                       data={'source': layer.get('_source'), 'effect': layer.get('effect')})


def build(result, material, layers, bases, profile, post, alpha_of, scopes=None):
    """scopes: {nested mask's identity: what shader_tree_masks.mask_value reads of it}: the layers inside a mask for some
    of the material's surfaces laid on there alone, by a Modo Mask of it."""
    builder = result.builder
    scopes = scopes or {}
    current = {}
    stack = []           # (group, values before it, effects used before it)
    used = set()
    pending = {}         # layer masks by what they mask

    def base(effect):
        held = bases.get(effect, 1.0 if effect in ('groupMask', 'layerMask') else ([.5, .5, 1.0] if effect in ('normal', 'normalCoat') else 0.0))
        return current.get(effect, ('c', rgb(held)))

    def close():
        nonlocal used
        group, before, used_before = stack.pop()
        mask = current.get('groupMask') if 'groupMask' in used else None
        external = pending.pop(group['id'], None)
        if group['id'] in scopes:
            from .shader_tree_masks import mask_value
            held = mask_value(builder, scopes[group['id']])
            if held[0] == 'n':
                external = builder.add(group['id'], 'scope_mask', 'modo_blend', {'blend': 1}, {'bg': external, 'fg': held}) if external else held
        for effect in sorted(used - {'groupMask'}):
            inner = current[effect]
            below = before.get(effect, base_of(effect, before))
            if group.get('invert') and effect in ('diffCol', 'specCol', 'lumiCol', 'tranCol', 'subsCol'):
                inner = builder.add(group['id'], 'group_invert_' + effect, 'modo_blend', {'blend': 3}, {'bg': ('c', [1.0] * 3), 'fg': inner})
            current[effect] = laid(builder, group['id'], 'group_' + effect, below, inner, group.get('blend', 'normal'),
                                   group.get('opacity', 1), [mask, external])
        if 'groupMask' in before:
            current['groupMask'] = before['groupMask']
        else:
            current.pop('groupMask', None)
        used = used_before | (used - {'groupMask'})

    def base_of(effect, held):
        value = bases.get(effect, [.5, .5, 1.0] if effect in ('normal', 'normalCoat') else 0.0)
        return held.get(effect, ('c', rgb(value)))

    def select(path):
        nonlocal used
        common = 0
        while common < min(len(path), len(stack)) and path[common]['id'] == stack[common][0]['id']:
            common += 1
        while len(stack) > common:
            close()
        for group in path[common:]:
            stack.append((dict(group), dict(current), used))
            used = set()
            current.pop('groupMask', None)

    tiled = {'bump': 1.0, 'coatBump': 1.0}
    from . import graph as shader_tree, textures as kinds
    whole_glow = shader_tree.glows_whole(layers)
    for layer in layers:
        select(layer.get('groups', []))
        effect = layer['effect']
        identity = layer['identity']
        if layer.get('kind') == 'materialBase':
            row_mask = pending.pop(identity, None)
            values = shader_tree.defaults_for(layer['material'])
            if whole_glow:
                shader_tree.glow_whole(values)
            blend = layer.get('blend', 'normal')
            for target, value in values.items():
                if target in {'groupMask', 'layerMask'} | kinds.INTERNAL_EFFECTS:
                    continue
                if target == 'displace' and target not in used and not any(value if isinstance(value, (list, tuple)) else [value]):
                    continue
                if layer.get('invert') and target in kinds.COLOR_EFFECTS:
                    value = [1 - v for v in value] if isinstance(value, list) else 1 - value
                below = base(target)
                opacity = float(layer.get('opacity', 1))
                if below[0] == 'c' and row_mask is None:
                    # Numbers over numbers: the number they come to (ModoTextureMap's arithmetic).
                    mixed = _blend(BLEND_NUMBERS[blend], rgb(below[1]), rgb(value))
                    alpha = max(0.0, min(1.0, opacity))
                    current[target] = ('c', [x * (1 - alpha) + y * alpha for x, y in zip(rgb(below[1]), mixed)])
                else:
                    current[target] = laid(builder, identity, 'row_' + target, below, ('c', rgb(value)), blend, opacity, [row_mask])
                used.add(target)
            continue
        if effect in tiled and layer.get('projection', 'uv') == 'uv':
            from .coordinates import affine
            try:
                a = affine(layer)[0]
                tiled[effect] = max(tiled[effect], (a[0] * a[0] + a[2] * a[2]) ** .5, (a[1] * a[1] + a[3] * a[3]) ** .5)
            except (ValueError, TypeError, KeyError):
                pass
        source = (layer.get('gradient') or {}).get('input') if layer.get('kind') == 'gradient' else None
        read = base(source) if source and not str(source).startswith('@') and source != effect else None
        mask = pending.pop(identity, None)
        if effect == 'layerMask':
            pending[layer.get('mask_target', '')] = texture(builder, layer, ('c', [1.0] * 3), mask, read)
            continue
        current[effect] = texture(builder, layer, base(effect), mask, read)
        used.add(effect)
    select([])
    outputs(result, material, current, used, bases, profile, post, tiled)


def outputs(result, material, current, used, bases, profile, post, tiled=None):
    """Each value the material is handed (graph.bindings' names) as a node: Plan.keys; and a displacement's height
    (Plan.displacement), which the graph's displacement output takes."""
    builder = result.builder
    tiled = tiled or {}

    def value(effect):
        return current.get(effect, ('c', rgb(bases.get(effect, 0.0))))

    def node(held, role):
        # A value only constants make is a Constant node, so that the output's own value is left as it was.
        if held[0] == 'n':
            return held
        return builder.add(material, role, 'constant', {'value': rgb(held[1])})

    keys = {}
    for colour, amount in AMOUNTS.items():
        if not ({colour, amount} & used):
            continue
        key = KEYS[colour][0]
        held = value(colour)
        if amount in used or profile == 'modo' or abs(float(rgb(bases.get(amount, 1))[0]) - 1) > 1e-9:
            share = value(amount)
            if not (share[0] == 'c' and all(abs(v - 1) < 1e-12 for v in rgb(share[1]))):
                held = builder.add(material, key + '_amount', 'modo_blend', {'blend': 1}, {'bg': held, 'fg': share})
        keys[key] = held
    if 'specAmt' in used:
        keys['specularAmount'] = value('specAmt')
    if {'dissolve', 'stencil'} & used:
        held = None
        if 'dissolve' in used:
            held = builder.add(material, 'presence_dissolve', 'modo_blend', {'blend': 3}, {'bg': ('c', [1.0] * 3), 'fg': value('dissolve')})
        if 'stencil' in used:
            kept = builder.add(material, 'presence_stencil', 'modo_blend', {'blend': 3}, {'bg': ('c', [1.0] * 3), 'fg': value('stencil')})
            held = builder.add(material, 'presence', 'modo_blend', {'blend': 1}, {'bg': held, 'fg': kept}) if held else kept
        keys['presence'] = held
    for normal, bump, key, role in (('normal', 'bump', 'normal', 'normal'), ('normalCoat', 'coatBump', 'coatNormal', 'coat_normal')):
        if not ({normal, bump} & used):
            continue
        # As graph.bindings: the normal beneath (its layers turned to the surface each), the height read to either side.
        steps = tiled.get(bump, 1.0)
        held = builder.add(material, role, 'bump', {'amplitude': float(post.get('bump_strength', .005)) if bump in used else 0.0,
                                                    'step': .001 / steps if bump in used and steps > 1 else 0.0}, {})
        if bump in used:
            wire(builder.nodes[held[1]], 'height', value(bump), scalar=True)
        if normal in used:
            wire(builder.nodes[held[1]], 'normal', value(normal))
        keys[key] = held
    if 'displace' in used:
        # As the kit writes the Shader Tree's displacement (rdla): the surface moved along its normal by the height times
        # the material's Displacement Distance.
        held = builder.add(material, 'displacement', 'NormalDisplacement', {'height_multiplier': float(post.get('displacement_distance', .02))}, {})
        wire(builder.nodes[held[1]], 'height', value('displace'), scalar=True)
        result.displacement = held[1]
    for effect in sorted(used):
        if effect in AMOUNTS or effect in AMOUNTS.values() or effect in ('dissolve', 'stencil', 'normal', 'bump', 'normalCoat', 'coatBump',
                                                                        'groupMask', 'layerMask', 'displace') or effect in DRIVERS:
            continue
        keys[KEYS[effect][0]] = value(effect)
    result.keys = {key: node(held, 'value_' + key)[1] for key, held in keys.items() if held[0] == 'n' or not post.get('whole')}


SENTINEL = '@shader_tree/'


def sentinels(lines_bindings, keys):
    """graph.bindings' result with each value the moved layers make put as a marker (SENTINEL + its name), for the material's
    MoonRay text to say what it does with each (connect)."""
    marked = dict(lines_bindings)
    for key in keys:
        held = marked.get(key)
        found = re.match(r'^bind\(\w+\("(?:[^"\\]|\\.)*"\),\s*(.*)\)$', held or '', re.S)
        unit = found.group(1) if found else ('1' if key not in (
            'diffuseColor', 'specularColor', 'emissiveColor', 'transmissionColor', 'subsurfaceColor', 'normal') else 'Rgb(1, 1, 1)')
        marked[key] = 'bind(ModoTextureMap("%s%s"), %s)' % (SENTINEL, key, unit)
    return marked


def marked_text(rows, keys):
    """What the kit writes for a Modo material's stack (moonshine.emit_stack over its rows, its moved layers in its own) with
    the values those layers make put as markers (sentinels), for connect()."""
    from . import graph, moonshine, absorption
    real = graph.bindings

    def marking(material, index, lines, *args, **named):
        return sentinels(real(material, index, lines, *args, **named), keys)
    graph.bindings = marking
    try:
        lines = []
        moonshine.emit_stack([absorption.surface(row) for row in rows], 'shader_tree_transfer', 0, lines)
    finally:
        graph.bindings = real
    return lines


def connect(result, material, lines, path, shader='DwaBaseMaterial'):
    """A Modo material's output wired as its MoonRay text (moonshine.emit, written with sentinels() in place of the moved
    layers' values) has it: each input that reads a marker wired to the nodes the text puts between the value and the
    input (the material's curves, Fresnel weights, ramps...), copied as graph nodes (Modo Blend for ModoTextureMap's blends,
    the map itself otherwise); and the output's values as the text has them where nothing varies. Returns those values."""
    from . import shader_library, map_library
    found = objects(lines)
    mixed = found.get(path + '/sss_mix')
    layered = False
    share = None
    if mixed is not None:
        try:
            share = sum(evaluate(found, literal(mixed[1].get('mask', '1')))) / 3
        except NotConstant:
            # Subsurface Amount from layers: the material mixed with itself without its scattering by their value, as the
            # kit writes it (moonshine.emit): a DwaLayerMaterial output of the two.
            share = None
            layered = True
        if share is not None and share <= 1e-6:
            path = path + '/surface'
        elif share is not None and share < 1 - 1e-6:
            # A Subsurface Amount between none and all (a plain Modo material's, Skin at 60%): the same two materials,
            # mixed by that amount as the output's mask.
            layered = True
    if path not in found or found[path][0] != shader:
        raise NotConstant('the material is written as more than one %s' % shader)
    schema = shader_library.catalog()[shader]['attributes']
    builder = result.builder
    made = {}

    def marked(name):
        return name.startswith(SENTINEL)

    def reaches(value, seen=()):
        if isinstance(value, tuple) and value[0] in ('bind', 'ref'):
            name = value[1]
            if marked(name):
                return True
            if name in seen or name not in found:
                return False
            return any(reaches(literal(text), seen + (name,)) for text in found[name][1].values()
                       if not text.startswith('"'))
        return False

    def copy_of(name):
        """The graph node for an object of the text that a marker reaches."""
        if marked(name):
            return ('n', result.keys[name[len(SENTINEL):]])
        if name in made:
            return made[name]
        kind, attributes = found[name]
        role = 'post_' + re.sub(r'[^0-9A-Za-z]', '_', name.strip('/'))
        if kind == 'ModoTextureMap':
            if int(literal(attributes.get('mode', '0'))) != 0:
                raise NotConstant('a ModoTextureMap mode %s after a layer' % attributes.get('mode'))
            node_kind, rename = 'modo_blend', {'background': 'bg', 'foreground': 'fg', 'blend': 'blend', 'opacity': 'opacity', 'mask': 'mask'}
            spec = {key: {'type': 'Rgb' if key in ('bg', 'fg') else ('Int' if key == 'blend' else 'Float')} for key in rename.values()}
        elif kind == 'ModoNormalMap':
            source = literal(attributes['input'])
            if isinstance(source, tuple) and marked(source[1]):
                made[name] = ('n', result.keys[source[1][len(SENTINEL):]])
                return made[name]
            raise NotConstant('a normal map the moved layers do not make')
        elif kind in map_library.catalog():
            node_kind, rename = kind, {key: key for key in attributes}
            spec = map_library.catalog()[kind]['attributes']
        else:
            raise NotConstant('a %s after a layer' % kind)
        parameters, inputs = {}, {}
        for key, text in attributes.items():
            target = rename.get(key)
            if target is None:
                raise NotConstant('%s.%s' % (kind, key))
            value = literal(text)
            kind_of = spec[target]['type']
            if reaches(value):
                inputs[target] = copy_of(value[1])
                if isinstance(value, tuple) and value[0] == 'bind' and value[2] not in (1.0, [1.0, 1.0, 1.0]):
                    raise NotConstant('a value bound at another weight than 1')
            elif kind_of.endswith('Vector'):
                parameters[target] = [rgb(v) if kind_of.startswith('Rgb') else (int(v) if kind_of.startswith('Int') else float(v)) for v in value]
            elif kind_of == 'Int':
                parameters[target] = int(round(evaluate(found, value)[0]))
            elif kind_of == 'Bool':
                parameters[target] = bool(value) if isinstance(value, bool) else bool(evaluate(found, value)[0])
            elif kind_of == 'Rgb':
                parameters[target] = evaluate(found, value)
            elif kind_of == 'String':
                parameters[target] = value
            else:
                parameters[target] = sum(evaluate(found, value)) / 3.0
        made[name] = builder.add(material, role, node_kind, parameters, inputs)
        return made[name]

    def transcribed(name, inputs):
        values = {}
        for key, text in found[name][1].items():
            spec = schema.get(key)
            if spec is None:
                continue
            value = literal(text)
            if reaches(value):
                inputs[key] = copy_of(value[1])[1]
                continue
            if spec['type'] in ('SceneObject*', 'String') or spec['type'].endswith('Vector') or (isinstance(value, tuple) and value[0] == 'ref'):
                continue
            kind = spec['type']
            if kind == 'Bool':
                values[key] = bool(value) if isinstance(value, bool) else bool(evaluate(found, value)[0])
            elif kind == 'Int':
                values[key] = int(round(evaluate(found, value)[0]))
            elif kind == 'Float':
                values[key] = sum(evaluate(found, value)) / 3.0
            elif kind == 'Rgb':
                values[key] = evaluate(found, value)
            elif kind in ('Vec2f', 'Vec3f', 'Vec4f') and isinstance(value, list):
                values[key] = [float(v) for v in value]
        return values

    if not layered:
        result.shader = shader
        return transcribed(path, result.inputs)
    # The two materials as nodes of the graph, its output the mix of them.
    result.shader = 'DwaLayerMaterial'
    for part, name in (('material_A', path), ('material_B', path + '/surface')):
        inputs = {}
        values = transcribed(name, inputs)
        held = builder.add(material, 'surface_' + part[-1], shader, values, {key: ('n', value) for key, value in inputs.items()})
        result.inputs[part] = held[1]
    if share is not None:
        return {'mask': float(share)}
    weight = literal(mixed[1]['mask'])
    if not reaches(weight):
        raise NotConstant('a subsurface mix the moved layers do not make')
    result.inputs['mask'] = copy_of(weight[1])[1]
    return {}


# Bringing a graph up to date.
def merged(graph, result, meta, created=False):
    """The graph with this command's nodes as the plan has them now: its old ones gone (a layer that is gone, its nodes
    with it), the plan's in place, the output's inputs this command wired rewired or let go. Someone's own nodes, and
    inputs wired to them, are left as they were. Where a node was before, it stays."""
    graph = copy.deepcopy(graph)
    members = graph['nodes']
    root = members[graph['root']]
    before = {identity: node for identity, node in members.items() if ours(identity, node)}
    for identity in before:
        del members[identity]
    held = dict(graph.get(META_KEY) or {})
    owned = set(held.get('inputs') or ())
    root_inputs = root.setdefault('inputs', {})
    for name in list(root_inputs):
        if name in owned or root_inputs[name] in before:
            del root_inputs[name]
    for identity, node in result.builder.nodes.items():
        node = copy.deepcopy(node)
        if identity in before and 'position' in before[identity]:
            node['position'] = list(before[identity]['position'])
        members[identity] = node
    root_inputs.update(result.inputs)
    if getattr(result, 'displacement', None):
        graph['displacement'] = result.displacement
    elif graph.get('displacement') in before:
        graph.pop('displacement', None)
    held.update(meta)
    held['version'] = VERSION
    held['inputs'] = sorted(result.inputs)
    # A graph this command made always keeps its record, a plain Modo material's (no layers, no nodes of its own) too:
    # MoonShine -> Shader Tree (shader_tree_revert) reads from it that the material was a Modo material.
    if result.inputs or result.builder.nodes or created:
        graph[META_KEY] = held
    elif META_KEY in graph:
        graph[META_KEY] = held
    place(graph, created)
    return graph


def place(graph, created):
    """Where new nodes sit: a new graph laid out whole (nodes.arrange); otherwise this command's new nodes in columns to
    the left of the output by how far they are from it, beneath what is there already."""
    from . import nodes
    members = graph['nodes']
    if created:
        nodes.arrange(graph)
        return
    loose = [identity for identity, node in members.items() if ours(identity, node) and 'position' not in node]
    if not loose:
        return
    depth = {graph['root']: 0}
    pending = [graph['root']]
    while pending:
        key = pending.pop(0)
        for source in (members[key].get('inputs') or {}).values():
            if source in members and source not in depth:
                depth[source] = depth[key] + 1
                pending.append(source)
    root = members[graph['root']].get('position') or [300, 50]
    lowest = max([node.get('position', [0, 0])[1] for identity, node in members.items() if 'position' in node] or [0])
    rows = {}
    for identity in sorted(loose, key=lambda key: (depth.get(key, 99), key)):
        level = depth.get(identity, 8)
        rows[level] = rows.get(level, 0) + 1
        members[identity]['position'] = [root[0] - 260.0 * level, lowest + 140 + 120 * (rows[level] - 1)]


def our_layers(graph):
    """{layer identity: its node's record (what the layer's image was)} of this command's layer nodes: its Modo Texture
    nodes (and the Image nodes of graphs made before them)."""
    found = {}
    for identity, node in ((graph or {}).get('nodes') or {}).items():
        if ours(identity, node) and node[NODE_KEY].get('role') in ('image', 'texture'):
            found[node[NODE_KEY]['layer']] = dict(node[NODE_KEY], file=(node.get('parameters') or {}).get('file'))
    return found


# A Modo material's values as the Shader Tree draws it, read back from what moonshine.emit writes for it with no layers.
class NotConstant(ValueError):
    pass


def objects(lines):
    """{name: (kind, {attribute: text})} of the objects written in RDLA lines."""
    text = '\n'.join(lines)
    found = {}
    for match in re.finditer(r'(?:materials\[[^\]]*\]\s*=\s*)?(\w+)\("((?:[^"\\]|\\.)*)"\)\s*\{', text):
        kind, name = match.group(1), match.group(2)
        at = match.end()
        attributes, at = _attributes(text, at)
        if attributes is not None:
            found[name] = (kind, attributes)
    return found


def _attributes(text, at):
    attributes = {}
    while True:
        while at < len(text) and text[at] in ' \t\r\n,':
            at += 1
        if at >= len(text):
            return None, at
        if text[at] == '}':
            return attributes, at + 1
        key = re.match(r'\["([^"]+)"\]\s*=\s*', text[at:])
        if not key:
            return None, at
        at += key.end()
        start, depth, quoted = at, 0, False
        while at < len(text):
            c = text[at]
            if quoted:
                if c == '\\':
                    at += 1
                elif c == '"':
                    quoted = False
            elif c == '"':
                quoted = True
            elif c in '({':
                depth += 1
            elif c in ')}':
                if depth == 0:
                    break
                depth -= 1
            elif c == ',' and depth == 0:
                break
            elif c == '\n' and depth == 0:
                break
            at += 1
        attributes[key.group(1)] = text[start:at].strip()


def literal(text):
    text = text.strip()
    if text in ('true', 'false'):
        return text == 'true'
    if re.fullmatch(r'[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?', text):
        return float(text)
    match = re.fullmatch(r'(Rgb|Rgba|Vec2|Vec3|Vec4)\((.*)\)', text)
    if match:
        values = [float(v) for v in match.group(2).split(',')]
        return values * 3 if match.group(1) == 'Rgb' and len(values) == 1 else values
    if text.startswith('{') and text.endswith('}'):
        inner = text[1:-1].strip()
        return [literal(part) for part in _split(inner)] if inner else []
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    match = re.fullmatch(r'bind\((\w+)\("((?:[^"\\]|\\.)*)"\)(?:\s*,\s*(.*))?\)', text, re.S)
    if match:
        return ('bind', match.group(2), literal(match.group(3)) if match.group(3) else 1.0)
    match = re.fullmatch(r'(\w+)\("((?:[^"\\]|\\.)*)"\)', text)
    if match:
        return ('ref', match.group(2))
    if text == 'undef()':
        return None
    raise NotConstant('not a value: ' + text[:80])


def _split(text):
    parts, depth, start = [], 0, 0
    for at, c in enumerate(text):
        if c in '({':
            depth += 1
        elif c in ')}':
            depth -= 1
        elif c == ',' and depth == 0:
            parts.append(text[start:at])
            start = at + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def evaluate(found, value, seen=()):
    """A colour of a value: a literal, or a map of constants (ModoTextureMap's blends, OpMap's arithmetic, a RampMap of
    its input). NotConstant for anything that varies over the surface."""
    if isinstance(value, bool):
        return [float(value)] * 3
    if isinstance(value, (int, float)):
        return [float(value)] * 3
    if isinstance(value, list):
        return rgb(value)
    if isinstance(value, tuple) and value[0] == 'bind':
        name, unit = value[1], value[2]
        if name in seen:
            raise NotConstant('a cycle')
        colour = sample(found, name, seen + (name,))
        unit = rgb(unit) if isinstance(unit, (list, int, float)) else [1.0] * 3
        return [a * b for a, b in zip(colour, unit)]
    raise NotConstant('not a constant')


def sample(found, name, seen):
    if name not in found:
        raise NotConstant('no object ' + name)
    kind, attributes = found[name]
    get = lambda key, default: evaluate(found, literal(attributes[key]), seen) if key in attributes else rgb(default)
    if kind == 'ModoTextureMap':
        if int(literal(attributes.get('mode', '0'))) != 0:
            raise NotConstant('a ModoTextureMap mode')
        a, b = get('background', 0.0), get('foreground', 1.0)
        mode = int(literal(attributes.get('blend', '0')))
        mixed = _blend(mode, a, b)
        alpha = max(0.0, min(1.0, sum(get('opacity', 1.0)) / 3 * sum(get('mask', 1.0)) / 3))
        return [x * (1 - alpha) + y * alpha for x, y in zip(a, mixed)]
    if kind == 'OpMap':
        a = [v * sum(get('op1_factor', 1.0)) / 3 for v in get('op1', 1.0)]
        b = [v * sum(get('op2_factor', 1.0)) / 3 for v in get('op2', 1.0)]
        operation = int(literal(attributes.get('operation', '0')))
        ops = {0: lambda x, y: x + y, 1: lambda x, y: x - y, 2: lambda x, y: x * y, 3: lambda x, y: x / (y if abs(y) > 1e-7 else 1e-7),
               4: max, 5: min}
        if operation not in ops:
            raise NotConstant('OpMap operation %d' % operation)
        result = [ops[operation](x, y) for x, y in zip(a, b)]
        if literal(attributes.get('clamp', 'false')) is True:
            result = [max(0.0, min(1.0, v)) for v in result]
        return result
    if kind == 'RampMap':
        if int(literal(attributes.get('ramp_type', '0'))) != 8:
            raise NotConstant('a RampMap laid out in space')
        at = sum(get('input', 1.0)) / 3
        positions = [float(v) for v in literal(attributes['positions'])]
        colours = [rgb(v) for v in literal(attributes['colors'])]
        kinds = [int(v) for v in literal(attributes.get('interpolations', '{}'))] or [1] * len(positions)
        if any(k != 1 for k in kinds):
            raise NotConstant('a RampMap that is not linear')
        return ramp_at(positions, colours, at)
    if kind == 'ConstantColorMap':
        return get('color_value', 1.0)
    if kind == 'ColorCorrectGammaMap':
        g = sum(get('gamma', 1.0)) / 3
        return [max(0.0, v) ** (1.0 / g) if g > 0 else v for v in get('input', 1.0)]
    if kind == 'ColorCorrectGainOffsetMap':
        gain, offset = sum(get('gain', 1.0)) / 3, sum(get('offset', 0.0)) / 3
        return [v * gain + offset for v in get('input', 1.0)]
    raise NotConstant('a ' + kind)


def ramp_at(positions, colours, at):
    if at <= positions[0]:
        return list(colours[0])
    for (p0, c0), (p1, c1) in zip(zip(positions, colours), zip(positions[1:], colours[1:])):
        if at <= p1:
            t = 0.0 if p1 <= p0 else (at - p0) / (p1 - p0)
            return [x + (y - x) * t for x, y in zip(c0, c1)]
    return list(colours[-1])


def _blend(mode, a, b):
    if mode == 0:
        return list(b)
    one = lambda f: [f(x, y) for x, y in zip(a, b)]
    table = {1: lambda x, y: x * y, 2: lambda x, y: x + y, 3: lambda x, y: x - y, 4: lambda x, y: 1 - (1 - x) * (1 - y),
             5: lambda x, y: x / max(1e-6, y), 6: lambda x, y: abs(x - y), 7: min, 8: max,
             9: lambda x, y: 2 * x * y if x < .5 else 1 - 2 * (1 - x) * (1 - y),
             10: lambda x, y: 2 * x * y if y < .5 else 1 - 2 * (1 - x) * (1 - y),
             11: lambda x, y: x + y - 2 * x * y,
             12: lambda x, y: x - (1 - 2 * y) * x * (1 - x) if y <= .5 else
                 x + (2 * y - 1) * ((((16 * x - 12) * x + 4) * x if x <= .25 else math.sqrt(max(0.0, x))) - x),
             13: lambda x, y: 1.0 if y >= 1 else min(1.0, x / max(1e-6, 1 - y)),
             14: lambda x, y: 0.0 if y <= 0 else 1 - min(1.0, (1 - x) / max(1e-6, y))}
    if mode not in table:
        raise NotConstant('blend %d' % mode)
    return one(table[mode])


def constant_parameters(lines, path, shader='DwaBaseMaterial'):
    """(parameters, ramps) of the material at path in lines: each attribute of the output as the number or colour it
    comes to, typed as the shader's catalog says, and the ramps a roughness goes through ('roughness_ramp',
    'specular_ramp', 'specular_colour'), for a graph whose roughness an image drives. NotConstant where any value
    varies over the surface (it should not: no layer is written) or the material is more than one shader."""
    from . import shader_library
    found = objects(lines)
    mixed = found.get(path + '/sss_mix')
    if mixed is not None:
        # Mixed by how much it scatters beneath its surface (moonshine.emit): a share that is all or nothing is the one
        # material or the other.
        share = sum(evaluate(found, literal(mixed[1].get('mask', '1')))) / 3
        if share >= 1 - 1e-6:
            pass
        elif share <= 1e-6:
            path = path + '/surface'
        else:
            raise NotConstant('the material is mixed with itself by its subsurface amount')
    if path not in found or found[path][0] != shader:
        raise NotConstant('the material is written as more than one %s' % shader)
    schema = shader_library.catalog()[shader]['attributes']
    parameters = {}
    for key, text in found[path][1].items():
        spec = schema.get(key)
        if spec is None or spec['type'] in ('SceneObject*', 'String') or spec['type'].endswith('Vector'):
            continue
        value = literal(text)
        if isinstance(value, tuple) and value[0] == 'ref':
            continue
        kind = spec['type']
        if kind == 'Bool':
            parameters[key] = bool(value) if isinstance(value, bool) else bool(evaluate(found, value)[0])
        elif kind == 'Int':
            parameters[key] = int(round(evaluate(found, value)[0]))
        elif kind == 'Float':
            colour = evaluate(found, value)
            parameters[key] = sum(colour) / 3.0
        elif kind == 'Rgb':
            parameters[key] = evaluate(found, value)
        elif kind in ('Vec2f', 'Vec3f', 'Vec4f'):
            if not isinstance(value, list):
                raise NotConstant('a bound vector')
            parameters[key] = [float(v) for v in value]
    ramps = {}
    for name, (kind, attributes) in found.items():
        if kind != 'RampMap':
            continue
        points = list(zip([float(v) for v in literal(attributes['positions'])], [rgb(v)[0] for v in literal(attributes['colors'])]))
        if name.startswith('/modo/roughness/'):
            ramps['roughness_ramp'] = points
        elif name.startswith('/modo/strength/'):
            ramps['specular_ramp'] = points
    if 'specular_ramp' in ramps:
        fresnel = next((name for name in found if name.startswith('/modo/fresnel/')), None)
        if fresnel is None:
            ramps.pop('specular_ramp')
        else:
            ramps['specular_colour'] = evaluate(found, literal(found[fresnel][1]['background']))
    return parameters, ramps
