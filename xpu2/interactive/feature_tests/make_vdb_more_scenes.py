"""More VDB scenes: make_vdb_more_scenes.py <folder> <vdb folder> <velocity vdb>. The VDB scenes' fog sphere with its
VdbVolume's opacity gain, colour and anisotropy bound to noise maps (the gain baked at the density's resolution and by
divisions), its incandescence bound (lighting the floor), its velocity grid under motion blur (and decimated), and the
geometry moving."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_vdb_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {')]
folder = Path(sys.argv[1]).resolve()
namespace = {'__file__': str(here / 'make_vdb_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(folder), sys.argv[2]]
exec(compile(defs, 'make_vdb_scenes.py', 'exec'), namespace)
sys.argv = argv
velocity_vdb = Path(sys.argv[3]).resolve().as_posix()
scene, geometry, mat, translate = namespace['scene'], namespace['geometry'], namespace['mat'], namespace['translate']

NOISE = 'NoiseMap_v2("/n") { ["space"]=2, ["frequency_multiplier"]=3.0, ["max_level"]=4.0, ["color_A"]=Rgb(0.1,0.1,0.1), ["color_B"]=Rgb(1,1,1) }'
CNOISE = 'NoiseMap_v2("/cn") { ["space"]=2, ["frequency_multiplier"]=2.0, ["color_A"]=Rgb(0.9,0.3,0.1), ["color_B"]=Rgb(0.2,0.5,1) }'


def vol(attrs, maps=(NOISE,)):
    base = {'opacity_gain_mult': 'Rgb(3,3,3)', 'color_mult': 'Rgb(0.85,0.8,0.75)', 'incandescence_gain_mult': 'Rgb(0,0,0)', 'anisotropy': '0.3'}
    base.update(attrs)
    return 'VdbVolume("/vol") { %s }\n%s' % (', '.join('["%s"]=%s' % kv for kv in base.items()), '\n'.join(maps))


MOTION = ', ["enable_motion_blur"]=true, ["motion_steps"]={-0.5, 0.5}'


def motion(text):
    text = text.replace('["enable_motion_blur"]=false, ', '', 1).replace('["russian_roulette_threshold"]=0', '["russian_roulette_threshold"]=0' + MOTION, 1)
    return text.replace('["near"]=0.01, ["far"]=1000.0 }', '["near"]=0.01, ["far"]=1000.0, ["mb_shutter_open"]=-0.5, ["mb_shutter_close"]=0.5 }', 1)


cases = {
    'vdbm-gain': scene(geometry('sphere.vdb'), vol({'opacity_gain_mult': 'bind(NoiseMap_v2("/n"),Rgb(3,3,3))'})),
    'vdbm-gain-div': scene(geometry('sphere.vdb'), vol({'opacity_gain_mult': 'bind(NoiseMap_v2("/n"),Rgb(3,3,3))', 'bake_resolution_mode': '1', 'bake_divisions': '20'})),
    'vdbm-color': scene(geometry('sphere.vdb'), vol({'color_mult': 'bind(NoiseMap_v2("/cn"),Rgb(1,1,1))'}, (CNOISE,))),
    'vdbm-aniso': scene(geometry('sphere.vdb'), vol({'anisotropy': 'bind(NoiseMap_v2("/n"),0.8)'})),
    'vdbm-incand': scene(geometry('sphere.vdb', emission='Cd'), vol({'opacity_gain_mult': 'Rgb(2,2,2)', 'color_mult': 'Rgb(0.6,0.6,0.6)',
                                                                    'incandescence_gain_mult': 'bind(NoiseMap_v2("/cn"),Rgb(6,3,1))', 'anisotropy': '0.0'}, (CNOISE,))),
}
vel = geometry('sphere.vdb').replace('["model"]="%s"' % (namespace['vdb'] / 'sphere.vdb').as_posix(),
                                      '["model"]="%s", ["velocity_grid"]="vel", ["velocity_scale"]=1.0' % velocity_vdb)
cases['vdb-velocity'] = motion(scene(vel, vol({})))
cases['vdb-velocity-rate'] = motion(scene(vel.replace('["velocity_scale"]=1.0', '["velocity_scale"]=1.0, ["velocity_sample_rate"]=0.5'), vol({})))
moving = geometry('sphere.vdb').replace('["node_xform"]=%s' % mat(translate(0, 1.1, 0)),
                                        '["node_xform"]=blur(%s, %s)' % (mat(translate(-0.4, 1.1, 0)), mat(translate(0.5, 1.2, 0))))
cases['vdb-moving'] = motion(scene(moving, vol({})))
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
