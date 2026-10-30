"""Heterogeneous BaseVolumes (bound attributes): make_mapped_volume_scenes.py <folder>. The emissive scenes' sphere
volume over a floor beside a ball, its attenuation colour, intensity, diffuse colour, emission and anisotropy bound to
noise maps; baked at the default, by divisions and by voxel size; on a subdivision sphere (its extinction maps at the
render origin); match_diffuse with a mapped diffuse colour."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_emissive_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('GLOW = ')]
namespace = {'__file__': str(here / 'make_emissive_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_mapped_tmp')]
exec(compile(defs, 'make_emissive_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene = namespace['scene']

NOISE = ('NoiseMap_v2("/n") { ["space"]=2, ["frequency_multiplier"]=2.5, ["max_level"]=4.0, ["color_A"]=Rgb(0.05,0.05,0.05), '
         '["color_B"]=Rgb(1,1,1) }')
CNOISE = ('NoiseMap_v2("/cn") { ["space"]=2, ["frequency_multiplier"]=1.5, ["max_level"]=3.0, ["color_A"]=Rgb(0.9,0.2,0.1), '
          '["color_B"]=Rgb(0.1,0.4,0.9) }')


def vol(attrs, maps=(NOISE,)):
    # The shader line first (scene() takes the name from it), the maps after it.
    return 'BaseVolume("/v") { %s }\n%s' % (attrs, '\n'.join(maps))


BASE = '["attenuation_color"]=Rgb(1,1,1), ["attenuation_intensity"]=2.0, ["diffuse_color"]=Rgb(0.8,0.8,0.8)'
cases = {
    'hv-density': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol('["attenuation_color"]=bind(NoiseMap_v2("/n"),Rgb(1,1,1)), ["attenuation_intensity"]=3.0, '
                                                          '["diffuse_color"]=Rgb(0.8,0.8,0.8)'))]),
    'hv-intensity-div': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol('["attenuation_intensity"]=bind(NoiseMap_v2("/n"),3.0), ["bake_resolution_mode"]=1, '
                                                                '["bake_divisions"]=40, ["diffuse_color"]=Rgb(0.8,0.8,0.8)'))]),
    'hv-voxel-size': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol('["attenuation_factor"]=bind(NoiseMap_v2("/n"),1.0), ["attenuation_intensity"]=3.0, '
                                                             '["bake_resolution_mode"]=2, ["bake_voxel_size"]=0.05, ["diffuse_color"]=Rgb(0.8,0.8,0.8)'))]),
    'hv-albedo': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol(BASE.replace('["diffuse_color"]=Rgb(0.8,0.8,0.8)', '["diffuse_color"]=bind(NoiseMap_v2("/cn"),Rgb(1,1,1))'),
                                                         (CNOISE,)))]),
    'hv-emission': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol('["attenuation_intensity"]=0.5, ["diffuse_color"]=Rgb(0.8,0.8,0.8), '
                                                           '["emission_color"]=bind(NoiseMap_v2("/cn"),Rgb(1,1,1)), ["emission_intensity"]=4.0', (CNOISE,)))]),
    'hv-anisotropy': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol(BASE + ', ["anisotropy"]=bind(NoiseMap_v2("/n"),0.8)'))]),
    'hv-match': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, vol('["match_diffuse"]=true, ["attenuation_intensity"]=2.0, '
                                                        '["diffuse_color"]=bind(NoiseMap_v2("/cn"),Rgb(1,1,1))', (CNOISE,)))]),
}
cases['hv-density-subd'] = cases['hv-density'].replace('RdlMeshGeometry("/v1") {', 'RdlMeshGeometry("/v1") { ["mesh_resolution"]=2,', 1)
cases['hv-density-subd'] = cases['hv-density-subd'].replace('["is_subd"]=false, ["smooth_normal"]=true }\nBaseVolume', '["is_subd"]=true }\nBaseVolume', 1)
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
