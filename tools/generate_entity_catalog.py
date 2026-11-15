"""Generate the schema of MoonRay's own scene objects from the vendored upstream declarations.

Lights, light filters, cameras, procedural geometry and volume shaders declare their
attributes in C++ rather than JSON, so this reads the declareAttribute calls. Display filters
declare theirs in JSON, which is read as it is. Writes
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
# Display filters: image operations MoonRay does over its render outputs as it renders. Their declarations are JSON.
DISPLAY_FILTERS = sorted(list((base / 'moonshine/dso/displayfilter').glob('*/*DisplayFilter.json'))
                         + list((dso / 'displayfilter').glob('*/*DisplayFilter.json')))
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


def json_declarations(path):
    """Attributes declared in a JSON schema, its included files first, as declarations() gives them."""
    schema = json.loads(path.read_text(encoding='utf-8'))
    found = []
    for included in (schema.get('directives') or {}).get('include', []):
        # Includes are named from the library they belong to: lib/displayfilter/json/common.json is moonshine's.
        found += json_declarations(base / 'moonshine' / included)
    for entry in schema.get('attributes', {}).values():
        kind = entry['type'].replace(' ', '')
        if kind not in TYPES:
            continue
        spec = {'name': entry['name'], 'type': kind}
        if 'default' in entry and not kind.startswith('SceneObject'):
            value = default(kind, str(entry['default']))
            if value is not None:
                spec['default'] = value
        interface = re.search(r'INTERFACE_(\w+)', entry.get('interface', ''))
        if interface and kind.startswith('SceneObject'):
            spec['interface'] = interface.group(1)
        for key in ('group', 'comment', 'label'):
            if key in entry:
                spec[key] = ' '.join(str(entry[key]).split()) if key == 'comment' else entry[key]
        for key in ('min', 'max'):
            limit = number(str(entry[key])) if key in entry else None
            if limit is not None:
                spec[key] = limit
        if 'enum' in entry:
            spec['enum'] = {label: int(value) for label, value in entry['enum'].items()}
        if entry.get('flags') and 'FLAGS_FILENAME' in entry['flags']:
            spec['filename'] = True
        found.append(spec)
    return found


catalog = {}
for path in DISPLAY_FILTERS:
    name = path.stem
    attributes = {spec['name']: spec for spec in json_declarations(path)}
    catalog[name] = {'category': 'displayfilter', 'category_label': 'Display Filters', 'attributes': attributes, 'placed': False,
                     'source': path.relative_to(root).as_posix()}
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
        if name == 'VdbGeometry':
            # A VDB file of a sequence (a run of # in its name for the frame) and fire coloured by its temperature: the
            # kit resolves both as it writes the scene (entities.resolve_vdb). MoonRay's own static says which: a shape
            # whose geometry changes between frames is not static, so unticked it reads the numbered files, one a frame
            # (native.vdb_sequences); it sits with the file, in the VDB section.
            if 'static' in attributes:
                attributes['static'] = dict(attributes['static'], group='VDB', comment=(
                    'Ticked: the one VDB file, at every frame. Unticked: the numbered files beside it (fire_1.vdb, fire_2.vdb...), '
                    'the one for each frame, as the geometry changes between frames. (MoonRay: disable if the geometry will '
                    'be updated between frames.)'))
            attributes['modo_blackbody'] = {
                'name': 'modo_blackbody', 'type': 'Bool', 'default': False, 'group': 'VDB', 'label': 'blackbody colour',
                'comment': 'Colour the emission grid by temperature, as a hot body glows: deep red where it is cool, orange, then '
                           'yellow-white where it is hottest. Choose the temperature grid as the emission grid. Off, it glows grey, '
                           "coloured by the volume's incandescence gain mult."}
            attributes['modo_blackbody_kelvin'] = {
                'name': 'modo_blackbody_kelvin', 'type': 'Float', 'default': 3000.0, 'group': 'VDB', 'label': 'kelvin at 1',
                'comment': 'The temperature, in kelvin, a value of 1 in the temperature grid stands for. Higher is whiter and hotter; '
                           'lower is redder.'}
            attributes['modo_frame_offset'] = {
                'name': 'modo_frame_offset', 'type': 'Int', 'default': 0, 'group': 'VDB', 'label': 'frame offset',
                'comment': "For a sequence of VDB files (static unticked): added to the scene's frame to "
                           'choose the file.'}
            attributes['modo_sequence_hold'] = {
                'name': 'modo_sequence_hold', 'type': 'Bool', 'default': False, 'group': 'VDB', 'label': 'hold first and last frames',
                'comment': 'Before a sequence of VDB files begins, show its first file, and after it ends, its last. Off, the volume '
                           'is not there outside its frames.'}
        if name == 'EnvLight':
            attributes['modo_replace_environment'] = {
                'name': 'modo_replace_environment', 'type': 'Bool', 'default': False, 'group': 'Assignment', 'label': 'replace Modo environment',
                'comment': 'Light the scene with this instead of the Modo environments and the preview environment light.'}
        if category == 'camera':
            attributes['modo_render_camera'] = {'name': 'modo_render_camera', 'type': 'Bool', 'default': False, 'group': 'Assignment',
                                                'label': 'render through this camera',
                                                'comment': 'Render through this camera, from where this item stands, instead of the Modo camera.'}
        if name in ('PerspectiveCamera', 'OrthographicCamera'):
            attributes['modo_lens'] = {'name': 'modo_lens', 'type': 'Bool', 'default': False, 'group': 'Lens', 'label': "use the Modo camera's lens",
                                       'comment': "Take the lens from this camera's own Modo properties (focal length, film, offsets, depth of field, "
                                                  'F-stop, focus distance and iris) instead of the MoonRay values below.'}
        catalog[name] = {'category': category, 'category_label': label, 'attributes': attributes, 'placed': placed,
                         'source': path.relative_to(root).as_posix()}
# The kit's own: an ocean plane, a surface MoonRay has no class for. The kit makes it a mesh at each reading (ocean_plane):
# rings around the camera out to the horizon, its UVs fixed to the world, worn by a sea made from the Ocean node's
# settings here (the graph editor's own, nodes.specs), or by the material its tag names. Part of the Ocean nodes override.
import sys  # noqa: E402
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes as _nodes  # noqa: E402
_shared = {}
for _spec in declarations(rdl2 / 'Geometry.cc'):
    _shared[_spec['name']] = _spec
_shared.pop('node_xform', None)
_plane = dict(_shared)
_plane['modo_material'] = {'name': 'modo_material', 'type': 'String', 'default': '', 'group': 'Assignment', 'label': 'material tag',
                           'comment': "The material tag of a Modo material to render the sea with, its Ocean node's settings its own; "
                                      'empty for the sea made from the settings here.'}
_plane['horizon'] = {'name': 'horizon', 'type': 'Float', 'default': 20000.0, 'min': 100.0, 'group': 'Ocean Plane', 'label': 'horizon',
                     'comment': 'How far the sea reaches from the camera, in metres. It follows the camera, so it never ends in view.'}
_plane['detail'] = {'name': 'detail', 'type': 'Float', 'default': 1.0, 'min': 0.05, 'group': 'Ocean Plane', 'label': 'detail near the camera',
                    'comment': "How far apart the plane's points are next to the camera, in metres; farther out they spread with "
                               'the distance. The renderers cut it finer still for the waves.'}
_plane['tile_size'] = {'name': 'tile_size', 'type': 'Float', 'default': 80.0, 'min': 1.0, 'group': 'Ocean Plane', 'label': 'tile size',
                       'comment': 'How wide one tile of the sea is, in metres: the sea is made at 80 m and scaled whole to this, its '
                                  'waves and their heights with it.'}
_plane['water_color'] = {'name': 'water_color', 'type': 'Rgb', 'default': [0.004, 0.018, 0.026], 'group': 'Ocean Plane',
                         'label': 'water colour', 'comment': "The water's colour, under its foam."}
_plane['foam_color'] = {'name': 'foam_color', 'type': 'Rgb', 'default': [0.85, 0.88, 0.9], 'group': 'Ocean Plane',
                        'label': 'foam colour', 'comment': "The foam's colour, where the surface folds over (Foam Threshold)."}
for _key, _spec in _nodes.specs('ocean').items():
    if _key in ('repeat', 'fit_to_mesh', 'tiles_across'):
        continue    # the plane lays the tiles itself, Tile Size wide
    _entry = {'name': _key, 'type': _spec['type'], 'group': 'Ocean', 'comment': ' '.join(str(_spec.get('comment', '')).split())}
    if 'default_value' in _spec:
        _entry['default'] = _spec['default_value']
    if _spec.get('enum'):
        _entry['enum'] = {str(k): int(v) for k, v in _spec['enum'].items()}
    _plane[_key] = _entry
catalog['OceanPlaneGeometry'] = {'category': 'geometry', 'category_label': 'Geometry', 'attributes': _plane, 'placed': True,
                                 'source': 'kit', 'override': 'ocean'}
target = root / 'kit/MoonRayForModo/python/moonray_modo/entity_catalog.json'
target.write_text(json.dumps(catalog, sort_keys=True, indent=2) + '\n', encoding='utf-8')
print('Generated', len(catalog), 'entity schemas,', sum(len(v['attributes']) for v in catalog.values()), 'attributes')
