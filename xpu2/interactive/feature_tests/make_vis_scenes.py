"""Visibility test scenes: make_vis_scenes.py <folder> <pixel samples>."""
import sys
from pathlib import Path
folder, samples = Path(sys.argv[1]).resolve(), int(sys.argv[2])
folder.mkdir(parents=True, exist_ok=True)
src = (Path(__file__).parent / 'make_light_scenes.py').read_text(encoding='utf-8')
ns = {'samples': samples}
exec(src[src.index('BASE = '):src.index('FILL = ')], ns)
BASE, GEOM, LAYER = ns['BASE'], ns['GEOM'], ns['LAYER']
FILL = 'EnvLight("/fill") { ["intensity"]=0.1, ["visible_in_camera"]=1 }\n'
KEY = 'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,4.5,1,1), ["width"]=3, ["height"]=2, ["intensity"]=3%s }\n'
SPOT = 'SpotLight("/spot") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 2,5,0.5,1), ["lens_radius"]=0.4, ["outer_cone_angle"]=50, ["inner_cone_angle"]=30, ["intensity"]=30%s }\n'
def geom(g, name, attrs):
    return g.replace('RdlMeshGeometry("%s") {' % name, 'RdlMeshGeometry("%s") { %s,' % (name, attrs))
cases = {
    'light-vis': (FILL + KEY % ', ["visible_mirror_reflection"]=false, ["visible_diffuse_reflection"]=false' + SPOT % ', ["visible_glossy_reflection"]=false', GEOM),
    'geo-vis': (FILL + KEY % '' + SPOT % '', geom(geom(geom(GEOM, '/ball', '["visible_in_camera"]=false'), '/mirror', '["visible_shadow"]=false'), '/wall', '["visible_mirror_reflection"]=false, ["visible_diffuse_reflection"]=false')),
    'single-sided': (FILL + KEY % '' + SPOT % '', geom(geom(GEOM, '/wall', '["side_type"]=1, ["reverse_normals"]=true'), '/ball', '["side_type"]=1')),
    'reversed': (FILL + KEY % '' + SPOT % '', geom(GEOM, '/ball', '["reverse_normals"]=true')),
}
for name, (lights, g) in cases.items():
    names = [l.split('(')[0] + '("' + l.split('"')[1] + '")' for l in lights.strip().split('\n')]
    text = BASE + lights + 'LightSet("/lights") { %s }\n' % ', '.join(names) + g + LAYER
    if name == 'geo-vis':
        text = geom(text, '/wall', '["visible_mirror_reflection"]=false, ["visible_diffuse_reflection"]=false')
    if name == 'single-sided':
        text = geom(text, '/wall', '["side_type"]=1, ["reverse_normals"]=true')
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(' '.join(cases))
