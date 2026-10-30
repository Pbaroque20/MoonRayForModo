"""Instanced subdivision surfaces and displaced prototypes: make_instance_subd_scenes.py <folder>. The instancer scenes'
cube references made subdivision surfaces (static, turning and moving under motion blur), and polygon and
subdivision references displaced by a noise (MoonRay's shared primitives: tessellated and displaced once in their own
space, the displacement evaluated as if the prototype sat at the origin)."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_instance_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('X = [')]
namespace = {'__file__': str(here / 'make_instance_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_inst_tmp')]
exec(compile(defs, 'make_instance_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene, mat, mul, translate, scale, rot_x, rot_y = (namespace[k] for k in ('scene', 'mat', 'mul', 'translate', 'scale', 'rot_x', 'rot_y'))

X = [translate(-1.4, 0, 0), mul(rot_y(30), translate(-0.4, 0, -0.3)), mul(scale(1.6, 0.6, 1), translate(0.7, 0, 0.2)),
     mul(rot_x(20), translate(1.6, 0.3, -0.6)), translate(0, 0, 1.2)]
XS = '{' + ','.join(mat(m) for m in X) + '}'
CLOSE = '{' + ','.join(mat(mul(mul(rot_y(25), m), translate(0.3, 0.05, 0))) for m in X) + '}'
NOISE = ('NoiseMap_v2("/bumps") { ["space"]=2, ["frequency_multiplier"]=6.0, ["max_level"]=4.5, ["color_A"]=Rgb(0,0,0), ["color_B"]=Rgb(1,1,1) }\n'
         'NormalDisplacement("/dn") { ["height"]=bind(NoiseMap_v2("/bumps"),1.0), ["zero_value"]=0.5, ["height_multiplier"]=0.06 }')


def subd(text, resolution=6):
    return text.replace('["is_subd"]=false, ["smooth_normal"]=true }', '["is_subd"]=true, ["mesh_resolution"]=%d }' % resolution)


def poly(text, resolution=6):
    return text.replace('["is_subd"]=false, ["smooth_normal"]=true }', '["is_subd"]=false, ["smooth_normal"]=true, ["mesh_resolution"]=%d }' % resolution)


def displaced(text):
    text = text.replace('{ RdlMeshGeometry("/ref"), "", DwaBaseMaterial("/m"), LightSet("/lights") }',
                        '{ RdlMeshGeometry("/ref"), "", DwaBaseMaterial("/m"), LightSet("/lights"), NormalDisplacement("/dn") }')
    text = text.replace('{ RdlInstancerGeometry("/inst"), "", DwaBaseMaterial("/m"), LightSet("/lights") }',
                        '{ RdlInstancerGeometry("/inst"), "", DwaBaseMaterial("/m"), LightSet("/lights"), NormalDisplacement("/dn") }')
    return text.replace('EnvLight("/fill")', NOISE + '\nEnvLight("/fill")', 1)


static = scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s }' % XS)
close = scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s, ["xform_list_close"]=%s }'
              % (XS, CLOSE), motion=True)
velocity = scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s, '
                 '["velocities"]={Vec3(6,0,0),Vec3(0,4,0),Vec3(-4,0,3),Vec3(2,2,2),Vec3(0,0,-6)} }' % XS, motion=True)
cases = {
    'isd-static': subd(static),
    'isd-mb-close': subd(close),
    'isd-mb-velocity': subd(velocity),
    'idp-poly': displaced(poly(static)),
    'idp-subd': displaced(subd(static)),
    'idp-poly-mb': displaced(poly(close)),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
