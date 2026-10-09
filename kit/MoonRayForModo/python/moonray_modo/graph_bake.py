"""Bake what is wired to a material's input into an image, with MoonRay itself.

MoonLight has one fixed material model and reads only images, so a ramp, a noise, a colour
correction or a chain of math nodes in a material graph means nothing to it. MoonRay knows
them all: it renders the node's output on a flat square that fills the picture, one unit of
UV across, and the picture is the node as a texture. The bake is kept, keyed by the nodes
that feed it, so it is made once per change.

What depends on the surface's UVs alone is baked over one unit of UV. A RampMap or GradientMap
laid out in the world or in the object's space is baked over one unit of that space instead,
and the plugin projects it back onto the surface. MoonRay's default for those two, render
space, is the camera's own space and is not followed. A node that looks at the normal, the camera
or anything else (a projection, a curvature map) has no single picture, and is named instead.
"""
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
             'VectorDisplacement', 'CombineDisplacement')
SPACES = (nodes.SPACE_WORLD, nodes.SPACE_OBJECT, nodes.SPACE_TEXTURE)
RAMP_BY_INPUT = 8
# Nodes that read the surface's UVs, which cannot share a picture with one laid out in space.
READ_UVS = ('image', 'texcoord', 'checker', 'ImageMap', 'CheckerboardMap', 'UVTransformMap', 'UsdUVTexture', 'UsdTransform2d')


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
    spatial, over_uvs = [], False
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
        if kind == 'normalmap' or nodes.category(kind) != 'map':
            return kind, None
        over_uvs = over_uvs or kind in READ_UVS
    if len(spatial) > 1 or (spatial and over_uvs):
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
    root = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo/GraphBakes'
    root.mkdir(parents=True, exist_ok=True)
    return root


def scene(graph, identity):
    """A scene that is nothing but the node, shown on a square that fills an orthographic view.

    The square is one unit across with a corner at the origin, so a point's position is also
    its UV: a node laid out in space is baked over one unit of that space. A GradientMap is
    turned to run along the square's first axis, which is where its projection puts it.
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
    baked['nodes']['bake'] = {'type': 'DwaEmissiveMaterial', 'parameters': {'show_emission': True}, 'inputs': {'emission': identity}}
    material = {'name': 'bake', 'color': [0, 0, 0], 'roughness': 1.0, 'shader': 'DwaBaseMaterial', 'native_shader': 'DwaEmissiveMaterial',
                'native_parameters': {'show_emission': True}, 'node_graph': baked, 'node_override': True}
    square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    mesh = {'name': 'Bake', 'identity': 'bake', 'vertices': [[u, v, 0.0] for u, v in square], 'faces': [[0, 1, 2, 3]],
            'material': 'bake', 'uvs': square, 'smooth': False,
            # Image nodes read the UVs under a name of their own; here every such name is the square's.
            'uv_sets': {layer['coordinate_key']: square for layer in nodes.descriptors(baked) if layer.get('projection', 'uv') == 'uv'}}
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, .5, .5, 5, 1], 'projection': 'ortho', 'ortho_width': 1.0,
                       'focal_mm': 50.0, 'film_mm': 36.0},
            'materials': {'': {'color': [0, 0, 0], 'roughness': 1.0}, 'bake': material},
            'meshes': [mesh], 'lights': [], 'environments': [], 'width': RESOLUTION, 'height': RESOLUTION, 'warnings': []}


def bake(graph, identity, runtime):
    """The path of an EXR holding the node's output over one unit of UV; made if it is not there yet."""
    from . import native, rdla
    signature = hashlib.sha256(json.dumps(['graph-bake-v2', RESOLUTION, scene(graph, identity)['materials']['bake']['node_graph'],
                                           files(graph, identity)], sort_keys=True, default=str).encode()).hexdigest()
    target = folder() / (signature + '.exr')
    if target.is_file() and target.stat().st_size:
        return target
    runtime = native.find_runtime(runtime)
    text = rdla.scene_text(scene(graph, identity), RESOLUTION, RESOLUTION, 2, 0.0, str(target))
    source = folder() / (signature + '.rdla')
    source.write_text(text, encoding='utf-8')
    done = subprocess.run([str(Path(runtime) / 'moonray.exe')] + native.arguments(source, target, 0, 'vectorized'),
                          env=native.environment(runtime), cwd=str(folder()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=120)
    if done.returncode or not target.is_file():
        raise ValueError('MoonRay could not bake the node: ' + done.stdout.decode(errors='replace')[-300:].strip())
    try:
        source.unlink()
    except OSError:
        pass
    return target
