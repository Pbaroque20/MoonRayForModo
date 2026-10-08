"""MoonRay's own scene objects as Modo items: lights, light filters, cameras, shapes and volumes.

An entity is a locator that carries a MoonRay class name and the attributes the user has set,
in the item's MoonRay tag. Unset attributes keep MoonRay's defaults. This module holds the
schema, reads the items, writes them into the RDLA scene, and says which of them MoonLightIPR
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
# The lights MoonLightIPR shows, with the snapshot keys their sizes go under.
PREVIEW_LIGHTS = {'DistantLight': {'angular_extent': 'angle'}, 'SphereLight': {'radius': 'radius'},
                  'RectLight': {'width': 'width', 'height': 'height'}, 'DiskLight': {'radius': 'radius'},
                  'SpotLight': {'lens_radius': 'radius', 'outer_cone_angle': 'cone'},
                  'CylinderLight': {'radius': 'radius', 'height': 'height'}, 'PortalLight': {'width': 'width', 'height': 'height'}}


# What a newly added item starts with where MoonRay's own defaults show nothing. MoonRay divides a
# light's intensity by its area, so its default of 1 is close to black, and its default sphere
# of radius 1 swallows whatever stands near it.
STARTING = {'SphereLight': {'intensity': 50.0, 'radius': .1}, 'RectLight': {'intensity': 50.0},
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
                    result.append({'identity': item.id, 'name': item.name, 'class': name, 'matrix': world_matrix(item),
                                   'parameters': from_channels(name, lambda channel: item.channel(channel).get())})
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
        wide = lens + reach * math.tan(math.radians(min(max(number('outer_cone_angle'), 0.0), 170.0)) / 2)
        return [('circles', [((0, 0, 0), (0, 0, lens)), ((0, 0, -reach), (0, 0, wide))]),
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
              'SpotLight': ['lens_radius', 'outer_cone_angle'], 'CylinderLight': ['radius', 'height'], 'SphereGeometry': ['radius'],
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
        name, body = block(entities, entity)
        tag = entity['parameters'].get('modo_material', '')
        if tag not in materials:
            tag = ''
        parts = [name, '""', 'materials[%s]' % string(tag), 'lightSet']
        if entity['parameters'].get('modo_volume'):
            parts.append(reference(entities, entity['parameters']['modo_volume'], 'VOLUME', entity['name'] + '.volume'))
        lines += body + ['table.insert(geometries, %s)' % name, 'table.insert(assignments, {%s})' % ', '.join(parts)]


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


# ---- MoonLightIPR ------------------------------------------------------------------------------

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


def preview(scene, warnings):
    """The snapshot with its entities turned into what MoonLightIPR draws: ordinary lights,
    environments and meshes. What has no counterpart there is named in warnings."""
    entities = scene.get('entities')
    if not entities:
        return scene
    lights, environments, meshes = list(scene.get('lights', [])), list(scene.get('environments', [])), list(scene.get('meshes', []))
    skipped = {}
    for entity in checked(scene):
        name, label, matrix = entity['class'], entity['name'], entity.get('matrix', IDENTITY)
        category = catalog()[name]['category']
        if category == 'light':
            if not value(entity, 'on'):
                continue
            intensity = float(value(entity, 'intensity')) * 2 ** float(value(entity, 'exposure'))
            color = value(entity, 'color')
            if entity['parameters'].get('light_filters'):
                warnings.append('MoonLightIPR ignores light filters on %s.' % label)
            if name == 'EnvLight':
                shown = {'camera': value(entity, 'visible_in_camera') == 1, 'indirect': True, 'reflection': True, 'refraction': True}
                texture = value(entity, 'texture')
                if texture:
                    if color != [1.0, 1.0, 1.0]:
                        warnings.append('MoonLightIPR shows the image of %s without its colour tint.' % label)
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
            if value(entity, 'texture'):
                warnings.append('MoonLightIPR shows %s without its texture.' % label)
            if value(entity, 'normalized') != (name != 'PortalLight'):
                warnings.append('MoonLightIPR shows %s with the usual normalization for its kind.' % label)
            light = {'kind': name, 'identity': entity['identity'], 'name': label, 'color': color, 'intensity': intensity, 'matrix': matrix}
            light.update({target: float(value(entity, key)) for key, target in PREVIEW_LIGHTS[name].items()})
            if name == 'SpotLight':
                light['soft_edge'] = max(0.0, light['cone'] - float(value(entity, 'inner_cone_angle'))) / 2
            lights.append(light)
        elif name in ('BoxGeometry', 'SphereGeometry'):
            if entity['parameters'].get('modo_volume'):
                skipped.setdefault('volumes', []).append(label)
                continue
            vertices, faces = box(value(entity, 'size')) if name == 'BoxGeometry' else sphere(float(value(entity, 'radius')))
            meshes.append({'name': label, 'identity': entity['identity'], 'vertices': vertices, 'faces': faces, 'matrix': matrix,
                           'material': entity['parameters'].get('modo_material', ''), 'smooth': name == 'SphereGeometry'})
        elif category == 'camera':
            if entity['parameters'].get('modo_render_camera'):
                warnings.append('MoonLightIPR looks through the Modo camera, not %s.' % label)
        else:
            skipped.setdefault(name, []).append(label)
    for name, labels in sorted(skipped.items()):
        warnings.append('MoonLightIPR does not show %s (%s).' % (name, ', '.join(labels[:6]) + (' ...' if len(labels) > 6 else '')))
    return dict(scene, lights=lights, environments=environments, meshes=meshes)
