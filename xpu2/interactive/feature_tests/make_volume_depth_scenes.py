"""State AOVs through volumes: make_volume_depth_scenes.py <folder>. The emissive scenes' floor and ball with a fog
sphere half over the horizon (camera rays through it hit the floor or nothing), depth, P and Wp outputs; the fog's
surface opacity threshold at its default and low, and two overlapping fogs of different thresholds."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_emissive_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('GLOW = ')]
folder = Path(sys.argv[1]).resolve()
namespace = {'__file__': str(here / 'make_emissive_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(folder)]
exec(compile(defs, 'make_emissive_scenes.py', 'exec'), namespace)
sys.argv = argv
scene = namespace['scene']


def fog(name, density, threshold=None, color='0.9,0.85,0.8'):
    extra = ', ["surface_opacity_threshold"]=%g' % threshold if threshold is not None else ''
    return ('BaseVolume("%s") { ["attenuation_color"]=Rgb(1,1,1), ["attenuation_intensity"]=%g, ["diffuse_color"]=Rgb(%s)%s }'
            % (name, density, color, extra))


OUTPUTS = '\n'.join([
    'RenderOutput("/depth") { ["file_name"]="OUTPUT", ["result"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Z" }',
    'RenderOutput("/P") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=0, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="P" }',
    'RenderOutput("/Wp") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=10, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Wp" }',
])


def depth_scene(volumes, sv=''):
    text = scene(volumes)
    if sv:
        text = text.replace('["russian_roulette_threshold"]=0 }', '["russian_roulette_threshold"]=0%s }' % sv, 1)
    return text.replace('RenderOutput("/beauty") {', OUTPUTS + '\nRenderOutput("/beauty") {', 1)


cases = {
    'vd-fog': depth_scene([('/v1', (-0.4, 1.3, -0.5), 0.9, fog('/f1', 1.5))]),
    'vd-fog-low': depth_scene([('/v1', (-0.4, 1.3, -0.5), 0.9, fog('/f1', 1.5, 0.1))]),
    'vd-two-max': depth_scene([('/v1', (-0.6, 1.3, -0.5), 0.8, fog('/f1', 1.2, 0.2)), ('/v2', (0.2, 1.4, -0.6), 0.7, fog('/f2', 3.0, 0.7, '0.5,0.7,0.9'))],
                              ', ["volume_overlap_mode"]=1'),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
