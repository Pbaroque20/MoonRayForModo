"""Presence test scenes: make_presence_scenes.py <folder> <pixel samples>. Beauty and alpha outputs."""
import sys
from pathlib import Path
folder, samples = Path(sys.argv[1]).resolve(), int(sys.argv[2])
folder.mkdir(parents=True, exist_ok=True)
src = (Path(__file__).parent / 'make_light_scenes.py').read_text(encoding='utf-8')
ns = {'samples': samples}
exec(src[src.index('BASE = '):src.index('FILL = ')], ns)
BASE, GEOM, LAYER = ns['BASE'], ns['GEOM'], ns['LAYER']
LIGHTS = ('EnvLight("/fill") { ["intensity"]=0.3, ["visible_in_camera"]=1 }\n'
          'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,4.5,1,1), ["width"]=3, ["height"]=2, ["intensity"]=3 }\n')
NAMES = 'EnvLight("/fill"), RectLight("/key")'
cases = {
    # The ball half present, the mirror's presence from a checker.
    'presence-partial': ('DwaBaseMaterial("/ball_m") {', 'DwaBaseMaterial("/ball_m") { ["presence"]=0.5,', ''),
    'presence-map': ('DwaBaseMaterial("/mirror_m") {', 'CheckerboardMap("/pchecker") { ["u_tiles"]=6, ["v_tiles"]=4 }\nDwaBaseMaterial("/mirror_m") { ["presence"]=bind(CheckerboardMap("/pchecker"),1.0),', ''),
    # A UsdPreviewSurface cut out by its opacity, a quarter present by DwaBase on the wall.
    'presence-usd': ('UsdPreviewSurface("/floor_m") {', 'UsdPreviewSurface("/floor_m") {', 'opacity'),
}
for name, (old, new, extra) in cases.items():
    text = BASE + LIGHTS + 'LightSet("/lights") { %s }\n' % NAMES + GEOM + LAYER
    text = text.replace(old, new)
    if extra == 'opacity':
        text = text.replace('UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
                            'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }\n'
                            'UsdPreviewSurface("/wall_m") { ["diffuseColor"]=Rgb(0.6,0.5,0.4), ["opacity"]=0.2, ["opacityThreshold"]=0.5 }')
        text = text.replace('{ RdlMeshGeometry("/wall"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") }',
                            '{ RdlMeshGeometry("/wall"), "", UsdPreviewSurface("/wall_m"), LightSet("/lights") }')
    text = text.replace('RenderOutput("/beauty") {', 'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=0, ["compression"]=1 }\nRenderOutput("/beauty") {')
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(' '.join(cases))
