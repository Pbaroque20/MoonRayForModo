"""The Modo Texture node: one Shader Tree texture layer as one node of a MoonShine graph, with the layer's own settings (its
source, its effect, how it is laid over what is beneath it, its value adjustments, its Texture Locator), drawn by the very
code that draws the Shader Tree layer (graph.layer_over), so that MoonRay, XPU2 and MoonLightIPR draw it as they draw the
layer. Its Background input is what lies beneath it (the layers under it, or the material's own value); its Mask input
masks it further (a Layer Mask, a group's mask); its Input is the channel a Gradient or a process reads where that is not
the one it lays on. A stack of Shader Tree layers is a chain of Modo Texture nodes, each the Background of the next.

What a layer is made of beyond its settings here (a gradient's keys and what it reads, a procedural's pattern settings, a
wireframe's, an image sequence's frames) is held whole in its Layer record (JSON, as layers.collect reads the layer); the
settings here are laid over it. No Modo here: shader_tree_transfer makes the nodes, nodes.emit draws them through draw()."""
import copy
import json
import math

KIND = 'modo_texture'
EFFECTS = ('diffCol', 'diffAmt', 'specCol', 'specAmt', 'rough', 'metallic', 'lumiCol', 'lumiAmt', 'coatAmt', 'coatRough', 'tranAmt',
           'tranCol', 'tranRough', 'dissolve', 'stencil', 'subsCol', 'subsAmt', 'aniso', 'diffRough', 'normal', 'normalCoat', 'bump',
           'coatBump', 'displace', 'ior', 'layerMask', 'groupMask', 'driverA', 'driverB', 'driverC', 'driverD')
EFFECT_LABELS = {'diffCol': 'Diffuse Color', 'diffAmt': 'Diffuse Amount', 'specCol': 'Specular Color', 'specAmt': 'Specular Amount',
                 'rough': 'Roughness', 'metallic': 'Metallic', 'lumiCol': 'Luminous Color', 'lumiAmt': 'Luminous Amount',
                 'coatAmt': 'Clearcoat Amount', 'coatRough': 'Clearcoat Roughness', 'tranAmt': 'Transparent Amount',
                 'tranCol': 'Transparent Color', 'tranRough': 'Refraction Roughness', 'dissolve': 'Dissolve', 'stencil': 'Stencil',
                 'subsCol': 'Subsurface Color', 'subsAmt': 'Subsurface Amount', 'aniso': 'Anisotropy', 'diffRough': 'Diffuse Roughness',
                 'normal': 'Normal', 'normalCoat': 'Clearcoat Normal', 'bump': 'Bump', 'coatBump': 'Clearcoat Bump', 'displace': 'Displacement',
                 'ior': 'Refractive Index', 'layerMask': 'Layer Mask', 'groupMask': 'Group Mask', 'driverA': 'Driver A', 'driverB': 'Driver B',
                 'driverC': 'Driver C', 'driverD': 'Driver D'}
KINDS = ('imageMap', 'constant', 'noise', 'checker', 'grid', 'dots', 'cellular', 'wood', 'weave', 'ripples', 'gradient', 'wireframe',
         'process', 'procedural')
BLENDS = ('normal', 'multiply', 'add', 'subtract', 'screen', 'divide', 'difference', 'darken', 'lighten', 'overlay', 'hardlight',
          'exclusion', 'softlight', 'colordodge', 'colorburn', 'normalblend')
BLEND_LABELS = ('Normal', 'Multiply', 'Add', 'Subtract', 'Screen', 'Divide', 'Difference', 'Darken', 'Lighten', 'Overlay', 'Hard Light',
                'Exclusion', 'Soft Light', 'Color Dodge', 'Color Burn', 'Normal Map Blend')
CHANNELS = ('use', 'ignore', 'only', 'red', 'green', 'blue')
CHANNEL_LABELS = ('Use Alpha', 'Ignore Alpha', 'Alpha Only', 'Red', 'Green', 'Blue')
PROJECTIONS = ('uv', 'planar', 'cubic', 'spherical', 'cylindrical', 'front', 'none')
PROJECTION_LABELS = ('UV Map', 'Planar', 'Cubic', 'Spherical', 'Cylindrical', 'Front', 'Solid')
TILES = ('repeat', 'edge', 'mirror', 'reset')
IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]

# The node's settings, with Modo's names for them where it has them; (type, default, group).
SETTINGS = {
    'bg': ('Rgb', [0.0, 0.0, 0.0], 'Layering'),
    'mask': ('Float', 1.0, 'Layering'),
    'input': ('Rgb', [0.0, 0.0, 0.0], 'Layering'),
    'effect': ('String', 'diffCol', 'Layering'),
    'blend': ('String', 'normal', 'Layering'),
    'opacity': ('Float', 1.0, 'Layering'),
    'invert': ('Bool', False, 'Layering'),
    'image_channel': ('String', 'use', 'Layering'),
    'kind': ('String', 'imageMap', 'Source'),
    'file': ('String', '', 'Source'),
    'color_space': ('String', '', 'Source'),
    'srgb': ('Bool', True, 'Source'),
    'value': ('Rgb', [1.0, 1.0, 1.0], 'Source'),
    'gamma': ('Float', 1.0, 'Adjustments'),
    'brightness': ('Float', 1.0, 'Adjustments'),
    'contrast': ('Float', 1.0, 'Adjustments'),
    'low': ('Float', 0.0, 'Adjustments'),
    'high': ('Float', 1.0, 'Adjustments'),
    'bias': ('Float', .5, 'Adjustments'),
    'gain': ('Float', .5, 'Adjustments'),
    'flip_red': ('Bool', False, 'Adjustments'),
    'flip_green': ('Bool', False, 'Adjustments'),
    'flip_blue': ('Bool', False, 'Adjustments'),
    'projection': ('String', 'uv', 'Texture Locator'),
    'uv_map': ('String', '', 'Texture Locator'),
    'axis': ('Int', 2, 'Texture Locator'),
    'locator_matrix': ('FloatVector', list(IDENTITY), 'Texture Locator'),
    'uv_matrix': ('FloatVector', [1.0, 0, 0, 0, 1.0, 0], 'Texture Locator'),
    'rotation': ('Float', 0.0, 'Texture Locator'),
    'scale': ('Vec2f', [1.0, 1.0], 'Texture Locator'),
    'tile_u': ('String', 'repeat', 'Texture Locator'),
    'tile_v': ('String', 'repeat', 'Texture Locator'),
    'layer': ('String', '{}', 'Layer record'),
}
BINDABLE = ('bg', 'mask', 'input')
COMMENTS = {
    'bg': 'What lies beneath this layer: the Modo Texture under it, or the channel\'s own value.',
    'mask': 'Where it is laid on, times its opacity: a Layer Mask, a group\'s mask (1 everywhere unwired).',
    'input': 'The channel a Gradient or a process (RegionalHSV, Process) reads where that is not the one beneath it.',
    'effect': "The layer's Effect: which of the material's channels it lays on, as Modo names them.",
    'blend': "The layer's Blend Mode.",
    'opacity': "The layer's Opacity, 0 to 1.",
    'invert': "The layer's Invert.",
    'image_channel': "Use Alpha, Ignore Alpha, Alpha Only, or one colour channel of the image.",
    'kind': 'What the layer is: an Image Map, a Constant, a procedural (Noise, Checker, Grid, Dots, Cellular, Wood, Weave, Ripples, Enhance:), a Gradient (and the processing textures: Occlusion, Curvature, Tension, Variation, weight maps), a Wireframe, a Process.',
    'file': "The image's file (path only: Modo does not hold it). A <UDIM> in its name is a UDIM set; a [####] an image sequence.",
    'color_space': "The image's colour space, as its clip's.",
    'srgb': 'The image is read as sRGB colour (Modo\'s (default) for a colour image that is not a float file).',
    'value': "A Constant layer's colour or value.",
    'gamma': "The layer's Gamma.", 'brightness': "The layer's Brightness.", 'contrast': "The layer's Contrast.",
    'low': "The layer's Low Value: what black becomes.", 'high': "The layer's High Value: what white becomes.",
    'bias': "The layer's Bias.", 'gain': "The layer's Gain.",
    'flip_red': 'Flips the red channel (as a normal map\'s Flip Red).', 'flip_green': 'Flips the green channel.', 'flip_blue': 'Flips the blue channel.',
    'projection': "The Texture Locator's Projection Type: UV Map, Planar, Cubic, Spherical, Cylindrical, Front, or Solid (through the object).",
    'uv_map': "The UV map the layer is laid on by (UV Map projection).",
    'axis': "The Texture Locator's Projection Axis: 0 X, 1 Y, 2 Z.",
    'locator_matrix': "The Texture Locator's place in the world (its world matrix, 16 numbers): its position, rotation and size.",
    'uv_matrix': "The locator's UV transform (a b c d e f: u' = a u + b v + c, v' = d u + e v + f), as its UV offset and matrix.",
    'rotation': "The locator's UV Rotation, in radians.", 'scale': "The locator's Horizontal and Vertical Repeat (Wrap).",
    'tile_u': 'Horizontal Repeat mode: repeat, edge (clamp), mirror or reset (nothing beyond the image).', 'tile_v': 'Vertical Repeat mode.',
    'layer': "The rest of the layer as the kit reads it (a gradient's keys and input, a procedural's settings, a sequence's frames...), JSON.",
}


def schema():
    """nodes.MAPS' form of the node: {setting: (type, default)}."""
    return {key: (kind, copy.deepcopy(default)) for key, (kind, default, _) in SETTINGS.items()}


def annotate(result):
    """nodes.specs' extras for the node: groups, comments and the choices of its word settings."""
    for key, spec in result.items():
        spec['group'] = SETTINGS[key][2]
        if key in COMMENTS:
            spec['comment'] = COMMENTS[key]
    result['effect']['enum'] = {EFFECT_LABELS[name]: name for name in EFFECTS}
    result['blend']['enum'] = dict(zip(BLEND_LABELS, BLENDS))
    result['image_channel']['enum'] = dict(zip(CHANNEL_LABELS, CHANNELS))
    result['projection']['enum'] = dict(zip(PROJECTION_LABELS, PROJECTIONS))
    result['tile_u']['enum'] = {name.title(): name for name in TILES}
    result['tile_v']['enum'] = {name.title(): name for name in TILES}
    result['axis']['enum'] = {'X': 0, 'Y': 1, 'Z': 2}
    result['kind']['enum'] = {name: name for name in KINDS}
    return result


def parameters_of(layer):
    """A Modo Texture node's settings for a layer read by layers.collect: the settings it has, and the rest as its record."""
    layer = dict(layer)
    for key in ('identity', 'name', 'groups', 'absolute_groups', 'mtime', 'size', 'tile_signature', '_source', '_effects', '_beneath',
                '_bumped', 'mask_target'):
        layer.pop(key, None)
    corrections = dict(layer.pop('corrections', None) or {})
    held = {'effect': layer.pop('effect', 'diffCol'), 'kind': layer.pop('kind', 'imageMap'), 'blend': layer.pop('blend', 'normal'),
            'opacity': float(layer.pop('opacity', 1)), 'invert': bool(layer.pop('invert', False)),
            'image_channel': layer.pop('image_channel', 'use' if layer.get('use_alpha') else 'ignore'),
            'gamma': float(corrections.pop('gamma', 1)), 'brightness': float(corrections.pop('brightness', 1)),
            'contrast': float(corrections.pop('contrast', 1)), 'low': float(corrections.pop('low', 0)), 'high': float(corrections.pop('high', 1)),
            'bias': float(layer.pop('bias', .5)), 'gain': float(layer.pop('gain', .5)),
            'projection': layer.pop('projection', 'uv'), 'uv_map': layer.pop('uv_map', '') or '',
            'uv_matrix': [float(v) for v in layer.pop('uv_matrix', [1, 0, 0, 0, 1, 0])], 'rotation': float(layer.pop('rotation', 0)),
            'scale': [float(v) for v in layer.pop('scale', [1, 1])], 'tile_u': layer.pop('tile_u', 'repeat'), 'tile_v': layer.pop('tile_v', 'repeat')}
    for colour in ('red', 'green', 'blue'):
        held['flip_' + colour] = bool(layer.pop('flip_' + colour, False))
    if 'path' in layer:
        held['file'] = str(layer.pop('path') or '')
        if isinstance(layer.get('sequence'), dict) and layer['sequence'].get('pattern'):
            # An image sequence: its file the pattern, each frame's found as the scene is read (shader_tree_clips).
            held['file'] = str(layer['sequence']['pattern'])
    if 'color_space' in layer:
        held['color_space'] = str(layer.pop('color_space') or '')
    if 'srgb' in layer:
        held['srgb'] = bool(layer.pop('srgb'))
    if 'value' in layer:
        value = layer.pop('value')
        held['value'] = [float(v) for v in (value if isinstance(value, (list, tuple)) else [value] * 3)][:3]
    if layer.get('locator_matrix') is not None:
        held['locator_matrix'] = [float(v) for v in layer.pop('locator_matrix')]
    if 'axis' in layer:
        axis = layer.pop('axis')
        held['axis'] = {'x': 0, 'y': 1, 'z': 2}.get(axis, axis) if isinstance(axis, str) else int(axis)
    layer.pop('coordinate_key', None)
    if corrections:
        layer['corrections_extra'] = corrections
    held['layer'] = json.dumps(layer, sort_keys=True)
    return held


def layer_of(parameters):
    """The layer a Modo Texture node draws (as layers.collect reads one) from its settings: its record, its settings laid
    over it, its coordinates' key worked out again from its locator."""
    from . import coordinates
    values = {key: copy.deepcopy(default) for key, (_, default, _) in SETTINGS.items()}
    values.update(parameters or {})
    try:
        layer = json.loads(values.get('layer') or '{}')
    except ValueError:
        raise ValueError('Modo Texture: its Layer record is not JSON')
    if not isinstance(layer, dict):
        raise ValueError('Modo Texture: its Layer record is not a record')
    corrections = dict(layer.pop('corrections_extra', None) or {})
    corrections.update(gamma=float(values['gamma']), brightness=float(values['brightness']), contrast=float(values['contrast']))
    if (float(values['low']), float(values['high'])) != (0.0, 1.0):
        corrections.update(low=float(values['low']), high=float(values['high']))
    layer.update(effect=values['effect'], kind=values['kind'], blend=values['blend'], opacity=float(values['opacity']),
                 invert=bool(values['invert']), image_channel=values['image_channel'], bias=float(values['bias']), gain=float(values['gain']),
                 projection=values['projection'], uv_map=values['uv_map'], uv_matrix=[float(v) for v in values['uv_matrix']],
                 rotation=float(values['rotation']), scale=[float(v) for v in values['scale']], tile_u=values['tile_u'], tile_v=values['tile_v'],
                 flip_red=bool(values['flip_red']), flip_green=bool(values['flip_green']), flip_blue=bool(values['flip_blue']))
    if values['kind'] == 'imageMap':
        layer['corrections'] = corrections
    elif any(abs(corrections.get(k, d) - d) > 1e-12 for k, d in (('gamma', 1), ('brightness', 1), ('contrast', 1))) or 'low' in corrections:
        layer['corrections'] = corrections
    if values['kind'] == 'imageMap':
        layer.update(path=values['file'], color_space=values['color_space'], srgb=bool(values['srgb']))
        if layer.get('sequence'):
            from .shader_tree_clips import frame_file, scene_frame
            framed = frame_file(dict(layer['sequence'], pattern=values['file']), scene_frame())
            layer['path'] = framed or values['file']
    if values['kind'] == 'constant':
        layer['value'] = [float(v) for v in values['value']]
    projection = values['projection']
    if projection not in ('uv', 'none'):
        layer['locator_matrix'] = [float(v) for v in values['locator_matrix']]
        layer['axis'] = int(values['axis'])
    elif projection == 'none':
        layer.pop('locator_matrix', None)
    if values['kind'] in ('imageMap',) or layer.get('procedural') or (values['kind'] == 'gradient' and (layer.get('gradient') or {}).get('texture')) \
            or (values['kind'] in ('checker', 'noise') and not layer.get('solid_map')):
        if projection != 'none':
            layer['coordinate_key'] = coordinates.key(layer)
    return layer


def descriptor(parameters):
    """The coordinates the node's layer lays on the meshes (coordinates.descriptors), or None."""
    layer = layer_of(parameters)
    return layer if layer.get('coordinate_key') else None


def draw(params, refs, path, definition, binding):
    """The node as MoonRay's maps (nodes.emit): its layer drawn by graph.layer_over over its Background, by its blend mode,
    opacity, alpha and Mask, as graph.bindings lays a Shader Tree layer."""
    from . import graph
    from .rdla import string, number, vector
    from .layers import BLENDS as NUMBERS
    layer = layer_of(params)
    effect = layer['effect']
    count = [0]

    def node(kind, attributes):
        name = '%s/%d' % (path, count[0])
        count[0] += 1
        held = {}
        for key, value in attributes.items():
            if value.startswith('bind('):
                unit = '1' if key in ('height', 'opacity', 'mask') or (kind == 'RampMap' and key == 'input') else (
                    'Vec3(1, 1, 1)' if key == 'input_texture_coordinates' else 'Rgb(1, 1, 1)')
                value = value[:-1] + ', ' + unit + ')'
            held[key] = value
        return 'bind(%s)' % definition(kind, name, held)

    def rgb(value):
        return vector(value if isinstance(value, (list, tuple)) else [value] * 3, 'Rgb')

    def given(key):
        if key in refs:
            return 'bind(%s)' % refs[key]
        return rgb((params or {}).get(key, SETTINGS[key][1]))

    def units(value):
        return value[:-1] + ', Rgb(1, 1, 1))' if value.startswith('bind(') else value

    beneath = given('bg')
    current = {effect: beneath}
    source = (layer.get('gradient') or {}).get('input') if layer.get('kind') == 'gradient' else None
    if source and not str(source).startswith('@') and source != effect:
        current[source] = given('input')
    if layer.get('solid_map', {}) and (layer.get('solid_map') or {}).get('process') and 'input' in refs:
        current[effect] = given('input')
    if layer.get('kind') == 'imageMap' and not layer.get('path'):
        # An image sequence at a frame where Modo shows no image (or no image chosen): nothing laid on.
        return definition('ModoTextureMap', path, {'background': units(beneath), 'foreground': units(beneath), 'blend': '0'})
    prepared = graph.prepared_layer(layer)
    if prepared is None:
        return definition('ModoTextureMap', path, {'background': units(beneath), 'foreground': units(beneath), 'blend': '0'})
    layer, solid = prepared
    drawn = graph.layer_over(layer, effect, solid, current, node, rgb)
    if drawn is None:
        return definition('ModoTextureMap', path, {'background': units(beneath), 'foreground': units(beneath), 'blend': '0'})
    foreground, mask, blend = drawn
    if 'mask' in refs:
        extra = 'bind(%s)' % refs['mask']
        mask = node('ModoTextureMap', {'background': mask, 'foreground': extra, 'blend': '1'}) if mask else extra
    elif float((params or {}).get('mask', 1.0)) != 1.0:
        extra = rgb(float(params['mask']))
        mask = node('ModoTextureMap', {'background': mask, 'foreground': extra, 'blend': '1'}) if mask else extra
    attributes = {'background': beneath, 'foreground': foreground, 'blend': str(NUMBERS[blend]), 'opacity': number(layer.get('opacity', 1))}
    if mask:
        attributes['mask'] = mask
    for key, value in list(attributes.items()):
        if value.startswith('bind('):
            attributes[key] = value[:-1] + ', ' + ('1' if key in ('opacity', 'mask') else 'Rgb(1, 1, 1)') + ')'
    return definition('ModoTextureMap', path, attributes)


def as_layer(node):
    """The Shader Tree layer a Modo Texture node is (for MoonLightIPR's reading of graphs, and the kit's scans), or None."""
    if not isinstance(node, dict) or node.get('type') != KIND:
        return None
    try:
        return layer_of(node.get('parameters') or {})
    except (ValueError, TypeError):
        return None
