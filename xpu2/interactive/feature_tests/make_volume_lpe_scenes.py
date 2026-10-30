"""Light path expressions through volumes: make_volume_lpe_scenes.py <folder>. The emissive scenes' floor and ball with
a key light, a labelled fog and a labelled glow, and light AOVs for a camera ray's volume emission, single scattering
by light and by the glow, and the multiple scattering's chains (max volume depth 3)."""
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

FOG = ('BaseVolume("/fog") { ["attenuation_color"]=Rgb(1,1,1), ["attenuation_intensity"]=0.8, ["diffuse_color"]=Rgb(0.9,0.85,0.8), '
       '["anisotropy"]=0.2, ["label"]="fog" }')
GLOW = ('BaseVolume("/glow") { ["emission_color"]=Rgb(1.0,0.55,0.2), ["emission_intensity"]=4.0, ["attenuation_color"]=Rgb(1,1,1), '
        '["attenuation_intensity"]=0.5, ["diffuse_color"]=Rgb(0.8,0.8,0.8), ["label"]="glow" }')
KEY = 'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0.5,3.5,1,1), ["width"]=2, ["height"]=2, ["intensity"]=2, ["label"]="key" }'


def out(name, lpe):
    return 'RenderOutput("%s") { ["file_name"]="OUTPUT", ["result"]=8, ["lpe"]="%s", ["channel_name"]="%s", ["channel_format"]=1, ["compression"]=1 }' % (
        name, lpe, name.strip('/'))


OUTPUTS = '\n'.join([
    out('/vemit', "C<O.'glow'>"),
    out('/vkey', "CV<L.'key'>"),
    out('/vlight', 'CVL'),
    out('/vglowlit', "CV<O.'glow'>"),
    out('/vmulti', 'CVV+L'),
    out('/vmultiglow', "CVV+<O.'glow'>"),
    out('/vany', 'C.*V.*'),
    out('/surface', 'C[DG].*'),
])


def lpe_scene(volumes):
    text = scene(volumes)
    text = text.replace('["russian_roulette_threshold"]=0 }', '["russian_roulette_threshold"]=0, ["max_volume_depth"]=3 }', 1)
    text = text.replace('EnvLight("/fill") { ["intensity"]=0.05 }', 'EnvLight("/fill") { ["intensity"]=0.05 }\n' + KEY)
    text = text.replace('LightSet("/lights") { EnvLight("/fill") }', 'LightSet("/lights") { EnvLight("/fill"), RectLight("/key") }')
    return text.replace('RenderOutput("/beauty") {', OUTPUTS + '\nRenderOutput("/beauty") {', 1)


cases = {
    'vlpe-fog': lpe_scene([('/v1', (-0.4, 0.8, 0.0), 0.7, FOG)]),
    'vlpe-glow': lpe_scene([('/v1', (-0.6, 0.8, 0.0), 0.6, GLOW), ('/v2', (0.3, 0.8, -0.3), 0.55, FOG)]),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
