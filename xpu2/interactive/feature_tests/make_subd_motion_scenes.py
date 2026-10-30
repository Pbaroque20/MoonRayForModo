"""Subdivision surfaces under motion blur: make_subd_motion_scenes.py <folder>. make_subd_scenes.py's cube, moving by
a second vertex list, by velocities, by accelerations (curved, five time steps) and by a turning node transform,
with the motion vectors among the outputs; and the adaptive case again (its adaptive_error now read)."""
import math
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_subd_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {}')]
namespace = {'__file__': str(here / 'make_subd_scenes.py')}
sys_argv = sys.argv
sys.argv = [sys.argv[0], str(here / '_subd_motion_tmp')]
exec(compile(defs, 'make_subd_scenes.py', 'exec'), namespace)
sys.argv = sys_argv
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene, mesh, cube, layer, DWA = namespace['scene'], namespace['mesh'], namespace['cube'], namespace['layer'], namespace['DWA']


def motion_scene(*args, **kw):
    text = scene(*args, **kw)
    text = text.replace('["enable_motion_blur"]=false', '["enable_motion_blur"]=true, ["motion_steps"]={-0.25, 0.25}')
    text = text.replace('RenderOutput("/dsdx")', 'RenderOutput("/motion") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=12, ["channel_format"]=1, '
                        '["compression"]=1, ["channel_name"]="motion" }\nRenderOutput("/dsdx")')
    return text


def v3(vs):
    return '{' + ','.join('Vec3(%g,%g,%g)' % p for p in vs) + '}'


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % x for row in m for x in row)


v, f, uv = cube()
L = layer([('/s', '', 'DwaBaseMaterial("/subd_m")')])
second = [(x + 0.4 * (y - 0.5), y + 0.1, z - 0.2) for x, y, z in v]
vel = [(3 * y, 0.5, -2 * x) for x, y, z in v]
acc = [(-40 * z, 0, 40 * x) for x, y, z in v]
c, s = math.cos(math.radians(20)), math.sin(math.radians(20))
turn = [[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [0.3, 0, 0, 1]]
cases = {
    'subdmb-delta': motion_scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=8, ["vertex_list_1"]=%s' % v3(second)), DWA, L),
    'subdmb-velocity': motion_scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=8, ["velocity_list_0"]=%s, ["motion_blur_type"]=1' % v3(vel)), DWA, L),
    'subdmb-accel': motion_scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=8, ["velocity_list_0"]=%s, ["accleration_list"]=%s, ["motion_blur_type"]=3, '
                                      '["curved_motion_blur_sample_count"]=5' % (v3(vel), v3(acc))), DWA, L),
    'subdmb-xform': motion_scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=8, ["node_xform"]=blur(%s, %s)'
                                      % (mat([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]), mat(turn))), DWA, L),
    'subdmb-adaptive': scene(mesh('/s', v, f, uv, True, ', ["adaptive_error"]=2.0, ["mesh_resolution"]=16'), DWA, L),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
