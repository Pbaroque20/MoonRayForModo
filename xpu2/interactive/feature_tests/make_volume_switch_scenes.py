"""The kit's volume switches: make_volume_switch_scenes.py <folder>. The emissive scenes' floor, ball and a scattering
volume over the sky and in front of the ball, each with a modo_object_id, and a Cryptomatte output beside the beauty:
rendered with MOONRAY_MODO_FOG_ALPHA (the volume's alpha once) and MOONRAY_MODO_CRYPTO_VOLUMES (the volume's IDs)."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_emissive_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('GLOW = ')]
namespace = {'__file__': str(here / 'make_emissive_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_switch_tmp')]
exec(compile(defs, 'make_emissive_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene = namespace['scene']

FOG = 'BaseVolume("/fog") { ["attenuation_color"]=Rgb(0.9,0.8,0.7), ["attenuation_intensity"]=1.2, ["diffuse_color"]=Rgb(0.8,0.8,0.8) }'
IDS = {'/floor': 1.1e-30, '/ball': 2.3e-31, '/v1': 3.7e-32}


def with_ids(text):
    lines = []
    for line in text.split('\n'):
        for name, value in IDS.items():
            head = 'RdlMeshGeometry("%s") {' % name
            if line.startswith(head):
                line = head + ' ["primitive_attributes"]={UserData("/id%s")},' % name.replace('/', '_') + line[len(head):]
                lines.append('UserData("/id%s") { ["float_key"]="modo_object_id", ["float_values_0"]={%g}, ["rate"]=1 }' % (name.replace('/', '_'), value))
        lines.append(line)
    text = '\n'.join(lines)
    text = text.replace('["russian_roulette_threshold"]=0 }', '["russian_roulette_threshold"]=0, ["deep_id_attribute_names"]={"modo_object_id"} }', 1)
    return text.replace('RenderOutput("/alpha")', 'RenderOutput("/crypto") { ["file_name"]="OUTPUT", ["result"]=13, ["channel_format"]=0, ["compression"]=1, '
                        '["channel_name"]="crypto_object", ["cryptomatte_depth"]=6 }\nRenderOutput("/alpha")', 1)


cases = {
    'vsw-sky': with_ids(scene([('/v1', (-0.6, 1.4, 0.0), 0.8, FOG)])),
    'vsw-front': with_ids(scene([('/v1', (0.9, 0.7, 0.8), 0.6, FOG)])),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
