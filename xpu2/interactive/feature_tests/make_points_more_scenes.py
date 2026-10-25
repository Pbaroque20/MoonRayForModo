"""More point and curve scenes: make_points_more_scenes.py <folder>. The point scenes' spheres in two parts of two
materials (and radii a part), with screen-space radii, instanced by an instancer, shadow-linked away from the key light;
curves with screen-space radii and instanced."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_points_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {')] if 'cases = {' in source else source
folder = Path(sys.argv[1]).resolve()
namespace = {'__file__': str(here / 'make_points_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(folder)]
exec(compile(defs, 'make_points_scenes.py', 'exec'), namespace)
sys.argv = argv
scene, vec3s, mat, translate, P, R, N = (namespace[k] for k in ('scene', 'vec3s', 'mat', 'translate', 'P', 'R', 'N'))

M2 = 'DwaBaseMaterial("/m2") { ["albedo"]=Rgb(0.2,0.5,0.9), ["roughness"]=0.2, ["specular"]=1.0 }'
PTS = 'RdlPointGeometry("/pts") { ["vertex_list_0"]=%s, ["radius_list"]={%s}%s }'
radii = ','.join('%.4g' % r for r in R)
parts = ', ["part_list"]={"a","b"}, ["part_indices"]={%s}' % ','.join(str(i % 2) for i in range(N))


def two_parts(text):
    return text.replace('{ RdlPointGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }',
                        '{ RdlPointGeometry("/pts"), "a", DwaBaseMaterial("/m"), LightSet("/lights") }, '
                        '{ RdlPointGeometry("/pts"), "b", DwaBaseMaterial("/m2"), LightSet("/lights") }')


cases = {
    'ptm-parts': two_parts(scene(PTS % (vec3s(P), radii, parts), M2)),
    'ptm-part-radii': two_parts(scene('RdlPointGeometry("/pts") { ["vertex_list_0"]=%s, ["radius_list"]={0.08,0.2}%s }' % (vec3s(P), parts), M2)),
    'ptm-ssr': scene(PTS % (vec3s(P), ','.join('%.4g' % (r * 6) for r in R), ', ["use_screen_space_radius"]=true')),
    'ptm-ssr-attrs': scene(PTS % (vec3s(P), radii, ', ["use_screen_space_radius"]=true, ["primitive_attributes"]={UserData("/d0"), UserData("/d1"), '
                                  'UserData("/r0"), UserData("/r1")}'),
                           'UserData("/d0") { ["float_key"]="min_distance", ["float_values_0"]={3.0} }\n'
                           'UserData("/d1") { ["float_key"]="max_distance", ["float_values_0"]={8.0} }\n'
                           'UserData("/r0") { ["float_key"]="min_distance_radius", ["float_values_0"]={2.0} }\n'
                           'UserData("/r1") { ["float_key"]="max_distance_radius", ["float_values_0"]={6.0} }'),
}
# Shadow linking: the points cast no shadow from the key light.
shadow = scene(PTS % (vec3s(P), radii, ''), 'ShadowSet("/ss") { RectLight("/key") }').replace(
    '{ RdlPointGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }', '{ RdlPointGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights"), ShadowSet("/ss") }')
cases['ptm-shadowset'] = shadow
# An instancer of the points (three copies).
inst = scene('RdlPointGeometry("/ref") { ["vertex_list_0"]=%s, ["radius_list"]={%s} }\n'
             'RdlInstancerGeometry("/pts") { ["method"]=2, ["references"]={RdlPointGeometry("/ref")}, ["xform_list"]={%s,%s,%s} }'
             % (vec3s(P[:20]), ','.join('%.4g' % r for r in R[:20]), mat(translate(-1.5, 0, 0)), mat(translate(0, 0.3, -0.5)), mat(translate(1.6, 0, 0.3))))
inst = inst.replace('GeometrySet("/geometry") { RdlPointGeometry("/pts")', 'GeometrySet("/geometry") { RdlInstancerGeometry("/pts")')
inst = inst.replace('{ RdlPointGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }',
                    '{ RdlPointGeometry("/ref"), "", DwaBaseMaterial("/m"), LightSet("/lights") }, { RdlInstancerGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }')
cases['ptm-instanced'] = inst
# Curves: linear strands up from the floor, screen-space radii; instanced.
curves_v, counts = [], []
for i in range(24):
    x, z = -2.0 + (i % 6) * 0.8, -1.0 + (i // 6) * 0.6
    curves_v += [(x, 0.0, z), (x + 0.15, 0.6, z + 0.05), (x + 0.1, 1.2, z - 0.05)]
    counts.append(3)
CV = 'RdlCurveGeometry("%s") { ["curves_vertex_count"]={%s}, ["vertex_list_0"]=%s, ["radius_list"]={%s}, ["curve_type"]=0%s }'
curves = CV % ('/pts', ','.join(map(str, counts)), vec3s(curves_v), '0.004', ', ["use_screen_space_radius"]=true')
cases['cvm-ssr'] = scene(curves).replace('RdlPointGeometry("/pts")', 'RdlCurveGeometry("/pts")')
cinst = scene(CV % ('/ref', ','.join(map(str, counts)), vec3s(curves_v), '0.03', '') + '\n'
              'RdlInstancerGeometry("/pts") { ["method"]=2, ["references"]={RdlCurveGeometry("/ref")}, ["xform_list"]={%s,%s} }'
              % (mat(translate(-0.4, 0, 0)), mat(translate(0.5, 0, 0.6))))
cinst = cinst.replace('GeometrySet("/geometry") { RdlPointGeometry("/pts")', 'GeometrySet("/geometry") { RdlInstancerGeometry("/pts")')
cinst = cinst.replace('{ RdlPointGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }',
                      '{ RdlCurveGeometry("/ref"), "", DwaBaseMaterial("/m"), LightSet("/lights") }, { RdlInstancerGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }')
cases['cvm-instanced'] = cinst
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
