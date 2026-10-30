"""Cookie v1 light filters (a map shader projected): make_cookie1_scenes.py <folder>. The light filter scenes' spot
with a CookieLightFilter whose texture_map is a checkerboard (blurred), an image, a world-space noise (MoonRay reads it
at the render origin) and none (white)."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_filter_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {')]
folder = Path(sys.argv[1]).resolve()
namespace = {'__file__': str(here / 'make_filter_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(folder)]
exec(compile(defs, 'make_filter_scenes.py', 'exec'), namespace)
sys.argv = argv
folder.mkdir(parents=True, exist_ok=True)
scene, mat, SPOT, TEX = namespace['scene'], namespace['mat'], namespace['SPOT'], namespace['TEX']


def cookie(texture_map, maps, extra=''):
    return scene('%s\nCookieLightFilter("/f") { ["node_xform"]=%s%s, ["projector_focal"]=25, ["projector_film_width_aperture"]=24, '
                 '["outside_projection"]=1, ["density"]=0.9%s }' % (maps, mat(SPOT), ', ["texture_map"]=%s' % texture_map if texture_map else '', extra),
                 'CookieLightFilter("/f")')


BLUR = ', ["blur_near_distance"]=2, ["blur_near_value"]=0.0, ["blur_far_distance"]=6, ["blur_far_value"]=0.05, ["blur_midpoint"]=4, ["blur_mid_value"]=0.02'
cases = {
    'lf1-checker': cookie('CheckerboardMap("/cc")', 'CheckerboardMap("/cc") { ["num_u_tiles"]=6, ["num_v_tiles"]=6, ["color_A"]=Rgb(1,1,1), ["color_B"]=Rgb(0.05,0.1,0.3) }', BLUR),
    'lf1-image': cookie('ImageMap("/im")', 'ImageMap("/im") { ["texture"]="%s" }' % TEX),
    'lf1-noise': cookie('NoiseMap_v2("/nm")', 'NoiseMap_v2("/nm") { ["space"]=2, ["frequency_multiplier"]=3.0, ["color_A"]=Rgb(0.2,0.2,0.2), ["color_B"]=Rgb(1,0.8,0.5) }'),
    'lf1-none': cookie(None, '', ', ["invert"]=true'),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')

# A combine within a combine (the vector filters' LightFilter_eval through a function pointer).
translate = namespace['translate']
nested = scene('DecayLightFilter("/a") { ["falloff_far"]=true, ["far_start"]=3.5, ["far_end"]=6.0 }\n'
               'ColorRampLightFilter("/b") { ["begin_distance"]=2.0, ["end_distance"]=6.0, ["distances"]={0,1}, ["colors"]={Rgb(1,0.9,0.5),Rgb(0.2,0.2,1)}, ["interpolation_types"]={1,1} }\n'
               'CombineLightFilter("/inner") { ["light_filters"]={DecayLightFilter("/a"), ColorRampLightFilter("/b")}, ["mode"]=2 }\n'
               'RodLightFilter("/r") { ["node_xform"]=%s, ["width"]=0.8, ["height"]=1.6, ["depth"]=0.8, ["radius"]=0.2, ["edge"]=0.5, ["color"]=Rgb(0,0,0) }\n'
               'CombineLightFilter("/f") { ["light_filters"]={CombineLightFilter("/inner"), RodLightFilter("/r")}, ["mode"]=0 }' % mat(translate(0.6, 1, 0.4)),
               'CombineLightFilter("/f")')
(folder / 'lf-combine-nested.rdla').write_text(nested, encoding='utf-8')
print('nested')
