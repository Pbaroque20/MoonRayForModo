"""The Ocean Plane, a MoonRay item of the kit's own (entity_catalog: OceanPlaneGeometry, part of the Ocean nodes
override): a sea that reaches the horizon, set up the moment it is added.

MoonRay has no plane of its own, nor any engine an endless one, so at each reading of the scene the kit makes it a mesh
(made): rings around the point under the camera, its points Detail apart next to the camera and spreading with the
distance out to the Horizon, at the height of the item. Its UVs are fixed to the world, one unit a tile (Tile Size), so
the waves stay where they are as the camera moves and the rings follow it. It wears a sea made from the item's own
settings, the Ocean node's (the graph editor's), with foam in its colour and roughness, unless its material tag names a
Modo material, whose Ocean node then makes the sea. Every engine then takes it as any displaced mesh: MoonRay and XPU2
cut it finer where it is near (Displacement Tessellation), MoonLightIPR splits and displaces it itself."""
import math

CLASS = 'OceanPlaneGeometry'
import os
# Points around each ring: next to the camera they are about Detail apart (MOONRAY_MODO_OCEAN_PLANE_SEGMENTS for tests).
SEGMENTS = int(os.environ.get('MOONRAY_MODO_OCEAN_PLANE_SEGMENTS') or 64)
SNAP = 16                   # the rings' centre moves in steps of this many Detail, so a camera move keeps them still
MATERIAL_PREFIX = '|ocean plane|'
OCEAN_KEYS = ('resolution', 'wind_speed', 'wind_direction', 'wave_height', 'choppiness', 'small_waves', 'wind_alignment',
              'against_wind', 'depth', 'seed', 'time_scale', 'time_offset', 'loop', 'foam_threshold', 'cascades',
              'swell_height', 'swell_length', 'swell_direction', 'crest_start')
# Where a plane made before Crest Colour was added has none: the crests lit a little brighter and greener than the water.
CREST_COLOR = (0.03, 0.15, 0.12)


def rings(detail, horizon):
    """The rings' radii, from the camera out: Detail apart at first, then each a step farther as far again as the
    points around it are apart, the last at the horizon."""
    detail = max(float(detail), 1e-3)
    horizon = max(float(horizon), detail * 2)
    step = 2 * math.pi / SEGMENTS
    radii, r = [], detail
    # Next to the camera, rings Detail apart until the points around a ring are as far apart.
    while r < detail / step and r < horizon:
        radii.append(r)
        r += detail
    while r < horizon:
        radii.append(r)
        r *= 1 + step
    radii.append(horizon)
    return radii


def made(entity, camera_matrix, value):
    """The plane as a mesh's points, faces and UVs (one pair per face corner), world space. value(key) gives the item's
    settings. Faces face up."""
    detail, horizon = float(value('detail')), float(value('horizon'))
    tile = max(float(value('tile_size')), 1e-3)
    height = float((entity.get('matrix') or [0] * 16)[13])
    snap = max(detail, 1e-3) * SNAP
    cx = round(float(camera_matrix[12]) / snap) * snap
    cz = round(float(camera_matrix[14]) / snap) * snap
    radii = rings(detail, horizon)
    angles = [2 * math.pi * k / SEGMENTS for k in range(SEGMENTS)]
    vertices = [[cx, height, cz]]
    for r in radii:
        vertices += [[cx + r * math.cos(a), height, cz + r * math.sin(a)] for a in angles]

    def ring(i, k):
        return 1 + i * SEGMENTS + k % SEGMENTS
    # The centre's fan, then quads between each ring and the next; each wound to face up.
    faces = [[0, ring(0, k + 1), ring(0, k)] for k in range(SEGMENTS)]
    for i in range(len(radii) - 1):
        faces += [[ring(i, k), ring(i, k + 1), ring(i + 1, k + 1), ring(i + 1, k)] for k in range(SEGMENTS)]
    uvs = [[vertices[v][0] / tile, vertices[v][2] / tile] for face in faces for v in face]
    return vertices, faces, uvs


def material(value, tile):
    """The sea the item's settings make: MoonRay's DwaBase water with the Ocean node's waves as its Vector Displacement,
    the crests' glow (Ocean Crest) over its colour, then the foam over its colour and roughness (as the asset library's ocean). Its tiles are one UV unit each, Tile Size wide
    (the sea made at ocean.FITTED_SIZE and scaled whole to it)."""
    from . import nodes, node_defaults
    from .ocean import FITTED_SIZE
    water = [float(c) for c in value('water_color')]
    foam = [float(c) for c in value('foam_color')]
    try:
        crest = [float(c) for c in value('crest_color')]
    except (KeyError, TypeError, ValueError):
        crest = list(CREST_COLOR)
    graph = nodes.new('DwaBaseMaterial', {'albedo': water, 'roughness': 0.03, 'refractive_index': 1.33, 'metallic': 0.0})
    params = {key: value(key) for key in OCEAN_KEYS}
    params.update(fit_to_mesh=False, repeat=[1.0, 1.0])
    graph['nodes']['sea'] = {'type': 'ocean', 'position': [-300, 300], 'inputs': {}, 'parameters': params,
                             '_scale': tile / FITTED_SIZE}
    graph['nodes']['waves'] = {'type': 'VectorDisplacement', 'position': [0, 300], 'inputs': {'vector': 'sea'},
                               'parameters': node_defaults.parameters('VectorDisplacement')}
    graph['displacement'] = 'waves'
    graph['nodes']['foam'] = {'type': 'ocean_foam', 'position': [-300, 0], 'inputs': {}, 'parameters': {}}
    # The light through the crests: the water's colour turning to Crest Colour where the waves stand highest.
    graph['nodes']['crest'] = {'type': 'ocean_crest', 'position': [-300, -150], 'inputs': {}, 'parameters': {}}
    graph['nodes']['glow'] = {'type': 'mix', 'position': [-150, -150], 'inputs': {'mix': 'crest'},
                              'parameters': {'bg': water, 'fg': crest, 'mix': 0.0}}
    graph['nodes']['colour'] = {'type': 'mix', 'position': [0, 0], 'inputs': {'mix': 'foam', 'bg': 'glow'},
                                'parameters': {'bg': water, 'fg': foam, 'mix': 0.0}}
    graph['nodes']['rough'] = {'type': 'mix', 'position': [0, 120], 'inputs': {'mix': 'foam'},
                               'parameters': {'bg': [0.03] * 3, 'fg': [0.5] * 3, 'mix': 0.0}}
    graph['nodes']['surface']['inputs'].update(albedo='colour', roughness='rough')
    return {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph, 'node_override': True,
            'color': water, 'roughness': 0.03}


def apply(result, warnings):
    """The scene read (host.snapshot) with each Ocean Plane item made a mesh, wearing its sea, and taken out of its MoonRay
    items, which no engine has a class for. Left out, with a notice, where the Ocean nodes override is off."""
    from . import entities, native
    planes = [e for e in result.get('entities') or [] if e.get('class') == CLASS]
    if not planes:
        return result
    result['entities'] = [e for e in result['entities'] if e.get('class') != CLASS]
    if not native.ocean():
        warnings.append('Ocean Plane is left out: turn on Ocean nodes in MoonShine graphs, in MoonRay Source Overrides.')
        return result
    camera = (result.get('camera') or {}).get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    materials = result.setdefault('materials', {})
    for entity in planes:
        def value(key, entity=entity):
            return entities.value(entity, key)
        try:
            vertices, faces, uvs = made(entity, camera, value)
        except (TypeError, ValueError, KeyError) as exc:
            warnings.append('Ocean Plane %s is left out: %s.' % (entity.get('name', ''), exc))
            continue
        tag = str(value('modo_material') or '')
        if not tag or tag not in materials:
            if tag:
                warnings.append('Ocean Plane %s: no material is tagged %s; it is rendered with the sea its own settings make.'
                                % (entity.get('name', ''), tag))
            tag = MATERIAL_PREFIX + str(entity.get('identity', ''))
            materials[tag] = material(value, max(float(value('tile_size')), 1e-3))
        mesh = {'name': entity.get('name', 'Ocean Plane'), 'identity': entity.get('identity', ''), 'vertices': vertices,
                'faces': faces, 'uvs': uvs, 'material': tag, 'smooth': True, 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                '_ocean_plane': True}
        result.setdefault('meshes', []).append(mesh)
    return result
