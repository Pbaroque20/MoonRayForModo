"""Volume cutouts (holdouts): make_cutout_scenes.py <folder>. The emissive scenes' sphere volume over a floor beside a
ball, as a CutoutVolume of a scattering BaseVolume (with a ramp it then ignores), in front of the ball and over the sky,
beside an ordinary volume (SUM, MAX, RND), and a cutout of no volume."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_emissive_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('GLOW = ')]
namespace = {'__file__': str(here / 'make_emissive_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_cutout_tmp')]
exec(compile(defs, 'make_emissive_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene = namespace['scene']

INNER = ('BaseVolume("/inner") { ["attenuation_color"]=Rgb(1,1,1), ["attenuation_intensity"]=1.5, ["diffuse_color"]=Rgb(0.8,0.8,0.8), '
         '["use_attenuation_ramp"]=true, ["attenuation_colors"]={Rgb(1,0,0),Rgb(0,0,1)}, ["attenuation_distances"]={0,1}, ["attenuation_interpolations"]={1,1} }')
FOG = 'BaseVolume("/fog") { ["attenuation_color"]=Rgb(0.9,0.8,0.7), ["attenuation_intensity"]=1.0, ["diffuse_color"]=Rgb(0.7,0.7,0.7) }'


def cut(name, inner='BaseVolume("/inner")'):
    return 'CutoutVolume("%s") { ["indirect_volume"]=%s }' % (name, inner)


cases = {
    'cut-front': scene([('/v1', (0.9, 0.7, 0.8), 0.6, cut('/c1') + '\n' + INNER)]),
    'cut-sky': scene([('/v1', (-0.6, 1.4, 0.0), 0.7, cut('/c1') + '\n' + INNER)]),
    'cut-none': scene([('/v1', (0.9, 0.7, 0.8), 0.6, 'CutoutVolume("/c1") { }')]),
    'cut-beside-sum': scene([('/v1', (0.6, 0.8, 0.6), 0.6, cut('/c1') + '\n' + INNER), ('/v2', (0.1, 0.8, 0.3), 0.6, FOG)]),
}
for mode, name in ((1, 'max'), (2, 'rnd')):
    cases['cut-beside-' + name] = cases['cut-beside-sum'].replace('["russian_roulette_threshold"]=0', '["russian_roulette_threshold"]=0, ["volume_overlap_mode"]=%d' % mode)
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
