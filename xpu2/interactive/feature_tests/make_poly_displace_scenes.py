"""Displaced polygon meshes MoonRay's PolyMesh makes: make_poly_displace_scenes.py <folder> <gray.tx>. A quad cube
displaced by a noise and an image, without uvs, untessellated, camera-adaptive, in parts with one part displaced,
reversed, with primitive attributes and a wireframe map; a cylinder with n-gon caps (a TriMesh) and a cube with a
face split in two triangles (a QuadMesh's degenerate quads)."""
import math
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_subd_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {}')]
namespace = {'__file__': str(here / 'make_subd_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_poly_tmp')]
exec(compile(defs, 'make_subd_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
gray = Path(sys.argv[2]).resolve().as_posix()
folder.mkdir(parents=True, exist_ok=True)
scene, cube, grid = namespace['scene'], namespace['cube'], namespace['grid']

MATS = '\n'.join([
    'NoiseMap_v2("/bumps") { ["space"]=2, ["frequency_multiplier"]=3.0, ["max_level"]=4.5, ["color_A"]=Rgb(0,0,0), ["color_B"]=Rgb(1,1,1) }',
    'ImageMap("/img") { ["texture"]="%s" }' % gray,
    'NormalDisplacement("/dn") { ["height"]=bind(NoiseMap_v2("/bumps"),1.0), ["zero_value"]=0.5, ["height_multiplier"]=0.15 }',
    'NormalDisplacement("/di") { ["height"]=bind(ImageMap("/img"),1.0), ["height_multiplier"]=0.08 }',
    'DwaBaseMaterial("/m") { ["albedo"]=bind(CheckerboardMap("/checker"), Rgb(1,1,1)), ["roughness"]=0.35, ["specular"]=1.0 }',
    'DwaBaseMaterial("/m2") { ["albedo"]=Rgb(0.8,0.3,0.2), ["roughness"]=0.5 }',
])


def pmesh(name, v, faces, uv=None, extra=''):
    counts = ','.join(str(len(f)) for f in faces)
    idx = ','.join(str(i) for f in faces for i in f)
    vl = '{' + ','.join('Vec3(%g,%g,%g)' % p for p in v) + '}'
    ul = ', ["uv_list"]={' + ','.join('Vec2(%g,%g)' % p for p in uv) + '}' if uv else ''
    return ('RdlMeshGeometry("%s") { ["vertex_list"]=%s, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}%s, ["is_subd"]=false, '
            '["smooth_normal"]=true%s }' % (name, vl, counts, idx, ul, extra))


def layer(entries):
    return 'Layer("/layer") { ' + ','.join('{ RdlMeshGeometry("/s"), "%s", DwaBaseMaterial("%s"), LightSet("/lights")%s }'
                                           % (part, mat, ', NormalDisplacement("%s")' % disp if disp else '') for part, mat, disp in entries) + \
        ',{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }'


def one(disp='/dn'):
    return layer([('', '/m', disp)])


v, f, uv = cube(1.4, (0, 1.0, 0))
cases = {
    'pd-cube-noise': scene(pmesh('/s', v, f, uv, ', ["mesh_resolution"]=8'), MATS, one()),
    'pd-cube-image': scene(pmesh('/s', v, f, uv, ', ["mesh_resolution"]=8'), MATS, one('/di')),
    'pd-cube-nouv': scene(pmesh('/s', v, f, None, ', ["mesh_resolution"]=8'), MATS, one()),
    'pd-cube-adaptive': scene(pmesh('/s', v, f, uv, ', ["mesh_resolution"]=16, ["adaptive_error"]=2.0'), MATS, one()),
    'pd-cube-reversed': scene(pmesh('/s', v, f, uv, ', ["mesh_resolution"]=8, ["reverse_normals"]=true'), MATS, one()),
    'pd-cube-parts': scene(pmesh('/s', v, f, uv, ', ["mesh_resolution"]=8, ["part_list"]={"top","rest"}, ["part_face_count_list"]={2,4}, '
                                 '["part_face_indices"]={3,1,0,2,4,5}'), MATS, layer([('top', '/m2', '/dn'), ('rest', '/m', None)])),
}
# Untessellated: a fine quad grid displaced at its own vertices.
gv, gf, guv = grid(16, 3.0, (0, 0.5, 0))
cases['pd-grid-res1'] = scene(pmesh('/s', gv, gf, guv, ', ["mesh_resolution"]=1'), MATS, one())
# A cylinder with 12-gon caps (MoonRay's TriMesh, its n-gons fanned).
n, r, h = 12, 0.7, 1.4
cv = [(r * math.cos(2 * math.pi * i / n), 0.3 + y, r * math.sin(2 * math.pi * i / n)) for y in (0, h) for i in range(n)]
cf = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)] + [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))]
cuv = []
for face in cf:
    cuv += [((cv[k][0] + 1) / 2, (cv[k][1] + cv[k][2] + 1) / 3) for k in face]
cases['pd-ngon'] = scene(pmesh('/s', cv, cf, cuv, ', ["mesh_resolution"]=6'), MATS, one())
# A cube with its top split in two triangles (a QuadMesh: the triangles degenerate quads).
mf = [face for k, face in enumerate(f) if k != 3] + [(f[3][0], f[3][1], f[3][2]), (f[3][0], f[3][2], f[3][3])]
muv = [p for k in range(6) if k != 3 for p in uv[4 * k:4 * k + 4]] + [uv[12], uv[13], uv[14], uv[12], uv[14], uv[15]]
cases['pd-mixed'] = scene(pmesh('/s', v, mf, muv, ', ["mesh_resolution"]=8'), MATS, one())
# Primitive attributes: a colour a vertex read by an AttributeMap; a wireframe map (the tessellated quads' vertices).
vert_cols = ','.join('Rgb(%g,%g,%g)' % (0.2 + 0.8 * (i & 1), 0.2 + 0.8 * ((i >> 1) & 1), 0.2 + 0.8 * ((i >> 2) & 1)) for i in range(len(v)))
fv_cols = ','.join('Rgb(%g,%g,%g)' % ((k * 37 % 10) / 10, (k * 53 % 10) / 10, (k * 71 % 10) / 10) for k in range(24))
ATTRS = '\n'.join([
    'UserData("/vc") { ["color_key"]="vcol", ["color_values_0"]={%s}, ["rate"]=4 }' % vert_cols,
    'UserData("/fvc") { ["color_key"]="fvcol", ["color_values_0"]={%s}, ["rate"]=6 }' % fv_cols,
    'AttributeMap("/am_v") { ["map_type"]=0, ["primitive_attribute_name"]="vcol", ["primitive_attribute_type"]=3, ["default_value"]=Rgb(1,0,1) }',
    'AttributeMap("/am_fv") { ["map_type"]=0, ["primitive_attribute_name"]="fvcol", ["primitive_attribute_type"]=3, ["default_value"]=Rgb(1,0,1) }',
    'DwaBaseMaterial("/mv") { ["albedo"]=bind(AttributeMap("/am_v"), Rgb(1,1,1)), ["roughness"]=0.35, ["specular"]=1.0 }',
    'DwaBaseMaterial("/mfv") { ["albedo"]=bind(AttributeMap("/am_fv"), Rgb(1,1,1)), ["roughness"]=0.35, ["specular"]=1.0 }',
    'WireframeMap("/wire") { ["line_color"]=Rgb(0.05,0.05,0.05), ["fill_color"]=Rgb(0.85,0.85,0.8), ["raster"]=true, ["line_width"]=1.5 }',
    'DwaBaseMaterial("/mw") { ["albedo"]=bind(WireframeMap("/wire"), Rgb(1,1,1)), ["roughness"]=0.35, ["specular"]=1.0 }',
])
prims = ', ["mesh_resolution"]=8, ["primitive_attributes"]={UserData("/vc"), UserData("/fvc")}'
cases['pd-prim-vertex'] = scene(pmesh('/s', v, f, uv, prims), MATS + '\n' + ATTRS, layer([('', '/mv', '/dn')]))
cases['pd-prim-facevarying'] = scene(pmesh('/s', v, f, uv, prims), MATS + '\n' + ATTRS, layer([('', '/mfv', '/dn')]))
cases['pd-wireframe'] = scene(pmesh('/s', v, f, uv, ', ["mesh_resolution"]=4'), MATS + '\n' + ATTRS, layer([('', '/mw', '/dn')]))
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
