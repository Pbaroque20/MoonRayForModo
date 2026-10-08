"""Generate the schema of MoonRay's own scene objects from the vendored upstream declarations.

Lights, light filters, cameras, procedural geometry and volume shaders declare their
attributes in C++ rather than JSON, so this reads the declareAttribute calls. Writes
kit/MoonRayForModo/python/moonray_modo/entity_catalog.json.
"""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
base = root / 'upstream/openmoonray/moonray'
rdl2 = base / 'scene_rdl2/lib/scene/rdl2'
dso = base / 'moonray/dso'
# category -> (label, shared declarations, {class: its declarations})
CATEGORIES = {
    'light': ('Lights', [rdl2 / 'Light.cc'], {name: dso / 'light' / name / 'attributes.cc' for name in (
        'EnvLight', 'DistantLight', 'SphereLight', 'RectLight', 'DiskLight', 'SpotLight', 'CylinderLight', 'PortalLight', 'MeshLight')}),
    'lightfilter': ('Light Filters', [rdl2 / 'LightFilter.cc'], {name: dso / 'lightfilter' / name / 'attributes.cc' for name in (
        'IntensityLightFilter', 'DecayLightFilter', 'RodLightFilter', 'BarnDoorLightFilter', 'CookieLightFilter', 'CookieLightFilter_v2',
        'ColorRampLightFilter', 'VdbLightFilter', 'CombineLightFilter')}),
    'camera': ('Cameras', [rdl2 / 'Camera.cc'], {name: dso / 'camera' / name / 'attributes.cc' for name in (
        'PerspectiveCamera', 'OrthographicCamera', 'FisheyeCamera', 'SphericalCamera', 'DomeMaster3DCamera', 'BakeCamera')}),
    'geometry': ('Geometry', [rdl2 / 'Geometry.cc'], {
        'BoxGeometry': base / 'moonshine/dso/geometry/Box/attributes.cc',
        'SphereGeometry': base / 'moonshine/dso/geometry/Sphere/attributes.cc',
        'VdbGeometry': dso / 'geometry/Vdb/attributes.cc'}),
    'volume': ('Volumes', [rdl2 / 'VolumeShader.cc'], {
        'BaseVolume': dso / 'volume/Base/attributes.cc', 'VdbVolume': dso / 'volume/Vdb/attributes.cc',
        'CutoutVolume': dso / 'volume/Cutout/attributes.cc'}),
}
TYPES = {'Bool', 'Int', 'Long', 'Float', 'Double', 'String', 'Rgb', 'Rgba', 'Vec2f', 'Vec3f', 'Vec4f', 'Mat4f', 'Mat4d',
         'SceneObject*', 'SceneObjectVector', 'BoolVector', 'IntVector', 'FloatVector', 'RgbVector', 'Vec2fVector', 'Vec3fVector',
         'StringVector', 'SceneObjectIndexable'}


def uncommented(text):
    # String literals may hold what looks like a comment, so they are matched first and kept.
    return re.sub(r'("(?:[^"\\\n]|\\.)*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or ' ', text, flags=re.S)


def call(text, start):
    """The arguments of the call whose opening parenthesis is at start, split at top level."""
    depth, args, current, quoted, i = 0, [], '', False, start
    while i < len(text):
        c = text[i]
        if quoted:
            current += c
            if c == '\\':
                current += text[i + 1]
                i += 1
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
            current += c
        elif c in '({':
            depth += 1
            if depth > 1:
                current += c
        elif c in ')}':
            depth -= 1
            if depth == 0:
                args.append(current.strip())
                return args, i
            current += c
        elif c == ',' and depth == 1:
            args.append(current.strip())
            current = ''
        else:
            current += c
        i += 1
    raise ValueError('Unbalanced call')


def text_of(expression):
    """Adjacent string literals, as C++ joins them; None if the expression is anything else."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', expression)
    if not parts or re.sub(r'"(?:[^"\\]|\\.)*"', '', expression).strip():
        return None
    return ''.join(parts).replace('\\"', '"').replace('\\n', ' ').replace('\\\\', '\\')


def number(token):
    token = token.strip()
    token = re.sub(r'^(?:rdl2::|math::|scene_rdl2::)*(?:Float|Int|float|int)\((.*)\)$', r'\1', token)
    if re.fullmatch(r'[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?[fF]?', token):
        value = float(token.rstrip('fF'))
        return int(value) if re.fullmatch(r'[-+]?\d+', token) else value
    return None


def default(kind, expression):
    expression = expression.strip()
    if kind == 'Bool':
        return {'true': True, 'false': False}.get(expression)
    if kind == 'String':
        return text_of(expression)
    if kind in ('Int', 'Long', 'Float', 'Double'):
        return number(expression)
    size = {'Rgb': 3, 'Rgba': 4, 'Vec2f': 2, 'Vec3f': 3, 'Vec4f': 4}.get(kind)
    found = re.fullmatch(r'(?:\w+::)*\w+\((.*)\)', expression, flags=re.S)
    if size and found:
        values = [number(v) for v in found.group(1).split(',')]
        if len(values) == 1 and values[0] is not None:
            return [values[0]] * size
        if len(values) == size and None not in values:
            return values
    return None


def declarations(path):
    """Attributes declared in one source file, in order, keyed by the variable that holds each."""
    text = uncommented(path.read_text(encoding='utf-8'))
    found = {}
    for match in re.finditer(r'(\w+)\s*=\s*(?:\w+\.)?\s*declareAttribute\s*<\s*(?:\w+::)*([\w*\s]+?)\s*>\s*\(', text):
        variable, kind = match.group(1), match.group(2).replace(' ', '')
        args, _ = call(text, match.end() - 1)
        name = text_of(args[0])
        if kind not in TYPES or name is None:
            continue
        spec = {'name': name, 'type': kind}
        rest = args[1:]
        if rest and kind not in ('SceneObject*', 'SceneObjectVector', 'SceneObjectIndexable') and 'FLAGS_' not in rest[0]:
            value = default(kind, rest[0])
            if value is not None:
                spec['default'] = value
            rest = rest[1:]
        joined = ' '.join(rest)
        if 'FLAGS_FILENAME' in joined:
            spec['filename'] = True
        interface = re.search(r'INTERFACE_(\w+)', joined)
        if interface and kind.startswith('SceneObject'):
            spec['interface'] = interface.group(1)
        found[variable] = spec
    counters = {}
    for match in re.finditer(r'\b(setMetadata|setEnumValue|setGroup)\s*\(', text):
        args, _ = call(text, match.end() - 1)
        kind = match.group(1)
        if kind == 'setGroup' and len(args) == 2 and args[1] in found:
            found[args[1]]['group'] = text_of(args[0]) or 'Parameters'
        elif kind == 'setMetadata' and len(args) == 3 and args[0] in found:
            value = text_of(args[2])
            if value is None:
                continue
            if 'sComment' in args[1] or text_of(args[1]) == 'comment':
                found[args[0]]['comment'] = ' '.join(value.split())
            elif text_of(args[1]) == 'label':
                found[args[0]]['label'] = value
            elif text_of(args[1]) in ('min', 'max'):
                limit = number(value)
                if limit is not None:
                    found[args[0]][text_of(args[1])] = limit
        elif kind == 'setEnumValue' and len(args) == 3 and args[0] in found:
            index = number(args[1])
            if index is None:
                # A named constant; these are declared in order from zero.
                index = counters.get(args[0], 0)
            counters[args[0]] = int(index) + 1
            found[args[0]].setdefault('enum', {})[text_of(args[2]) or str(index)] = int(index)
    return list(found.values())


catalog = {}
for category, (label, shared, classes) in CATEGORIES.items():
    for name, path in classes.items():
        attributes = {}
        for source in shared + [path]:
            for spec in declarations(source):
                attributes[spec['name']] = spec
        # The item's own transform places the object, where the class has a place at all.
        placed = attributes.pop('node_xform', None) is not None or category in ('light', 'camera', 'geometry')
        # What only the plugin needs to know, alongside MoonRay's own attributes.
        if category == 'geometry':
            attributes['modo_material'] = {'name': 'modo_material', 'type': 'String', 'default': '', 'group': 'Assignment', 'label': 'material tag',
                                           'comment': 'The material tag of the Modo material this is rendered with; empty for the base material.'}
            attributes['modo_volume'] = {'name': 'modo_volume', 'type': 'SceneObject*', 'interface': 'VOLUME', 'group': 'Assignment', 'label': 'volume',
                                         'comment': 'The name of a MoonRay volume item that fills this shape.'}
        if category == 'camera':
            attributes['modo_render_camera'] = {'name': 'modo_render_camera', 'type': 'Bool', 'default': False, 'group': 'Assignment',
                                                'label': 'render through this camera',
                                                'comment': 'Render through this camera, from where this item stands, instead of the Modo camera.'}
        catalog[name] = {'category': category, 'category_label': label, 'attributes': attributes, 'placed': placed,
                         'source': path.relative_to(root).as_posix()}
target = root / 'kit/MoonRayForModo/python/moonray_modo/entity_catalog.json'
target.write_text(json.dumps(catalog, sort_keys=True, indent=2) + '\n', encoding='utf-8')
print('Generated', len(catalog), 'entity schemas,', sum(len(v['attributes']) for v in catalog.values()), 'attributes')
