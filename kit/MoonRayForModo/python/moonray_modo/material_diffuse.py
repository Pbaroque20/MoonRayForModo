"""A MoonRay material's main colour and Modo's diffuse colour, the channel Traditional and Principled materials share and
Modo's viewport draws, kept the same. Once linked (LINKED in its settings: from when it is made, or from a colour written
to it) a material's colour is its diffuse, read from the channel (properties.read), so that undoing either undoes both in
one step: a colour edited in its form or graph goes to the diffuse in the command that writes it, and a diffuse edited in
Modo needs nothing written. A material of a scene saved before this keeps both colours until one is edited
(moonray_material_properties). A map wired into the colour leaves the colour's own value, and so the diffuse, as they are."""
from . import material_override, properties, shader_library

COLOURS = ('albedo', 'color', 'metallic_color', 'diffuse_color')
AXES = 'RGB'
LINKED = 'diffuse_linked'
_KEYS = {}


def colour_key(shader):
    """Which attribute of a material is the one that follows the diffuse, or None."""
    if shader not in _KEYS:
        attributes = shader_library.catalog().get(shader, {}).get('attributes', {})
        _KEYS[shader] = next((key for key in COLOURS if attributes.get(key, {}).get('type') == 'Rgb'), None)
    return _KEYS[shader]


def same(a, b):
    return a is not None and b is not None and all(abs(float(x) - float(y)) < 1e-5 for x, y in zip(a, b))


def stored_colour(settings):
    """(attribute, its value or None) of settings as they render; (None, None) for a material without such a colour."""
    settings = material_override.effective(settings)
    key = colour_key(settings.get('native_shader') or '')
    if key is None:
        return None, None
    value = (settings.get('native_parameters') or {}).get(key)
    return key, list(value[:3]) if isinstance(value, (list, tuple)) and len(value) >= 3 else None


def with_colour(settings, key, value):
    """Settings with this colour, in the graph's output node too: it is the same material."""
    settings = dict(settings)
    settings['native_parameters'] = dict(settings.get('native_parameters') or {}, **{key: list(value)})
    graph = settings.get('node_graph')
    if graph and graph.get('root') in graph.get('nodes', {}):
        graph = dict(graph, nodes=dict(graph['nodes']))
        root = dict(graph['nodes'][graph['root']])
        root['parameters'] = dict(root.get('parameters') or {}, **{key: list(value)})
        graph['nodes'][graph['root']] = root
        settings['node_graph'] = graph
    return settings


def diffuse(item):
    return [float(item.channel('diffCol.' + axis).get()) for axis in AXES]


def to_diffuse(item, settings):
    """The material's colour, as just written, into its diffuse. Whether it has one, and so is linked from now on."""
    if not properties.is_material(item):
        return False
    value = stored_colour(settings)[1]
    if value is None:
        return False
    if not same(value, diffuse(item)):
        for axis, part in zip(AXES, value):
            item.channel('diffCol.' + axis).set(float(part))
    return True


def read_linked(item, settings):
    """Settings as read, a linked material's colour being its diffuse as it stands."""
    if not settings.get(LINKED):
        return settings
    key = colour_key(settings.get('native_shader') or '')
    return with_colour(settings, key, diffuse(item)) if key else settings


def differs(item):
    """Whether the diffuse and the material's colour are not the same."""
    key, value = stored_colour(properties.read(item))
    return key is not None and not same(value, diffuse(item))


def from_diffuse(item):
    """The diffuse into the material's colour. Whether that changed anything."""
    if item.id in properties.LIVE or not differs(item):
        return False
    settings = properties.read(item)
    properties.write(item, with_colour(settings, stored_colour(settings)[0], diffuse(item)))
    return True
