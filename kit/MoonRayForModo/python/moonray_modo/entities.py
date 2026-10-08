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

ITEM_TYPE = 'moonray.entity'
CLASS_KEY, PARAMETERS_KEY = 'entity_class', 'entity_parameters'
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
SIZES = {'Rgb': 3, 'Rgba': 4, 'Vec2f': 2, 'Vec3f': 3, 'Vec4f': 4}
CONSTRUCTORS = {'Rgb': 'Rgb', 'Rgba': 'Rgba', 'Vec2f': 'Vec2', 'Vec3f': 'Vec3', 'Vec4f': 'Vec4'}
# The lights MoonLightIPR shows, with the snapshot keys their sizes go under.
PREVIEW_LIGHTS = {'DistantLight': {'angular_extent': 'angle'}, 'SphereLight': {'radius': 'radius'},
                  'RectLight': {'width': 'width', 'height': 'height'}, 'DiskLight': {'radius': 'radius'},
                  'SpotLight': {'lens_radius': 'radius', 'outer_cone_angle': 'cone'},
                  'CylinderLight': {'radius': 'radius', 'height': 'height'}, 'PortalLight': {'width': 'width', 'height': 'height'}}


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
    for bound, wrong in (('min', lambda a, b: a < b), ('max', lambda a, b: a > b)):
        if bound in spec and wrong(value, spec[bound]):
            raise ValueError('Value is beyond the %s of %s' % (bound, spec[bound]))
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


def is_entity(item):
    from . import properties
    return bool(properties.read(item).get(CLASS_KEY))


def collect(scene, warnings):
    """Read every MoonRay item in the Modo scene that is set to render."""
    from . import properties
    from .host import render_visible, world_matrix
    result = []
    # The item type made for them, and plain locators in case that type is unavailable.
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
