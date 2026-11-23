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


def lift(matrix):
    """An Ocean Plane mesh's matrix: its item's height alone (the Y of the item's world matrix), its points at height 0
    (made). The rings stand under the camera wherever the item is, and the sea stays level whatever the item's rotation.
    Held as the mesh's matrix, the item moved up or down is the mesh moved (incremental.refresh_transforms, follow_items)
    as any other item's; with the height in its points, the realtime preview added the move to it again (a plane at 2.5 m
    drawn at 5 m) beside the plane kept from before, and motion blur refused the scene for its two meshes of one name."""
    height = float(matrix[13]) if matrix and len(matrix) == 16 else 0.0
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, height, 0, 1]


def made(entity, camera_matrix, value):
    """The plane as a mesh's points, faces and UVs (one pair per face corner): the points at height 0, the item's height
    being the mesh's matrix (lift), their X and Z the world's. value(key) gives the item's settings. Faces face up."""
    detail, horizon = float(value('detail')), float(value('horizon'))
    tile = max(float(value('tile_size')), 1e-3)
    snap = max(detail, 1e-3) * SNAP
    cx = round(float(camera_matrix[12]) / snap) * snap
    cz = round(float(camera_matrix[14]) / snap) * snap
    radii = rings(detail, horizon)
    angles = [2 * math.pi * k / SEGMENTS for k in range(SEGMENTS)]
    vertices = [[cx, 0.0, cz]]
    for r in radii:
        vertices += [[cx + r * math.cos(a), 0.0, cz + r * math.sin(a)] for a in angles]

    def ring(i, k):
        return 1 + i * SEGMENTS + k % SEGMENTS
    # The centre's fan, two of its wedges a quad (centre, then three points of the first ring), then quads between each
    # ring and the next; each wound to face up. Quads throughout: MoonRay's even tessellation (realtime's sea, rdla) gives
    # a triangle among quads a degenerate edge as many points as the others, and the waves on them came out as walls and
    # shards metres high (the user's dragon over an Ocean Plane, 2026-11-23: "a batch of spikes around the dragon").
    faces = [[0, ring(0, k + 2), ring(0, k + 1), ring(0, k)] for k in range(0, SEGMENTS - 1, 2)]
    if SEGMENTS % 2:
        faces.append([0, ring(0, SEGMENTS), ring(0, SEGMENTS - 1)])
    for i in range(len(radii) - 1):
        faces += [[ring(i, k), ring(i, k + 1), ring(i + 1, k + 1), ring(i + 1, k)] for k in range(SEGMENTS)]
    uvs = [[vertices[v][0] / tile, vertices[v][2] / tile] for face in faces for v in face]
    return vertices, faces, uvs


# Where an Ocean Plane's waves begin to fade toward the horizon in MoonRay and XPU2 (fade, nodes.fade_ocean), as twice
# the tiles of wave one pixel spans along the view there (which grows as the distance squared over the camera's height
# above the water). On a tester's sea (camera 5.6 m up, 50 mm, 1280 wide) dark speckle began about 12 pixels under the
# horizon, where a pixel spans a tile (the rows above held 7-18% dark pixels, the waves' own shading; 23% at 8 pixels,
# 90% at 2). The fade starts twice as many rows down (a quarter of a tile), so that it is halfway by then and eases in
# as MoonLightIPR's far sea does; starting at the speckle, grain stayed in the last rows before the horizon.
FADE_START_WAVES = 0.25
# The water's roughness at the horizon, where its waves have faded: a soft sheen of the sky, as MoonLightIPR's far sea.
FADE_ROUGHNESS = 0.15


def fade(camera, width, height, tile, far=20000.0, toward_horizon=0.0):
    """An Ocean Plane's fade toward the horizon for its sea (nodes.fade_ocean): the camera's place on the water
    (origin), a point far along its view over the ground (end), and the share of that distance where the fade begins
    (ratio): d = sqrt(FADE_START_WAVES x tile x height / (2 x pixel angle)). toward_horizon (the item's Horizon Fade,
    0 to 1) moves the start toward the horizon by the rows of the picture: at 0.5, half as many rows under the horizon
    (twice as far). None for an orthographic camera or one looking straight down."""
    m = camera.get('matrix') or [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    if camera.get('projection', 'persp') != 'persp':
        return None
    forward = [-m[8], 0.0, -m[10]]
    length = math.hypot(forward[0], forward[2])
    if length < 1e-6:
        return None
    forward = [forward[0] / length, 0.0, forward[2] / length]
    focal, film = float(camera.get('focal_mm') or 50.0), float(camera.get('film_mm') or 36.0)
    pixel = film / max(focal, 1e-3) / max(int(width or 1920), 1)
    above = max(m[13] - height, 0.1)
    start = math.sqrt(FADE_START_WAVES * tile * above / (2.0 * pixel))
    start /= max(1.0 - 0.95 * min(max(float(toward_horizon or 0.0), 0.0), 1.0), 0.05)
    far = max(float(far or 20000.0), start * 2.0)
    return {'origin': [m[12], height, m[14]], 'end': [m[12] + forward[0] * far, height, m[14] + forward[2] * far],
            'ratio': start / far, 'roughness': FADE_ROUGHNESS}


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

    def number(key, default):
        # Where a plane made before the setting was added has none: as the sea was before.
        try:
            held = float(value(key))
        except (KeyError, TypeError, ValueError):
            return default
        return min(1.0, max(0.0, held))
    rough, foam_rough = number('roughness', 0.1), number('foam_roughness', 0.5)
    graph = nodes.new('DwaBaseMaterial', {'albedo': water, 'roughness': rough, 'refractive_index': 1.33, 'metallic': 0.0})
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
                               'parameters': {'bg': [rough] * 3, 'fg': [foam_rough] * 3, 'mix': 0.0}}
    graph['nodes']['surface']['inputs'].update(albedo='colour', roughness='rough')
    return {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph, 'node_override': True,
            'color': water, 'roughness': rough}


def apply(result, warnings):
    """The scene read (host.snapshot) with each Ocean Plane item made a mesh, wearing its sea, and taken out of its MoonRay
    items, which no engine has a class for. Left out, with a notice, where the Ocean nodes override is off."""
    from . import entities, native
    # A reading that keeps the meshes it had (an edit followed) holds the planes made at its last reading: they are made
    # again here, where the camera now stands, and the old ones let go (two of one name refused motion blur).
    if 'meshes' in result:
        result['meshes'] = [mesh for mesh in result['meshes'] if not mesh.get('_ocean_plane')]
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
            tile = max(float(value('tile_size')), 1e-3)
            materials[tag] = material(value, tile)
            # Its waves fade out toward the horizon in MoonRay and XPU2, as MoonLightIPR's do (nodes.fade_ocean); not in
            # MoonLightIPR's reading, where the fade would change the material at every move of the camera.
            try:
                from .host import modo_displaces
                moonray = modo_displaces()
            except ImportError:
                moonray = True
            faded = None
            if moonray:
                try:
                    toward = float(value('horizon_fade') or 0.0)
                except (KeyError, TypeError, ValueError):
                    toward = 0.0
                faded = fade(result.get('camera') or {}, result.get('width'), lift(entity.get('matrix'))[13], tile,
                             float(value('horizon') or 20000.0), toward)
            if faded:
                materials[tag]['node_graph']['nodes']['sea']['_fade'] = faded
        mesh = {'name': entity.get('name', 'Ocean Plane'), 'identity': entity.get('identity', ''), 'vertices': vertices,
                'faces': faces, 'uvs': uvs, 'material': tag, 'smooth': True, 'matrix': lift(entity.get('matrix')),
                '_ocean_plane': True}
        result.setdefault('meshes', []).append(mesh)
    return result
