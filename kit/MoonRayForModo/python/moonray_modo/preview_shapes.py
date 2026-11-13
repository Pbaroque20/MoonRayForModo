"""Other things than the MoonRay Widget for the graph editor's material preview to show a material on (material_preview):
water, a wide plane seen low against a low sun, for displacement such as the Ocean node's; subsurface, a ring and a
ball lit from behind, where light comes through the thin parts; velvet, a soft cushion between grazing lights, where a
sheen shows. Each is made here, its meshes with UVs from 0 to 1, at the preview's Scale."""
import math

# What the preview's Shape choice offers: its key, its label, and its tooltip.
SHAPES = (('widget', 'MoonRay Widget', 'The MoonRay Widget on its stand, in studio light.'),
          ('water', 'Water', 'A wide plane seen low against a low sun under a sky: for displacement and water, such as the '
                             'Ocean node (the plane is 100 units across at Scale 1, its UVs 0 to 1 across it).'),
          ('subsurface', 'Subsurface', 'A ring and a ball lit from behind: light shows through their thin parts, for '
                                       'subsurface scattering and translucency.'),
          ('velvet', 'Velvet', 'A soft cushion between grazing lights: its edges catch the sheen of velvet and fuzz.'))


def look_at(eye, target):
    """A Modo-style matrix: its axes in rows, looking down its own -Z."""
    back = [e - t for e, t in zip(eye, target)]
    length = math.sqrt(sum(v * v for v in back)) or 1.0
    back = [v / length for v in back]
    right = [back[2], 0.0, -back[0]]
    length = math.sqrt(sum(v * v for v in right)) or 1.0
    right = [v / length for v in right]
    up = [back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2], back[0] * right[1] - back[1] * right[0]]
    return right + [0.0] + up + [0.0] + back + [0.0] + list(eye) + [1.0]


def surface(name, rows, columns, place, wrap_u=False, wrap_v=False):
    """A mesh of quads over a grid of (u, v) from 0 to 1, each point placed by place(u, v); its UVs those (u, v)."""
    across, down = columns + (0 if wrap_u else 1), rows + (0 if wrap_v else 1)
    vertices = [list(place(i / columns, j / rows)) for j in range(down) for i in range(across)]
    faces, uvs = [], []
    for j in range(rows):
        for i in range(columns):
            corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            faces.append([(b % down) * across + (a % across) for a, b in corners])
            uvs.extend([a / columns, b / rows] for a, b in corners)
    return {'name': name, 'identity': 'preview/' + name, 'vertices': vertices, 'faces': faces, 'uvs': uvs, 'smooth': True}


def sky(intensity=1.0):
    # Below the horizon the haze the sky has at it: where the plane ends, the water meets the sky with no band between.
    return {'kind': 'grad4', 'name': 'Preview sky', 'identity': 'preview/sky', 'intensity': intensity, 'zenith': [.16, .3, .62],
            'sky': [.62, .72, .86], 'ground': [.62, .72, .86], 'nadir': [.62, .72, .86], 'sky_exponent': 4.0, 'ground_exponent': 4.0}


def water(scale):
    s = lambda point: [v * scale for v in point]
    plane = surface('water', 250, 250, lambda u, v: s([(u - .5) * 100, 0.0, (v - .5) * 100]))
    return {'meshes': [plane],
            'camera': {'identity': 'preview/camera', 'matrix': look_at(s([0, 2.4, 40]), s([0, 0, 18])), 'focal_mm': 35, 'film_mm': 36},
            'lights': [{'identity': 'preview/sun', 'kind': 'DistantLight', 'matrix': look_at([0, 0, 0], [0, -.18, 1]),
                        'color': [1, .88, .7], 'intensity': 4.0, 'angle': 1.0}],
            'environments': [sky()]}


def subsurface(scale):
    s = lambda point: [v * scale for v in point]

    def ring(u, v):
        # Standing on the floor, facing the camera, its tube 0.44 thick: the light behind shows through it.
        a, b = 2 * math.pi * u, 2 * math.pi * v
        reach = .7 + .22 * math.cos(b)
        return s([reach * math.cos(a) - .6, reach * math.sin(a) + .92, .22 * math.sin(b)])

    def ball(u, v):
        a, b = 2 * math.pi * u, math.pi * v
        return s([.55 * math.sin(b) * math.cos(a) + .85, .55 - .55 * math.cos(b), .55 * math.sin(b) * math.sin(a) + .3])
    floor = surface('floor', 1, 1, lambda u, v: s([(u - .5) * 12, 0.0, (v - .5) * 12]))
    return {'meshes': [surface('ring', 48, 96, ring, wrap_u=True, wrap_v=True), surface('ball', 48, 96, ball, wrap_u=True), floor],
            'camera': {'identity': 'preview/camera', 'matrix': look_at(s([0, 1.5, 6.8]), s([.1, .75, 0])), 'focal_mm': 50, 'film_mm': 36},
            'lights': [{'identity': 'preview/back', 'kind': 'RectLight', 'matrix': look_at(s([0, 1.5, -2.6]), s([0, .8, 0])),
                        'color': [1, .95, .9], 'intensity': 30.0, 'width': 2.5 * scale, 'height': 2.5 * scale},
                       {'identity': 'preview/fill', 'kind': 'RectLight', 'matrix': look_at(s([2.5, 2.5, 3.5]), s([0, .6, 0])),
                        'color': [1, 1, 1], 'intensity': 8.0, 'width': 2 * scale, 'height': 2 * scale}],
            'environments': [], 'floor': 'floor'}


def velvet(scale):
    s = lambda point: [v * scale for v in point]

    def cushion(u, v):
        # A rounded box (a superellipsoid), soft at its edges, sagging a little at the middle of its top.
        a, b = 2 * math.pi * u, math.pi * v - math.pi / 2
        power = lambda t, e: math.copysign(abs(t) ** e, t)
        x = power(math.cos(b), .45) * power(math.cos(a), .45)
        z = power(math.cos(b), .45) * power(math.sin(a), .45)
        y = power(math.sin(b), .6)
        sag = .08 * (1 - min(1.0, x * x + z * z)) if y > 0 else 0.0
        return s([1.15 * x, .36 * y + .36 - sag, .85 * z])
    floor = surface('floor', 1, 1, lambda u, v: s([(u - .5) * 12, 0.0, (v - .5) * 12]))
    return {'meshes': [surface('cushion', 64, 128, cushion, wrap_u=True), floor],
            'camera': {'identity': 'preview/camera', 'matrix': look_at(s([0, 2.4, 5.2]), s([0, .3, 0])), 'focal_mm': 50, 'film_mm': 36},
            'lights': [{'identity': 'preview/left', 'kind': 'RectLight', 'matrix': look_at(s([-3, 1.0, -1]), s([0, .4, 0])),
                        'color': [1, .97, .92], 'intensity': 20.0, 'width': 2 * scale, 'height': 1.5 * scale},
                       {'identity': 'preview/right', 'kind': 'RectLight', 'matrix': look_at(s([3, 1.0, -1]), s([0, .4, 0])),
                        'color': [.92, .96, 1], 'intensity': 20.0, 'width': 2 * scale, 'height': 1.5 * scale},
                       {'identity': 'preview/key', 'kind': 'RectLight', 'matrix': look_at(s([1, 3.5, 3.5]), s([0, .3, 0])),
                        'color': [1, 1, 1], 'intensity': 12.0, 'width': 2.5 * scale, 'height': 2.5 * scale}],
            'environments': [], 'floor': 'floor'}


def made(shape, scale):
    """The shape's meshes, camera, lights and environments, at that scale; None for the MoonRay Widget."""
    return {'water': water, 'subsurface': subsurface, 'velvet': velvet}.get(shape, lambda _: None)(scale)
