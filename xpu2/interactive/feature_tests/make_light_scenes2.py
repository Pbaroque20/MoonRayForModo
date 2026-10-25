"""More light test scenes: make_light_scenes2.py <folder> <texture.tx> <pixel samples>. Mesh lights, clear radius,
shadow distances, a two-sided sphere and cylinder lights, against the same floor, wall and balls."""
import math
import sys
from pathlib import Path

folder, tex, samples = Path(sys.argv[1]).resolve(), sys.argv[2].replace('\\', '/'), int(sys.argv[3])
folder.mkdir(parents=True, exist_ok=True)
src = (Path(__file__).parent / 'make_light_scenes.py').read_text(encoding='utf-8')
ns = {}
exec(src.split("FILL = ")[0].replace("folder, tex, hdri, samples = Path(sys.argv[1]).resolve(), sys.argv[2].replace('\\\\', '/'), sys.argv[3].replace('\\\\', '/'), int(sys.argv[4])",
                                       "folder, tex, hdri, samples = None, None, None, %d" % samples), ns)
BASE, GEOM, LAYER = ns['BASE'], ns['GEOM'], ns['LAYER']
FILL = 'EnvLight("/fill") { ["intensity"]=0.05 }\n'


def mesh(name, vertices, faces, extra=''):
    return 'RdlMeshGeometry("%s") { ["vertex_list"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=false%s }\n' % (
        name, ','.join('Vec3(%.5f,%.5f,%.5f)' % v for v in vertices), ','.join(str(len(f)) for f in faces),
        ','.join(str(i) for f in faces for i in f), extra)


# An arch of quads over the balls, facing down: a QuadMesh.
arch_v, arch_f = [], []
for i in range(9):
    a = math.pi * (0.15 + 0.7 * i / 8)
    x, y = 3.0 * math.cos(a), 1.2 + 3.0 * math.sin(a)
    arch_v += [(x, y, -1.2), (x, y, 1.2)]
for i in range(8):
    arch_f.append((2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2))  # winding: normals toward the arch's centre (down)
ARCH = mesh('/emitter', arch_v, arch_f)
# A ring of triangles and a hexagon (a TriMesh: the hexagon is fanned or clipped), in two parts, facing down.
ring_v = [(0.0, 4.2, 0.5)]
for k in range(6):
    a = 2 * math.pi * k / 6
    ring_v.append((1.4 * math.cos(a), 4.2, 0.5 + 1.4 * math.sin(a)))
hex_base = len(ring_v)
for k in range(6):
    a = 2 * math.pi * k / 6
    ring_v.append((-2.6 + 0.8 * math.cos(a), 3.6, 0.8 * math.sin(a)))
ring_f = [(0, 1 + k, 1 + (k + 1) % 6) for k in range(6)] + [tuple(hex_base + k for k in range(6))]
RING = mesh('/emitter', ring_v, ring_f, ', ["part_list"]={"fan","hexagon"}, ["part_face_count_list"]={6,1}, ["part_face_indices"]={0,1,2,3,4,5,6}')

CASES = {
    'mesh-quads': (FILL + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["intensity"]=2, ["color"]=Rgb(1,0.8,0.6), ["visible_in_camera"]=1 }\n', ARCH),
    'mesh-tris': (FILL + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["intensity"]=3, ["visible_in_camera"]=1 }\n', RING),
    'mesh-parts': (FILL + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["parts"]={"hexagon"}, ["intensity"]=3, ["visible_in_camera"]=1, ["normalized"]=false }\n', RING),
    'clear-radius': (FILL + 'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, -0.6,4.5,0.3,1), ["width"]=1.5, ["height"]=1.5, ["intensity"]=4, ["clear_radius"]=3.0 }\n', ''),
    'clear-falloff': (FILL + 'SphereLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, -0.4,3.6,0.6,1), ["radius"]=0.3, ["intensity"]=4, ["clear_radius"]=1.5, ["clear_radius_falloff_distance"]=2.5, ["clear_radius_interpolation_type"]=3 }\n', ''),
    'shadow-distances': (FILL + 'SpotLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,5,0.5,1), ["lens_radius"]=0.4, ["outer_cone_angle"]=70, ["inner_cone_angle"]=40, ["intensity"]=40, ["min_shadow_distance"]=0.8, ["max_shadow_distance"]=3.5 }\n', ''),
    'sphere-two-sided': (FILL + 'SphereLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,3.6,1.5,1), ["radius"]=0.6, ["intensity"]=4, ["sidedness"]=2, ["visible_in_camera"]=1 }\n', ''),
    'cylinder': (FILL + 'CylinderLight("/key") { ["node_xform"]=Mat4(0,1,0,0, -1,0,0,0, 0,0,1,0, 0,3.8,0.8,1), ["radius"]=0.12, ["height"]=4, ["intensity"]=4, ["visible_in_camera"]=1 }\n', ''),
    'cylinder-texture': (FILL + 'CylinderLight("/key") { ["node_xform"]=Mat4(0,1,0,0, -1,0,0,0, 0,0,1,0, 0,3.8,0.8,1), ["radius"]=0.12, ["height"]=4, ["intensity"]=4, ["visible_in_camera"]=1, ["texture"]="%s", ["texture_filter"]=1 }\n' % tex, ''),
}
for name, (light, extra) in CASES.items():
    lights = [l.split('(')[0] + '("' + l.split('"')[1] + '")' for l in light.strip().split('\n')]
    text = BASE + light + 'LightSet("/lights") { %s }\n' % ', '.join(lights) + GEOM + extra + LAYER
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(' '.join(CASES))
