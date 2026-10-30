"""Motion blur on instanced points and curves, and screen-space radii on moving curves: make_motion_instances_scenes.py
<folder>. An instancer moving (its node transform blurred, sliding or turning), references moving of their own
(vertex_list_1) under a still instancer, and curves with screen-space radii whose points move."""
import math
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_points_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {')] if 'cases = {' in source else source
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
namespace = {'__file__': str(here / 'make_points_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(folder)]
exec(compile(defs, 'make_points_scenes.py', 'exec'), namespace)
sys.argv = argv
scene, vec3s, mat, translate, P, R = (namespace[k] for k in ('scene', 'vec3s', 'mat', 'translate', 'P', 'R'))


def rotate_y(deg, x=0.0, y=0.0, z=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [x, y, z, 1]]


REF_ENTRY = '{ RdlPointGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }'


def instanced(ref_cls, ref_text, node_xform):
    text = scene(ref_text + '\nRdlInstancerGeometry("/pts") { ["method"]=2, ["references"]={%s("/ref")}, ["xform_list"]={%s,%s,%s}, ["node_xform"]=%s }'
                 % (ref_cls, mat(translate(-1.5, 0, 0)), mat(translate(0, 0.3, -0.5)), mat(translate(1.6, 0, 0.3)), node_xform), motion=True)
    text = text.replace('GeometrySet("/geometry") { RdlPointGeometry("/pts")', 'GeometrySet("/geometry") { RdlInstancerGeometry("/pts")')
    return text.replace(REF_ENTRY, '{ %s("/ref"), "", DwaBaseMaterial("/m"), LightSet("/lights") }, '
                                   '{ RdlInstancerGeometry("/pts"), "", DwaBaseMaterial("/m"), LightSet("/lights") }' % ref_cls)


still = mat(translate(0, 0, 0))
sliding = 'blur(%s, %s)' % (mat(translate(-0.25, 0, 0)), mat(translate(0.25, 0.08, 0)))
turning = 'blur(%s, %s)' % (mat(rotate_y(-12)), mat(rotate_y(12)))
P20, R20 = P[:20], R[:20]
P20b = [(x + 0.2, y + 0.05, z) for x, y, z in P20]
POINTS = 'RdlPointGeometry("/ref") { ["vertex_list_0"]=%s, ["radius_list"]={%s}%s }'
radii = ','.join('%.4g' % r for r in R20)
curves_v, counts = [], []
for i in range(24):
    x, z = -2.0 + (i % 6) * 0.8, -1.0 + (i // 6) * 0.6
    curves_v += [(x, 0.0, z), (x + 0.15, 0.6, z + 0.05), (x + 0.1, 1.2, z - 0.05)]
    counts.append(3)
curves_v1 = [(x + 0.12 * y, y, z) for x, y, z in curves_v]
CV = 'RdlCurveGeometry("%s") { ["curves_vertex_count"]={%s}, ["vertex_list_0"]=%s, ["radius_list"]={%s}, ["curve_type"]=0%s }'
cnt = ','.join(map(str, counts))
cases = {
    'mi-points-sliding': instanced('RdlPointGeometry', POINTS % (vec3s(P20), radii, ''), sliding),
    'mi-points-turning': instanced('RdlPointGeometry', POINTS % (vec3s(P20), radii, ''), turning),
    'mi-points-own': instanced('RdlPointGeometry', POINTS % (vec3s(P20), radii, ', ["vertex_list_1"]=%s, ["motion_blur_type"]=2' % vec3s(P20b)), still),
    'mi-curves-sliding': instanced('RdlCurveGeometry', CV % ('/ref', cnt, vec3s(curves_v), '0.03', ''), sliding),
    'mi-curves-turning': instanced('RdlCurveGeometry', CV % ('/ref', cnt, vec3s(curves_v), '0.03', ''), turning),
    'mi-curves-own': instanced('RdlCurveGeometry', CV % ('/ref', cnt, vec3s(curves_v), '0.03', ', ["vertex_list_1"]=%s, ["motion_blur_type"]=2' % vec3s(curves_v1)), still),
}
ssr = scene(CV % ('/pts', cnt, vec3s(curves_v), '0.004', ', ["use_screen_space_radius"]=true, ["vertex_list_1"]=%s, ["motion_blur_type"]=2' % vec3s(curves_v1)),
            motion=True)
cases['cv-ssr-moving'] = ssr.replace('RdlPointGeometry("/pts")', 'RdlCurveGeometry("/pts")')
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
