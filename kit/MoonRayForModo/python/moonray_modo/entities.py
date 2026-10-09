"""MoonRay's own scene objects as Modo items: lights, light filters, cameras, shapes and volumes.

An entity is a locator that carries a MoonRay class name and the attributes the user has set,
in the item's MoonRay tag. Unset attributes keep MoonRay's defaults. This module holds the
schema, reads the items, writes them into the RDLA scene, and says which of them MoonLight
can show. Only collect() touches Modo.
"""
import json
import math
from functools import lru_cache
from pathlib import Path

ITEM_TYPE = 'moonray.entity'      # the first, generic item; kept so that scenes holding it still load
TYPE_PREFIX = 'moonray.'           # each class has its own item type: moonray.EnvLight, ...
CHANNEL_PREFIX = 'mr_'             # keeps MoonRay's attribute names clear of the locator's own channels
VECTORS = {'Rgb': ('color', '.R', '.G', '.B'), 'Vec2f': ('xy', '.X', '.Y'), 'Vec3f': ('xyz', '.X', '.Y', '.Z')}
CLASS_KEY, PARAMETERS_KEY = 'entity_class', 'entity_parameters'
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
SIZES = {'Rgb': 3, 'Rgba': 4, 'Vec2f': 2, 'Vec3f': 3, 'Vec4f': 4}
CONSTRUCTORS = {'Rgb': 'Rgb', 'Rgba': 'Rgba', 'Vec2f': 'Vec2', 'Vec3f': 'Vec3', 'Vec4f': 'Vec4'}
# The lights MoonLight shows, with the snapshot keys their sizes go under.
PREVIEW_LIGHTS = {'DistantLight': {'angular_extent': 'angle'}, 'SphereLight': {'radius': 'radius'},
                  'RectLight': {'width': 'width', 'height': 'height'}, 'DiskLight': {'radius': 'radius'},
                  'SpotLight': {'lens_radius': 'radius', 'outer_cone_angle': 'cone'},
                  'CylinderLight': {'radius': 'radius', 'height': 'height'}, 'PortalLight': {'width': 'width', 'height': 'height'}}


# What a newly added item starts with where MoonRay's own defaults show nothing. MoonRay divides a
# light's intensity by its area, so its default of 1 is close to black, and its default sphere
# of radius 1 swallows whatever stands near it.
STARTING = {'EnvLight': {'modo_replace_environment': True, 'visible_in_camera': 1},   # 1 is force on: seen behind the scene
            'SphereLight': {'intensity': 50.0, 'radius': .1}, 'RectLight': {'intensity': 50.0},
            'DiskLight': {'intensity': 50.0, 'radius': .5}, 'SpotLight': {'intensity': 50.0, 'lens_radius': .05},
            'CylinderLight': {'intensity': 50.0, 'radius': .05}, 'MeshLight': {'intensity': 50.0}}


@lru_cache(maxsize=1)
def catalog():
    return json.loads(Path(__file__).with_name('entity_catalog.json').read_text(encoding='utf-8'))


def classes(category=None):
    return sorted(name for name, entry in catalog().items() if category in (None, entry['category']))


def typed(value, spec):
    """Check one authored value against its attribute; return it in the form that is stored."""
    kind = spec['type']
    if kind == 'SceneObject*':
        if not isinstance(value, str) or not value.strip():
            raise ValueError('Expected the name of a MoonRay item')
        return value.strip()
    if kind in ('SceneObjectVector', 'SceneObjectIndexable'):
        names = value if isinstance(value, list) else [value]
        if not names or not all(isinstance(v, str) and v.strip() for v in names):
            raise ValueError('Expected the names of MoonRay items')
        return [v.strip() for v in names]
    if kind.endswith('Vector'):
        if not isinstance(value, list):
            raise ValueError('Expected a list')
        return [typed(v, dict(spec, type=kind[:-6])) for v in value]
    if kind == 'Bool':
        if type(value) is not bool:
            raise ValueError('Expected true or false')
        return value
    if kind == 'String':
        if not isinstance(value, str):
            raise ValueError('Expected text')
        return value
    if kind in SIZES:
        if not isinstance(value, list) or len(value) != SIZES[kind]:
            raise ValueError('Expected %d components' % SIZES[kind])
        return [typed(v, {'type': 'Float'}) for v in value]
    if kind not in ('Float', 'Double', 'Int', 'Long') or type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError('Expected a finite ' + kind)
    if kind in ('Int', 'Long') and int(value) != value:
        raise ValueError('Expected a whole number')
    if 'enum' in spec and int(value) not in spec['enum'].values():
        raise ValueError('Unknown choice')
    return int(value) if kind in ('Int', 'Long') else float(value)


def validate(name, parameters):
    if name not in catalog():
        raise ValueError('Unknown MoonRay class: ' + str(name))
    if not isinstance(parameters, dict):
        raise ValueError('MoonRay item parameters must be an object')
    attributes = catalog()[name]['attributes']
    result = {}
    for key, value in parameters.items():
        if key not in attributes:
            raise ValueError('Unknown %s attribute: %s' % (name, key))
        result[key] = typed(value, attributes[key])
    return result


def item_type(name):
    return TYPE_PREFIX + name


def display(name):
    """A class as the user sees it: dwEnvLight, for DreamWorks, as the kit names its other MoonRay things."""
    return 'dw' + name


def replaces_environment(scene):
    """Whether a MoonRay environment light is set to stand in for Modo's own environments."""
    return any(e['class'] == 'EnvLight' and e.get('parameters', {}).get('modo_replace_environment') and value(e, 'on')
               for e in checked(scene))


def hint_name(label):
    """A popup choice as Modo stores it: no spaces or punctuation."""
    import re
    return re.sub(r'[^A-Za-z0-9]+', '_', label).strip('_').lower() or 'choice'


def channels(name):
    """How each attribute of a class is held on its Modo item, in attribute order.

    Returns (attribute, channel name, kind, default, choices). kind is boolean, integer, float,
    color, xy, xyz or string; choices are (value, popup name) pairs for an integer shown as a
    popup. default is MoonRay's where the schema gives one, otherwise a neutral value, and an
    attribute still at its default is left out of the scene so MoonRay keeps its own.
    """
    result = []
    for key, spec in sorted(catalog()[name]['attributes'].items()):
        kind, default, choices = spec['type'], spec.get('default'), None
        if kind == 'Bool':
            plan, default = 'boolean', bool(default)
        elif kind in ('Int', 'Long'):
            plan, default = 'integer', int(default or 0)
            if 'enum' in spec:
                choices, used = [], set()
                for label, number in sorted(spec['enum'].items(), key=lambda entry: entry[1]):
                    internal = hint_name(label)
                    while internal in used:
                        internal += '_'
                    used.add(internal)
                    choices.append((int(number), internal))
                if default not in [number for number, _ in choices]:
                    default = choices[0][0]
        elif kind in ('Float', 'Double'):
            plan, default = 'float', float(default or 0)
        elif kind in VECTORS:
            plan, default = VECTORS[kind][0], [float(v) for v in (default or [0.0] * SIZES[kind])]
        else:
            # Text, file paths, the names of other MoonRay items, and lists typed as [a, b, c].
            plan, default = 'string', ''
        result.append((key, CHANNEL_PREFIX + key, plan, default, choices))
    return result


INTERFACES = {'LIGHT': 'light', 'LIGHTFILTER': 'lightfilter', 'CAMERA': 'camera', 'GEOMETRY': 'geometry', 'VOLUME': 'volume'}
# Lengths, angles and sizes cannot be negative; MoonRay's schema seldom says so itself.
NEVER_NEGATIVE = ('radius', 'width', 'height', 'distance', 'angular_extent', 'cone_angle', 'near', 'far', 'focal', 'spread')


def choice_labels(name, key):
    """(value, popup name, label) for an attribute with named values, in value order."""
    spec = catalog()[name]['attributes'][key]
    internal = dict(next(choices for k, _, _, _, choices in channels(name) if k == key))
    return [(number, internal[number], ' '.join(word.capitalize() for word in label.replace('_', ' ').split()))
            for label, number in sorted(spec['enum'].items(), key=lambda entry: entry[1])]


# Attributes nobody should have to type. Each is shown as a list to choose from, or not at all.
VDB_GRIDS = ('density_grid', 'emission_grid', 'velocity_grid', 'density_grid_name')
# Names MoonRay matches up between items: shown as the names already in use, with a way to add one.
LABELS = ('label', 'shadow_receiver_label')
# What cannot be chosen from anything in a Modo scene, or is given to MoonRay some other way:
# a camera inside a medium, a map shader by name, the parts of a mesh light, and shadow exclusion's own syntax.
UNSHOWN = ('medium_geometry', 'medium_material', 'map_shader', 'texture_map', 'parts', 'shadow_exclusion_mappings')


def presentation(name, key):
    """How an attribute is shown in its item's properties, so that none is a box to type in.

    'choice' named values; 'pick' one other item; 'list' several other items; 'ramp' one of the three
    lists of a ramp, which the ramp editor edits together; 'file' a file chosen in a dialog; 'grid' a
    grid of the item's VDB file; 'label' a name shared between items; 'material' a material of the scene;
    'uv' a UV map of the scene; 'hidden' not shown; 'channel' the item's own channel, which is a number,
    a colour or a switch.
    """
    spec = catalog()[name]['attributes'][key]
    kind = spec['type']
    if key in UNSHOWN:
        return 'hidden'
    if any(key in ramp[1:] for ramp in RAMPS.get(name, [])):
        return 'ramp'
    if 'enum' in spec and kind in ('Int', 'Long'):
        return 'choice'
    category = reference_category(spec)
    if category:
        return 'pick' if kind == 'SceneObject*' else 'list'
    if kind.startswith('SceneObject') or kind.endswith('Vector'):
        return 'hidden'
    if kind == 'String':
        # MoonRay marks most of its file attributes as such, but not all.
        if spec.get('filename') or key.endswith(('_image', '_map', '_file_name')):
            return 'file'
        if key in VDB_GRIDS:
            return 'grid'
        if key in LABELS:
            return 'label'
        if key == 'modo_material':
            return 'material'
        if key == 'uv_attribute':
            return 'uv'
        return 'hidden'
    return 'channel'


def vdb_grids(path):
    """The names of the grids in an OpenVDB file, read from its header; none if it cannot be read."""
    import struct
    try:
        with open(path, 'rb') as stream:
            def number(code):
                size = struct.calcsize(code)
                return struct.unpack(code, stream.read(size))[0]

            def text():
                return stream.read(number('<I')).decode('utf-8', 'replace')
            if stream.read(8) != b' BDV\x00\x00\x00\x00':
                return []
            version = number('<I')
            if version >= 211:
                stream.read(8)                      # the library's version
            offsets = bool(number('<B')) if version >= 212 else False
            if 220 <= version < 222:
                stream.read(1)                      # compression, held per file in these versions
            stream.read(36)                         # the file's identifier
            for _ in range(number('<I')):           # the file's own notes: name, type, value
                text(); text(); stream.read(number('<I'))
            names = []
            for _ in range(min(number('<i'), 256)):
                name = text()
                text()                              # the grid's type
                if version >= 216:
                    text()                          # the grid it is an instance of
                stream.read(16)
                end = number('<q')
                # Two grids of one name are told apart by a suffix after a separator.
                names.append(name.split('\x1e')[0])
                if not offsets:
                    break
                stream.seek(end)
            return [n for i, n in enumerate(names) if n and n not in names[:i]]
    except (OSError, struct.error, ValueError, UnicodeError):
        return []


def reference_category(spec):
    """The kind of MoonRay item an attribute names, if it names one at all."""
    if not spec['type'].startswith('SceneObject'):
        return None
    key = spec['name']
    # Some attributes do not declare what they point at; their names do.
    named = ('lightfilter' if key == 'light_filters' else 'camera' if key.endswith('camera') or key == 'projector'
             else 'volume' if key.endswith('volume') else None)
    return INTERFACES.get(spec.get('interface')) or named


def limits(name, key):
    """The lowest a number may be, or None. The ranges in MoonRay's schema are slider ranges, not
    limits, so only a floor of zero is taken from them or from what the attribute measures."""
    spec = catalog()[name]['attributes'][key]
    if spec['type'] not in ('Float', 'Double') or key == 'offset_radius':
        return None
    measured = any(key == word or key.endswith('_' + word) for word in NEVER_NEGATIVE)
    return 0.0 if measured or spec.get('min') == 0 else None


def parse_list(text, kind):
    """A list typed into a text field: [1, 2, 3] as before, or just 1 2 3; colours and vectors
    as 1 0 0; 0 1 0 or as numbers in a row."""
    import re
    text = text.strip()
    if text.startswith('['):
        return json.loads(text)
    element = kind[:-6]
    if element == 'String':
        return [part.strip() for part in text.split(',') if part.strip()]
    if element == 'Bool':
        words = [w.lower() for w in re.split(r'[\s,;]+', text) if w]
        if not all(w in ('true', 'false', '1', '0', 'on', 'off') for w in words):
            raise ValueError('expected on or off values')
        return [w in ('true', '1', 'on') for w in words]
    def numbers(part):
        return [float(w) for w in re.split(r'[\s,]+', part.strip()) if w]
    if element in SIZES:
        size = SIZES[element]
        if ';' in text:
            return [numbers(part) for part in text.split(';') if part.strip()]
        flat = numbers(text)
        if len(flat) % size:
            raise ValueError('expected %d numbers for each entry' % size)
        return [flat[i:i + size] for i in range(0, len(flat), size)]
    values = numbers(text.replace(';', ' '))
    return [int(v) for v in values] if element in ('Int', 'Long') and all(v == int(v) for v in values) else values


def from_channels(name, read):
    """The attributes the user has changed, from read(channel name) for each of the item's channels."""
    attributes = catalog()[name]['attributes']
    parameters = {}
    for key, channel, plan, default, choices in channels(name):
        spec = attributes[key]
        if plan in ('color', 'xy', 'xyz'):
            value = [float(read(channel + suffix)) for suffix in VECTORS[spec['type']][1:]]
            changed = any(abs(a - b) > 1e-9 for a, b in zip(value, default))
        elif plan == 'string':
            text = str(read(channel) or '').strip()
            changed = bool(text)
            if not changed:
                continue
            if spec['type'] in ('String', 'SceneObject*'):
                value = text
            elif spec['type'].startswith('SceneObject'):
                value = [part.strip() for part in text.split(',') if part.strip()]
            else:
                try:
                    value = parse_list(text, spec['type'])
                except ValueError as exc:
                    raise ValueError('%s must be a list such as 1 2 3 (%s)' % (key, exc))
        else:
            value = read(channel)
            floor = limits(name, key)
            if floor is not None:
                # The form keeps such numbers from going negative; one set some other way is brought back.
                value = max(float(value), floor)
            if choices and isinstance(value, str):
                # Modo hands a popup back by name.
                value = {internal: number for number, internal in choices}.get(value, default)
            value = bool(value) if plan == 'boolean' else int(value) if plan == 'integer' else float(value)
            changed = value != default if plan != 'float' else abs(value - default) > 1e-9
        if changed:
            parameters[key] = value
    return validate(name, parameters)


def is_entity(item):
    from . import properties
    return bool(properties.read(item).get(CLASS_KEY))


def collect(scene, warnings):
    """Read every MoonRay item in the Modo scene that is set to render."""
    from . import properties
    from .host import render_visible, world_matrix
    result = []
    # Each class has an item type whose channels are its attributes.
    for name in classes():
        try:
            typed_items = list(scene.items(item_type(name), superType=False))
        except (LookupError, RuntimeError, TypeError):
            continue
        for item in typed_items:
            try:
                if render_visible(item):
                    from . import primitive_attributes
                    result.append({'identity': item.id, 'name': item.name, 'class': name, 'matrix': world_matrix(item),
                                   'parameters': from_channels(name, lambda channel: item.channel(channel).get()),
                                   'attributes': primitive_attributes.read(item)})
            except (ValueError, LookupError, RuntimeError, AttributeError, TypeError) as exc:
                warnings.append('MoonRay item %s: %s.' % (getattr(item, 'name', '?'), exc))
    # The first, generic item kept its class and values in a tag; plain locators may carry one too.
    items = []
    for kind in (ITEM_TYPE, 'locator'):
        try:
            items += list(scene.items(kind, superType=False))
        except (LookupError, RuntimeError, TypeError):
            pass
    for item in items:
        try:
            settings = properties.read(item)
            name = settings.get(CLASS_KEY)
            if not name or not render_visible(item):
                continue
            result.append({'identity': item.id, 'name': item.name, 'class': name, 'matrix': world_matrix(item),
                           'parameters': validate(name, settings.get(PARAMETERS_KEY, {}))})
        except (ValueError, LookupError, RuntimeError) as exc:
            warnings.append('MoonRay item %s: %s.' % (getattr(item, 'name', '?'), exc))
    return result


def value(entity, key):
    """An attribute as authored, or MoonRay's default when it was left alone."""
    if key in entity['parameters']:
        return entity['parameters'][key]
    return catalog()[entity['class']]['attributes'].get(key, {}).get('default')


def checked(scene):
    """The scene's entities, validated again: a snapshot may come from a file or another version."""
    result = []
    for entity in scene.get('entities', []):
        result.append(dict(entity, parameters=validate(entity['class'], entity.get('parameters', {}))))
    return result


# ---- Ramps -------------------------------------------------------------------------------------

# The attributes that together make one ramp, per class: (label, positions, values, interpolations).
# MoonRay holds each ramp as three lists of equal length.
RAMPS = {'ColorRampLightFilter': [('Colour ramp', 'distances', 'colors', 'interpolation_types')],
         'RodLightFilter': [('Falloff ramp', 'ramp_in_distances', 'ramp_out_distances', 'ramp_interpolation_types')],
         'VdbLightFilter': [('Density remap', 'density_remap_inputs', 'density_remap_outputs', 'density_remap_interpolation_types')],
         'BaseVolume': [('Attenuation ramp', 'attenuation_distances', 'attenuation_colors', 'attenuation_interpolations'),
                        ('Density ramp', 'density_distances', 'densities', 'density_interpolations'),
                        ('Diffuse ramp', 'diffuse_distances', 'diffuse_colors', 'diffuse_interpolations')]}
INTERPOLATIONS = ('None', 'Linear', 'Exponential Up', 'Exponential Down', 'Smooth', 'Catmull-Rom', 'Monotone Cubic')


def ramp_eval(positions, values, interpolations, x):
    """A ramp at x, by MoonRay's rules: the span's interpolation is that of its left stop, and
    outside the stops the end values hold. Values are numbers or lists of them. The two cubic
    modes are both drawn as a Catmull-Rom curve through the stops."""
    order = sorted(range(len(positions)), key=lambda i: positions[i])
    stops = [positions[i] for i in order]
    listed = isinstance(values[0], (list, tuple))
    held = [list(values[i]) if listed else [values[i]] for i in order]
    modes = [interpolations[i] for i in order]
    def out(value):
        return value if listed else value[0]
    if x <= stops[0]:
        return out(held[0])
    if x >= stops[-1]:
        return out(held[-1])
    left = max(i for i in range(len(stops)) if stops[i] <= x)
    span = stops[left + 1] - stops[left]
    if span <= 0:
        return out(held[left])
    u = (x - stops[left]) / span
    mode = modes[left]
    if mode >= 5:
        before, after = held[max(left - 1, 0)], held[min(left + 2, len(held) - 1)]
        a, b = held[left], held[left + 1]
        return out([.5 * ((2 * b0) + (-a0 + c0) * u + (2 * a0 - 5 * b0 + 4 * c0 - d0) * u * u + (-a0 + 3 * b0 - 3 * c0 + d0) * u ** 3)
                    for a0, b0, c0, d0 in zip(before, a, b, after)])
    weight = (0.0 if mode == 0 else u if mode == 1 else u * u if mode == 2 else 1 - (1 - u) ** 2 if mode == 3
              else math.sin(u * math.pi / 2))
    return out([a + weight * (b - a) for a, b in zip(held[left], held[left + 1])])


def ramp_lists(entity, positions, values, interpolations, fallback):
    """One ramp's three lists as authored; MoonRay's fallback when they are missing or do not match."""
    lists = [entity['parameters'].get(key) for key in (positions, values, interpolations)]
    if not all(lists) or len({len(v) for v in lists}) != 1:
        return fallback
    return lists


# ---- Light filters -----------------------------------------------------------------------------

def inverse_rows(matrix):
    """Rows that take a world point into an item's own space: three of (x, y, z, offset)."""
    from .coordinates import inverse
    inv = inverse(matrix)
    return [[inv[0 * 4 + i], inv[1 * 4 + i], inv[2 * 4 + i], inv[12 + i]] for i in range(3)]


def filter_records(entities, names, owner, warnings):
    """The light filters named on a light, as MoonLight applies them: an intensity scale, a
    decay over distance, or a colour ramp. The kinds it cannot apply are named in warnings."""
    from .working_space import color as working_color
    records = []
    for name in names or ():
        found = [e for e in entities if name in (e['name'], e['identity']) and catalog()[e['class']]['category'] == 'lightfilter']
        if len(found) != 1:
            warnings.append('%s names light filter %s, which is %s.' % (owner, name, 'missing' if not found else 'the name of several items'))
            continue
        entity = found[0]
        kind = entity['class']
        if not value(entity, 'on'):
            continue
        if kind == 'IntensityLightFilter':
            scale = [c * float(value(entity, 'intensity')) * 2 ** float(value(entity, 'exposure')) for c in working_color(value(entity, 'color'))]
            if value(entity, 'invert'):
                scale = [1 / c if c else c for c in scale]
            if value(entity, 'light_path_selection'):
                warnings.append('MoonLight applies %s to every light path.' % entity['name'])
            records.append({'kind': 'intensity', 'scale': scale})
        elif kind == 'DecayLightFilter':
            records.append({'kind': 'decay', 'near': bool(value(entity, 'falloff_near')), 'far': bool(value(entity, 'falloff_far')),
                            'distances': [float(value(entity, key)) for key in ('near_start', 'near_end', 'far_start', 'far_end')]})
        elif kind == 'ColorRampLightFilter':
            begin, end = float(value(entity, 'begin_distance')), float(value(entity, 'end_distance'))
            if begin >= end:
                begin, end = 0.0, 1.0
            stops, colors, modes = ramp_lists(entity, 'distances', 'colors', 'interpolation_types', [[0.0, 1.0], [[1, 1, 1], [0, 0, 0]], [1, 1]])
            records.append({'kind': 'ramp', 'directional': value(entity, 'mode') == 1, 'mirror': value(entity, 'wrap_mode') == 1,
                            'rows': inverse_rows(entity.get('matrix', IDENTITY)) if value(entity, 'use_xform') else None,
                            'begin': begin, 'end': end, 'intensity': float(value(entity, 'intensity')),
                            'density': min(1.0, max(0.0, float(value(entity, 'density')))),
                            'positions': stops, 'colors': colors, 'interpolations': modes})
        else:
            warnings.append('MoonLight does not apply %s (%s on %s).' % (kind, entity['name'], owner))
    return records


# ---- Mesh lights -------------------------------------------------------------------------------

def mesh_lights(scene, warnings=None):
    """Hand each MeshLight item to the mesh it names.

    MoonRay's MeshLight emits only from a real mesh, so the item names a Modo mesh. The plugin
    already knows how to make a mesh emit, from its Object controls; this fills those in from
    the item's colour, intensity and exposure and takes the item out of the list, so the rest
    of the export and MoonLight treat it as any other emitting mesh.
    """
    lit = [e for e in scene.get('entities', []) if e['class'] == 'MeshLight']
    if not lit:
        return scene
    warnings = [] if warnings is None else warnings
    production = dict(scene.get('production', {}))
    objects = dict(production.get('objects', {}))
    for entity in checked({'entities': lit}):
        label, target = entity['name'], entity['parameters'].get('geometry', '')
        if not value(entity, 'on'):
            continue
        owners = {mesh.get('source_item') or str(mesh.get('identity', '')).split('|')[0] for mesh in scene.get('meshes', [])
                  if target and target in (mesh.get('name'), mesh.get('source_item'), str(mesh.get('identity', '')).split('|')[0])}
        if len(owners) != 1:
            warnings.append('Mesh light %s needs the name of one Modo mesh as its geometry%s.' % (label, ', not %s' % target if target else ''))
            continue
        if entity['parameters'].get('light_filters') or entity['parameters'].get('map_shader'):
            warnings.append('Mesh light %s is exported without its light filters and map shader.' % label)
        owner = owners.pop()
        objects[owner] = dict(objects.get(owner, {}), mesh_light=True, light_color=value(entity, 'color'),
                              light_intensity=float(value(entity, 'intensity')) * 2 ** float(value(entity, 'exposure')))
    production['objects'] = objects
    return dict(scene, production=production, entities=[e for e in scene['entities'] if e['class'] != 'MeshLight'])


# ---- Viewport proxies --------------------------------------------------------------------------

def proxy(name, number):
    """The wireframe that stands for an item in the viewport, in the item's own space.

    number(attribute) gives the current value of one of the class's numeric attributes. Returns
    a list of ('circles', [(centre, normal scaled to the radius), ...]), ('boxes', [(corner,
    opposite corner), ...]), ('lines', [point, point, ...]) in pairs, and ('strip', [points]).
    MoonRay's flat lights and its cameras face down their local -Z axis; a cylinder light
    stands along Y.
    """
    category = catalog()[name]['category']
    def rectangle(width, height, z=0.0):
        x, y = width / 2, height / 2
        return [(-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z), (-x, -y, z)]
    def arrow(length, x=0.0, y=0.0):
        head = length * .2
        return [(x, y, 0), (x, y, -length), (x, y, -length), (x + head * .4, y, -length + head),
                (x, y, -length), (x - head * .4, y, -length + head)]
    def arc(radius, plane, steps=16):
        """Half a circle over the top: in the XY plane, or the ZY plane."""
        points = [(math.cos(math.pi * i / steps) * radius, math.sin(math.pi * i / steps) * radius) for i in range(steps + 1)]
        return [(a, b, 0.0) if plane == 'xy' else (0.0, b, a) for a, b in points]
    if name == 'SphereLight':
        r = max(number('radius'), 1e-4)
        return [('circles', [((0, 0, 0), (r, 0, 0)), ((0, 0, 0), (0, r, 0)), ((0, 0, 0), (0, 0, r))])]
    if name == 'EnvLight':
        # A dome: the horizon, two arcs over the top, and a mark for up.
        return [('circles', [((0, 0, 0), (0, 1, 0))]), ('strip', arc(1.0, 'xy')), ('strip', arc(1.0, 'zy')),
                ('lines', [(0, 1, 0), (0, 1.25, 0)])]
    if name == 'DistantLight':
        return [('circles', [((0, 0, 0), (0, 0, .25))]),
                ('lines', arrow(1.0) + arrow(.8, .18, 0) + arrow(.8, -.18, 0) + arrow(.8, 0, .18) + arrow(.8, 0, -.18))]
    if name in ('RectLight', 'PortalLight'):
        w, h = max(number('width'), 1e-4), max(number('height'), 1e-4)
        shapes = [('strip', rectangle(w, h)), ('lines', arrow(min(w, h) * .5))]
        if name == 'PortalLight':
            # An opening rather than a surface: crossed corner to corner.
            shapes.append(('lines', [(-w / 2, -h / 2, 0), (w / 2, h / 2, 0), (-w / 2, h / 2, 0), (w / 2, -h / 2, 0)]))
        return shapes
    if name == 'DiskLight':
        r = max(number('radius'), 1e-4)
        return [('circles', [((0, 0, 0), (0, 0, r))]), ('lines', arrow(r))]
    if name == 'SpotLight':
        lens = max(number('lens_radius'), 1e-4)
        reach = 1.0
        def spread(angle):
            return lens + reach * math.tan(math.radians(min(max(angle, 0.0), 170.0)) / 2)
        wide = spread(number('outer_cone_angle'))
        # The outer cone, and inside it the ring where the falloff begins.
        full = spread(min(number('inner_cone_angle'), number('outer_cone_angle')))
        return [('circles', [((0, 0, 0), (0, 0, lens)), ((0, 0, -reach), (0, 0, wide)), ((0, 0, -reach), (0, 0, max(full, 1e-4)))]),
                ('lines', [(lens, 0, 0), (wide, 0, -reach), (-lens, 0, 0), (-wide, 0, -reach),
                           (0, lens, 0), (0, wide, -reach), (0, -lens, 0), (0, -wide, -reach)])]
    if name == 'CylinderLight':
        r, half = max(number('radius'), 1e-4), max(number('height'), 1e-4) / 2
        return [('circles', [((0, half, 0), (0, r, 0)), ((0, -half, 0), (0, r, 0))]),
                ('lines', [(r, -half, 0), (r, half, 0), (-r, -half, 0), (-r, half, 0), (0, -half, r), (0, half, r), (0, -half, -r), (0, half, -r)])]
    if name == 'BoxGeometry':
        x, y, z = (max(number('size.' + axis), 1e-4) / 2 for axis in 'XYZ')
        return [('boxes', [((-x, -y, -z), (x, y, z))])]
    if name == 'SphereGeometry':
        r = max(number('radius'), 1e-4)
        return [('circles', [((0, 0, 0), (0, r, 0)), ((0, 0, 0), (0, 0, r))])]
    if name == 'RodLightFilter':
        x, y, z = (max(number(key), 1e-4) / 2 for key in ('width', 'height', 'depth'))
        return [('boxes', [((-x, -y, -z), (x, y, z))])]
    if name == 'BarnDoorLightFilter':
        return [('strip', rectangle(max(number('projector_width'), 1e-4), max(number('projector_height'), 1e-4))), ('lines', arrow(.5))]
    if category == 'camera':
        # A viewing pyramid down -Z, with a mark for which way is up.
        w, h, d = .5, .28, .8
        far = rectangle(w * 2, h * 2, -d)
        return [('strip', far), ('lines', [point for corner in far[:4] for point in ((0, 0, 0), corner)]
                                 + [(-w * .3, h, -d), (0, h * 1.5, -d), (0, h * 1.5, -d), (w * .3, h, -d)])]
    if category == 'geometry':
        return [('boxes', [((-.5, -.5, -.5), (.5, .5, .5))])]
    # Filters and volumes with no shape of their own: a small diamond.
    s = .2
    return [('strip', [(s, 0, 0), (0, s, 0), (-s, 0, 0), (0, -s, 0), (s, 0, 0)]), ('strip', [(0, s, 0), (0, 0, s), (0, -s, 0), (0, 0, -s), (0, s, 0)])]


def proxy_inputs(name):
    """The numeric attributes proxy() asks for, as (asked name, channel name)."""
    wanted = {'SphereLight': ['radius'], 'RectLight': ['width', 'height'], 'PortalLight': ['width', 'height'], 'DiskLight': ['radius'],
              'SpotLight': ['lens_radius', 'outer_cone_angle', 'inner_cone_angle'], 'CylinderLight': ['radius', 'height'], 'SphereGeometry': ['radius'],
              'RodLightFilter': ['width', 'height', 'depth'], 'BarnDoorLightFilter': ['projector_width', 'projector_height']}.get(name, [])
    inputs = [(key, CHANNEL_PREFIX + key) for key in wanted]
    if name == 'BoxGeometry':
        inputs = [('size.' + axis, CHANNEL_PREFIX + 'size.' + axis) for axis in 'XYZ']
    return inputs


# ---- RDLA --------------------------------------------------------------------------------------

def reference(entities, name, interface, owner):
    """The RDLA expression for another MoonRay item, named as the user typed it."""
    category = {'LIGHT': 'light', 'LIGHTFILTER': 'lightfilter', 'CAMERA': 'camera', 'GEOMETRY': 'geometry', 'VOLUME': 'volume'}.get(interface)
    found = [e for e in entities if name in (e['name'], e['identity'])
             and (category is None or catalog()[e['class']]['category'] == category)]
    if len(found) != 1:
        raise ValueError('%s refers to %s, which is %s' % (owner, name, 'not a MoonRay item of the right kind' if not found
                                                         else 'the name of more than one MoonRay item'))
    return '%s(%s)' % (found[0]['class'], _string('/modo/entity/' + found[0]['identity']))


def _string(text):
    from .rdla import string
    return string(text)


def literal(entities, entity, key, authored):
    from .rdla import number, string
    from .working_space import color as working_color
    spec = catalog()[entity['class']]['attributes'][key]
    kind = spec['type']
    owner = entity['name'] + '.' + key
    if kind == 'SceneObject*':
        return reference(entities, authored, spec.get('interface'), owner)
    if kind in ('SceneObjectVector', 'SceneObjectIndexable'):
        return '{' + ', '.join(reference(entities, name, spec.get('interface'), owner) for name in authored) + '}'
    def one(item, kind):
        if kind == 'Bool':
            return 'true' if item else 'false'
        if kind == 'String':
            if spec.get('filename') and item:
                from . import textures
                textures.register(item)
            return string(item)
        if kind in CONSTRUCTORS:
            # A light's colour is lit in the working space, like every other light's.
            if kind == 'Rgb' and key == 'color' and catalog()[entity['class']]['category'] == 'light':
                item = working_color(item)
            return CONSTRUCTORS[kind] + '(' + ', '.join(number(v) for v in item) + ')'
        return number(item)
    if kind.endswith('Vector'):
        return '{' + ', '.join(one(v, kind[:-6]) for v in authored) + '}'
    return one(authored, kind)


def block(entities, entity, extra=()):
    """The lines that define one entity: its place, then what the user set."""
    from .rdla import matrix, string
    name = '%s(%s)' % (entity['class'], string('/modo/entity/' + entity['identity']))
    lines = [name + ' {']
    if catalog()[entity['class']]['placed']:
        lines.append('  ["node_xform"] = %s,' % matrix(entity.get('matrix', IDENTITY)))
    lines += ['  [%s] = %s,' % (string(key), text) for key, text in extra]
    for key, authored in sorted(entity['parameters'].items()):
        if not key.startswith('modo_'):
            lines.append('  [%s] = %s,' % (string(key), literal(entities, entity, key, authored)))
    return name, lines + ['}']


def emit_lights(scene, lines):
    """Light filters, then the lights that may use them, into the scene's light table."""
    entities = checked(scene)
    for entity in entities:
        if catalog()[entity['class']]['category'] == 'lightfilter':
            lines += block(entities, entity)[1]
    for entity in entities:
        if catalog()[entity['class']]['category'] == 'light':
            name, body = block(entities, entity)
            lines += body + ['table.insert(lights, %s)' % name]


def emit_geometry(scene, materials, lines):
    """Volume shaders, then the shapes, each assigned its material and whatever fills it."""
    from .rdla import string
    entities = checked(scene)
    for entity in entities:
        if catalog()[entity['class']]['category'] == 'volume':
            lines += block(entities, entity)[1]
    for entity in entities:
        if catalog()[entity['class']]['category'] != 'geometry':
            continue
        held = []
        if entity.get('attributes'):
            # What the shape carries for its material to read.
            from . import primitive_attributes
            held = primitive_attributes.emit('/modo/entity/%s/attribute' % entity['identity'], [entity['attributes']], lines)
        name, body = block(entities, entity)
        tag = entity['parameters'].get('modo_material', '')
        if tag not in materials:
            tag = ''
        parts = [name, '""', 'materials[%s]' % string(tag), 'lightSet']
        if entity['parameters'].get('modo_volume') and not entity['parameters'].get('modo_material'):
            # A shape that holds a volume and was given no material is the volume alone: with the scene's
            # default surface on it, a cloud renders as the solid box it sits in.
            parts = [name, '""', 'lightSet']
        if entity['parameters'].get('modo_volume'):
            parts.append(reference(entities, entity['parameters']['modo_volume'], 'VOLUME', entity['name'] + '.volume'))
        lines += body + ['table.insert(geometries, %s)' % name, 'table.insert(assignments, {%s})' % ', '.join(parts)]
        if held:
            # MoonRay's own shapes take such values only from an instancer, so the shape is given one that puts it
            # once where it stands. A shape an instancer repeats is not in the picture a second time on its own.
            holder = 'RdlInstancerGeometry(%s)' % string('/modo/entity/%s/holder' % entity['identity'])
            lines += [holder + ' {', '  ["method"] = 2,', '  ["references"] = {%s},' % name, '  ["use_reference_xforms"] = true,',
                      '  ["use_reference_attributes"] = true,', '  ["xform_list"] = {Mat4(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)},',
                      '  ["primitive_attributes"] = {%s},' % ', '.join(held), '}',
                      'table.insert(geometries, %s)' % holder, 'table.insert(assignments, {%s, "", nil, lightSet})' % holder]


def render_camera(scene):
    """The camera entity the scene is rendered through, if one says so."""
    chosen = [e for e in checked(scene) if catalog()[e['class']]['category'] == 'camera' and e['parameters'].get('modo_render_camera')]
    if len(chosen) > 1:
        raise ValueError('More than one MoonRay camera is set to render: ' + ', '.join(e['name'] for e in chosen))
    return chosen[0] if chosen else None


def camera_lines(scene, entity):
    """The scene's camera, as this entity: the shutter comes from the scene, the rest from the item."""
    from .rdla import number, string
    entities = checked(scene)
    steps = scene.get('motion_steps', [-.25, .25])
    shutter = [(key, number(steps[i])) for key, i in (('mb_shutter_open', 0), ('mb_shutter_close', -1)) if key not in entity['parameters']]
    lines = block(entities, entity, shutter)[1]
    # The rest of the scene file knows the camera by this name.
    lines[0] = 'local camera = %s(%s) {' % (entity['class'], string('/modo/camera'))
    return lines


# ---- MoonLight ------------------------------------------------------------------------------

def camera_projection(entity):
    """How MoonLight is to look through a MoonRay camera item: a projection and its numbers, as
    MoonRay works them out, or None for a camera it has no reading of."""
    import math
    name = entity['class']
    if name == 'FisheyeCamera':
        return {'projection': 'fisheye', 'projection_values': [float(int(value(entity, 'mapping'))), float(int(value(entity, 'format'))),
                                                                float(value(entity, 'zoom')), math.radians(float(value(entity, 'fov'))) / 2]}
    if name == 'SphericalCamera':
        zoom = 30.0 / max(1e-6, float(value(entity, 'focal')))
        low, high = math.radians(float(value(entity, 'min_latitude'))), math.radians(float(value(entity, 'max_latitude')))
        middle = (low + high) / 2 + math.radians(float(value(entity, 'latitude_zoom_offset')))
        latitude = [zoom * (high - low), middle + (low - middle) * zoom]
        if bool(value(entity, 'inside_out')) or float(value(entity, 'offset_radius') or 0):
            return None
        if [float(value(entity, key)) for key in ('min_latitude', 'max_latitude', 'min_longitude', 'max_longitude')] == [-90.0, 90.0, -180.0, 180.0]:
            # MoonRay keeps its earlier convention for the whole sphere: the view axis is in the
            # middle of the picture.
            low, high = -1.5 * math.pi, .5 * math.pi
        else:
            low, high = math.radians(float(value(entity, 'min_longitude'))), math.radians(float(value(entity, 'max_longitude')))
        middle = (low + high) / 2 + math.radians(float(value(entity, 'longitude_zoom_offset')))
        return {'projection': 'spherical', 'projection_values': latitude + [zoom * (high - low), middle + (low - middle) * zoom]}
    return None


def box(size):
    x, y, z = (v / 2 for v in size)
    vertices = [[sx * x, sy * y, sz * z] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    return vertices, [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]


def sphere(radius, segments=48, rings=24):
    vertices = [[radius * math.sin(math.pi * r / rings) * math.cos(2 * math.pi * s / segments), radius * math.cos(math.pi * r / rings),
                 radius * math.sin(math.pi * r / rings) * math.sin(2 * math.pi * s / segments)] for r in range(rings + 1) for s in range(segments)]
    faces = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
             for r in range(rings) for s in range(segments)]
    return vertices, faces


def emitting_area(name, light):
    """What MoonRay divides a normalized light's brightness by: pi times its surface. None for a kind of light this is
    not worked out for."""
    import math
    if name in ('RectLight', 'PortalLight'):
        size = light['width'] * light['height']
    elif name in ('DiskLight', 'SpotLight'):
        size = math.pi * light['radius'] ** 2
    elif name == 'SphereLight':
        size = 4 * math.pi * light['radius'] ** 2
    elif name == 'CylinderLight':
        size = 2 * math.pi * light['radius'] * light['height']
    else:
        return None
    return math.pi * size if size > 1e-12 else None


def preview(scene, warnings):
    """The snapshot with its entities turned into what MoonLight draws: ordinary lights,
    environments and meshes. What has no counterpart there is named in warnings."""
    entities = scene.get('entities')
    if not entities:
        return scene
    lights, environments, meshes = list(scene.get('lights', [])), list(scene.get('environments', [])), list(scene.get('meshes', []))
    scene = mesh_lights(scene, warnings)
    skipped = {}
    camera = scene['camera']
    entities_checked = checked(scene)
    if replaces_environment(scene):
        # A MoonRay environment light set to replace Modo's leaves only itself and its kind.
        environments = []
    for entity in entities_checked:
        name, label, matrix = entity['class'], entity['name'], entity.get('matrix', IDENTITY)
        category = catalog()[name]['category']
        if category == 'light':
            if not value(entity, 'on'):
                continue
            intensity = float(value(entity, 'intensity')) * 2 ** float(value(entity, 'exposure'))
            color = value(entity, 'color')
            filters = filter_records(entities_checked, entity['parameters'].get('light_filters'), label, warnings)
            for record in [r for r in filters if r['kind'] == 'intensity']:
                # A plain scale needs nothing from the renderer.
                color = [c * s for c, s in zip(color, record['scale'])]
            filters = [r for r in filters if r['kind'] != 'intensity']
            if name == 'EnvLight':
                shown = {'camera': value(entity, 'visible_in_camera') == 1, 'indirect': True, 'reflection': True, 'refraction': True}
                texture = value(entity, 'texture')
                if texture:
                    if color != [1.0, 1.0, 1.0]:
                        warnings.append('MoonLight shows the image of %s without its colour tint.' % label)
                    environments.append(dict(shown, kind='image', name=label, identity=entity['identity'], path=texture, matrix=matrix,
                                             intensity=intensity * sum(color) / 3,
                                             srgb=Path(texture).suffix.lower() not in ('.exr', '.hdr', '.tx')))
                else:
                    environments.append(dict(shown, kind='constant', name=label, identity=entity['identity'], zenith=color, nadir=color,
                                             intensity=intensity))
                continue
            if name not in PREVIEW_LIGHTS:
                skipped.setdefault(name, []).append(label)
                continue
            if value(entity, 'texture') and name != 'RectLight':
                warnings.append('MoonLight shows %s without its texture.' % label)
            light = {'kind': name, 'identity': entity['identity'], 'name': label, 'color': color, 'intensity': intensity, 'matrix': matrix,
                     'filters': filters}
            if name == 'RectLight' and value(entity, 'texture'):
                light['texture'] = value(entity, 'texture')
            if filters and name == 'DistantLight':
                warnings.append('MoonLight applies only intensity filters to distant light %s.' % label)
            light.update({target: float(value(entity, key)) for key, target in PREVIEW_LIGHTS[name].items()})
            # MoonLight draws each kind of light the usual way for its kind: its brightness spread over its size, except
            # for a portal. A light set the other way is given the brightness that comes to the same thing.
            usual = name != 'PortalLight'
            if bool(value(entity, 'normalized')) != usual:
                size = emitting_area(name, light)
                if size is None:
                    warnings.append('MoonLight shows %s with the usual normalization for its kind.' % label)
                else:
                    light['intensity'] = intensity * size if usual else intensity / size
            if name == 'SpotLight':
                light['soft_edge'] = max(0.0, light['cone'] - float(value(entity, 'inner_cone_angle'))) / 2
            lights.append(light)
        elif name in ('BoxGeometry', 'SphereGeometry'):
            if entity['parameters'].get('modo_volume'):
                skipped.setdefault('volumes', []).append(label)
                continue
            vertices, faces = box(value(entity, 'size')) if name == 'BoxGeometry' else sphere(float(value(entity, 'radius')))
            mesh = {'name': label, 'identity': entity['identity'], 'vertices': vertices, 'faces': faces, 'matrix': matrix,
                    'material': entity['parameters'].get('modo_material', ''), 'smooth': name == 'SphereGeometry'}
            meshes.append(mesh)
        elif category == 'lightfilter':
            # A filter shows through the lights that name it; what cannot be applied is said there.
            continue
        elif category == 'camera':
            if entity['parameters'].get('modo_render_camera'):
                lens = camera_projection(entity)
                if lens is None:
                    warnings.append('MoonLight looks through the Modo camera, not %s.' % label)
                else:
                    # The view is from the item, through its own kind of lens.
                    camera = dict(scene['camera'], matrix=matrix, dof=False, **lens)
                    camera.pop('matrix_close', None)
        else:
            skipped.setdefault(name, []).append(label)
    for name, labels in sorted(skipped.items()):
        warnings.append('MoonLight does not show %s (%s).' % (name, ', '.join(labels[:6]) + (' ...' if len(labels) > 6 else '')))
    return dict(scene, camera=camera, lights=lights, environments=environments, meshes=meshes, entities=[])
