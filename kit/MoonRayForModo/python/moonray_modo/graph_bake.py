"""Bake what is wired to a material's input into an image, with MoonRay itself.

MoonLightIPR has one fixed material model and reads only images, so a ramp, a noise, a colour
correction or a chain of math nodes in a material graph means nothing to it. MoonRay knows
them all: it renders the node's output on a flat square that fills the picture, one unit of
UV across, and the picture is the node as a texture. The bake is kept, keyed by the nodes
that feed it, so it is made once per change.

What depends on the surface's UVs alone is baked over one unit of UV. A RampMap or GradientMap
laid out in the world or in the object's space is baked over one unit of that space instead,
and the plugin projects it back onto the surface. Any other map laid out in the object's space (a
noise, mostly) is baked over the box its meshes fill, flat across the box's thinnest side, and
MoonLightIPR reads it by where each point is in its object (solid, solid_frame). MoonRay's default for those two, render
space, is the camera's own space and is not followed. A node that looks at the normal, the camera
or anything else (a projection, a curvature map) has no single picture, and is named instead.
"""
from .cache_folder import root as cache_root
import copy
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import nodes

RESOLUTION = 512
# Nodes whose value comes from somewhere other than the UVs.
ELSEWHERE = ('Project', 'TransformSpace', 'TransformNormal', 'Curvature', 'Wireframe', 'Directional', 'Toon', 'Hair', 'Deformation',
             'LODMap', 'DebugMap', 'Random', 'OpenVdb', 'TwoSided', 'UsdPrimvarReader', 'ExtraAov', 'AttributeMap', 'AxisAngle',
             'NormalToRgb', 'RgbToNormal', 'DistortNormal', 'CombineNormal', 'ImageNormal', 'SwitchNormal', 'NormalDisplacement',
             'VectorDisplacement', 'CombineDisplacement', 'SwitchDisplacement')
SPACES = (nodes.SPACE_WORLD, nodes.SPACE_OBJECT, nodes.SPACE_TEXTURE)
RAMP_BY_INPUT = 8
# Nodes that read the surface's UVs, which cannot share a picture with one laid out in space.
READ_UVS = ('image', 'texcoord', 'checker', 'ImageMap', 'CheckerboardMap', 'UVTransformMap', 'UsdUVTexture', 'UsdTransform2d')
# Nodes that work on each value alone, wherever it is: a colour correction or arithmetic. Over one image and these, a
# bake need cover only one repeat of the image, laid on as the image is (single_image).
POINTWISE = ('multiply', 'add', 'subtract', 'divide', 'clamp', 'convert', 'swizzle', 'lerp', 'constant', 'invert', 'power',
             'RemapMap', 'ClampMap', 'InvertMap', 'RgbToFloatMap', 'FloatToRgbMap', 'RgbToLabMap', 'LabToRgbMap', 'MultiChannelToFloatMap')
TILE_RESOLUTION = 2048
# A map laid out in the object's space, baked over the box its meshes fill: as many pixels across it.
SOLID_RESOLUTION = 2048


def space_of(node):
    """The space a map is laid out in (nodes.SPACE_*), MoonRay's own default where it is not set; None for a node with
    no space to choose."""
    try:
        spec = nodes.specs(node['type'])
    except ValueError:
        return None
    if 'space' not in spec or not spec['space'].get('enum'):
        return None
    value = (node.get('parameters') or {}).get('space')
    if value is None:
        from . import node_defaults
        try:
            value = node_defaults.parameters(node['type']).get('space', 0)
        except ValueError:
            value = 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def solid(graph, identity):
    """The maps feeding a node that are laid out in the object's or the world's space (a noise, mostly; RampMap and
    GradientMap have projections of their own): what MoonLightIPR bakes over the box the material's meshes fill."""
    return [key for key, node in feeding(graph, identity).items() if node['type'] not in ('RampMap', 'GradientMap')
            and not any(node['type'].startswith(prefix) for prefix in ELSEWHERE)
            and space_of(node) in (nodes.SPACE_OBJECT, nodes.SPACE_WORLD)]


def solid_frame(region):
    """How a box of an object's space, {'low': [x, y, z], 'high': [x, y, z]}, is baked: flat across its thinnest side,
    as a square covering the other two. Returns (the bake square's matrix, the camera's matrix, the square's side, the
    rows that take a point of the object to the bake's u and v); matrices with their axes in rows, as Modo's."""
    low, high = [float(v) for v in region['low']], [float(v) for v in region['high']]
    extent = [max(h - l, 0.0) for l, h in zip(low, high)]
    across = min(range(3), key=lambda axis: extent[axis])
    a, b = [axis for axis in range(3) if axis != across]
    side = max(extent[a], extent[b], 1e-6) * 1.02
    centre = [(l + h) / 2 for l, h in zip(low, high)]

    def unit(axis):
        return [1.0 if k == axis else 0.0 for k in range(3)]
    ea, eb = unit(a), unit(b)
    ez = [ea[1] * eb[2] - ea[2] * eb[1], ea[2] * eb[0] - ea[0] * eb[2], ea[0] * eb[1] - ea[1] * eb[0]]
    corner = list(centre)
    corner[a] -= side / 2
    corner[b] -= side / 2
    square = [v * side for v in ea] + [0.0] + [v * side for v in eb] + [0.0] + ez + [0.0] + corner + [1.0]
    distance = 4 * side + extent[across]
    camera = ea + [0.0] + eb + [0.0] + ez + [0.0] + [c + z * distance for c, z in zip(centre, ez)] + [1.0]
    rows = [v / side for v in ea] + [-corner[a] / side] + [v / side for v in eb] + [-corner[b] / side] + [0.0, 0.0, 0.0, 0.0]
    return square, camera, side, rows


def single_image(graph, identity):
    """The one image a node is a colour correction or arithmetic of, or None. Baked, such a node is the image with
    those done to it: one repeat of it, at more than the bake's usual size, laid on through the image's own UV map
    and repeats, as sharp as the image."""
    found = None
    for key, node in feeding(graph, identity).items():
        kind = node['type']
        if kind == 'image' and 'texcoord' not in node.get('inputs', {}) and node.get('parameters', {}).get('file'):
            if found is not None:
                return None
            found = key
        elif not (kind.startswith('ColorCorrect') or kind in POINTWISE):
            return None
    return found


def feeding(graph, identity, seen=None):
    """The node and everything wired into it."""
    seen = seen if seen is not None else {}
    node = graph['nodes'].get(identity)
    if node is None or identity in seen:
        return seen
    seen[identity] = node
    for source in node.get('inputs', {}).values():
        feeding(graph, source, seen)
    return seen


def plan(graph, identity):
    """How a node is to be baked: (why not, the node laid out in space or None). With no reason
    and no such node, it is baked over the UVs."""
    spatial, over_uvs, laid_in_space = [], False, False
    for key, node in feeding(graph, identity).items():
        kind, values = node['type'], node.get('parameters', {})
        if kind in ('RampMap', 'GradientMap'):
            space = int(values.get('space', 0))
            if space == nodes.SPACE_RENDER:
                return 'a %s in render space, which follows the camera (set its space to object, world or texture)' % kind, None
            if space not in SPACES:
                return 'a %s laid out in camera, screen or reference space' % kind, None
            if kind == 'RampMap' and int(values.get('ramp_type', 0)) == RAMP_BY_INPUT:
                return 'a RampMap driven by an input', None
            if space == nodes.SPACE_TEXTURE:
                over_uvs = True
            elif nodes.space_descriptor(node) is None:
                return 'a %s with no length' % kind, None
            else:
                spatial.append(key)
            continue
        if any(kind.startswith(prefix) for prefix in ELSEWHERE):
            return '%s, which does not depend on the UVs alone' % kind, None
        if space_of(node) in (nodes.SPACE_OBJECT, nodes.SPACE_WORLD) and nodes.category(kind) == 'map':
            # Baked over the box its meshes fill (solid), where that is given.
            laid_in_space = True
            continue
        if kind == 'normalmap' or nodes.category(kind) != 'map':
            return kind, None
        over_uvs = over_uvs or kind in READ_UVS
    if len(spatial) > 1 or (spatial and over_uvs) or (laid_in_space and (spatial or over_uvs)):
        return 'nodes laid out in space mixed with others that read the UVs or another space', None
    return None, (spatial[0] if spatial else None)


def reason(graph, identity):
    """Why a node cannot be baked, in a few words, or None if it can."""
    return plan(graph, identity)[0]


def files(graph, identity):
    """The image files the node reads, with their sizes and times, so that a changed file is baked again."""
    found = []
    for node in feeding(graph, identity).values():
        for key, value in sorted(node.get('parameters', {}).items()):
            for path in value if isinstance(value, list) else [value]:
                if isinstance(path, str) and key in ('file', 'texture') and path:
                    try:
                        stat = os.stat(path)
                        found.append((path, stat.st_size, stat.st_mtime_ns))
                    except OSError:
                        found.append((path, 0, 0))
    return found


def folder():
    root = cache_root() / 'GraphBakes'
    root.mkdir(parents=True, exist_ok=True)
    return root


def scene(graph, identity, tile=None, region=None):
    """A scene that is nothing but the node, shown on a square that fills an orthographic view.

    The square is one unit across with a corner at the origin, so a point's position is also
    its UV: a node laid out in space is baked over one unit of that space. A GradientMap is
    turned to run along the square's first axis, which is where its projection puts it. With region, the box the
    material's meshes fill in their own space, maps laid out in the object's space (solid) are baked over it instead:
    the square laid across it (solid_frame), and those maps read in the world, which is the square's object space there.
    """
    baked = {'version': 1, 'root': 'bake', 'overrides': [],
             'nodes': {key: {k: copy.deepcopy(v) for k, v in node.items() if k != 'position'} for key, node in feeding(graph, identity).items()}}
    spatial = plan(graph, identity)[1]
    if spatial is not None:
        values = baked['nodes'][spatial].setdefault('parameters', {})
        # The bake's mesh stands at the origin unturned, so every one of these spaces is the same there.
        values['space'] = nodes.SPACE_WORLD
        if baked['nodes'][spatial]['type'] == 'GradientMap':
            values['start'], values['end'] = [0.0, 0.0, 0.0], [1.0, 0.0, 0.0]
    if tile is not None:
        # One repeat of the image: what the image's scale makes several of is laid on again by the image's own UVs.
        baked['nodes'][tile].setdefault('parameters', {})['scale'] = [1.0, 1.0]
    size = TILE_RESOLUTION if tile is not None else RESOLUTION
    laid = solid(graph, identity) if region is not None else []
    for key in laid:
        baked['nodes'][key].setdefault('parameters', {})['space'] = nodes.SPACE_WORLD
    baked['nodes']['bake'] = {'type': 'DwaEmissiveMaterial', 'parameters': {'show_emission': True}, 'inputs': {'emission': identity}}
    material = {'name': 'bake', 'color': [0, 0, 0], 'roughness': 1.0, 'shader': 'DwaBaseMaterial', 'native_shader': 'DwaEmissiveMaterial',
                'native_parameters': {'show_emission': True}, 'node_graph': baked, 'node_override': True}
    square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    mesh = {'name': 'Bake', 'identity': 'bake', 'vertices': [[u, v, 0.0] for u, v in square], 'faces': [[0, 1, 2, 3]],
            'material': 'bake', 'uvs': square, 'smooth': False,
            # Image nodes read the UVs under a name of their own; here every such name is the square's.
            'uv_sets': {layer['coordinate_key']: square for layer in nodes.descriptors(baked) if layer.get('projection', 'uv') == 'uv'}}
    camera = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, .5, .5, 5, 1], 'projection': 'ortho', 'ortho_width': 1.0,
              'focal_mm': 50.0, 'film_mm': 36.0}
    if laid:
        mesh['matrix'], camera['matrix'], camera['ortho_width'], _ = solid_frame(region)
        size = SOLID_RESOLUTION
    return {'camera': camera,
            'materials': {'': {'color': [0, 0, 0], 'roughness': 1.0}, 'bake': material},
            'meshes': [mesh], 'lights': [], 'environments': [], 'width': size, 'height': size, 'warnings': []}


def bake(graph, identity, runtime, tile=None, region=None):
    """The path of an EXR holding the node's output over one unit of UV (with tile, over one repeat of that image);
    made if it is not there yet."""
    target, render = prepared(graph, identity, runtime, tile, region=region)
    if render is not None:
        render()
    return target


def written(graph, identity, tile=None, size=None, region=None):
    """(the EXR's path, the scene's text that makes it), the text None where the EXR is made already: what prepared
    renders in a MoonRay of its own, and what the graph editor's node previews hand to one kept loaded (node_previews).
    size, where given, is the picture's side in pixels."""
    from . import rdla
    made = scene(graph, identity, tile, region)
    if size is not None:
        made['width'] = made['height'] = int(size)
    size = made['width']
    # v3 (2026-10-30): previews kept before then made again once, among them flat ones that were kept as made.
    signature = hashlib.sha256(json.dumps(['graph-bake-v3', size, made['materials']['bake']['node_graph'], made['camera'],
                                           files(graph, identity)], sort_keys=True, default=str).encode()).hexdigest()
    target = folder() / (signature + '.exr')
    if target.is_file() and target.stat().st_size:
        return target, None
    return target, rdla.scene_text(made, size, size, 2, 0.0, str(target))


def prepared(graph, identity, runtime, tile=None, size=None, region=None):
    """(the EXR's path, None) where the bake is already made; else (the path it will have, a call that makes it). The
    scene is written here, where Modo may be asked about textures; the call only runs MoonRay, and may be made on
    another thread (the graph editor's node previews). size, where given, is the picture's side in pixels."""
    from . import native
    target, text = written(graph, identity, tile, size, region)
    if text is None:
        return target, None
    runtime = native.find_runtime(runtime)
    source = target.with_suffix('.rdla')
    source.write_text(text, encoding='utf-8')
    environment = native.environment(runtime)
    arguments = [str(Path(runtime) / 'moonray.exe')] + native.arguments(source, target, 0, 'vectorized')

    def render():
        done = subprocess.run(arguments, env=environment, cwd=str(folder()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=120)
        if done.returncode or not target.is_file():
            raise ValueError('MoonRay could not bake the node: ' + done.stdout.decode(errors='replace')[-300:].strip())
        try:
            source.unlink()
        except OSError:
            pass
    return target, render
