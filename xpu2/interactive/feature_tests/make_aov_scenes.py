"""AOV test scenes: make_aov_scenes.py <folder> <pixel samples>. Every output into one EXR (OUTPUT), as the kit writes
its AOVs: the beauty, alpha, depth, state variables, wireframe, material AOVs, the kit's light path expressions and a
visibility AOV, the weight and aux buffers, a primitive attribute, and the math filters."""
import sys
from pathlib import Path
folder, samples = Path(sys.argv[1]).resolve(), int(sys.argv[2])
folder.mkdir(parents=True, exist_ok=True)
src = (Path(__file__).parent / 'make_light_scenes.py').read_text(encoding='utf-8')
ns = {'samples': samples}
exec(src[src.index('BASE = '):src.index('FILL = ')], ns)
BASE, GEOM, LAYER = ns['BASE'], ns['GEOM'], ns['LAYER']
BASE = BASE.replace('["two_stage_output"]=false }', '["two_stage_output"]=false, ["russian_roulette_threshold"]=0 }')
LIGHTS = ('EnvLight("/fill") { ["intensity"]=0.3, ["visible_in_camera"]=1, ["label"]="modo_environment" }\n'
          'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,4.5,1,1), ["width"]=3, ["height"]=2, ["intensity"]=3, ["label"]="key" }\n')
NAMES = 'EnvLight("/fill"), RectLight("/key")'


def out(name, **attrs):
    def val(v):
        if isinstance(v, bool): return 'true' if v else 'false'
        if isinstance(v, str): return '"%s"' % v
        return str(v)
    a = ', '.join('["%s"]=%s' % (k, val(v)) for k, v in attrs.items())
    return 'RenderOutput("%s") { ["file_name"]="OUTPUT", ["channel_format"]=0, ["compression"]=1, %s }\n' % (name, a)


OUTPUTS = ''.join([
    out('/alpha', result=1),
    out('/depth', result=2),
    out('/N', result=3, state_variable=2),
    out('/Ng', result=3, state_variable=1),
    out('/P', result=3, state_variable=0),
    out('/St', result=3, state_variable=3),
    out('/Wp', result=3, state_variable=10),
    out('/dPds', result=3, state_variable=4),
    out('/wire', result=6),
    out('/albedo', result=7, material_aov='albedo'),
    out('/dcolor', result=7, material_aov='D.color', channel_name='dcolor'),
    out('/mnormal', result=7, material_aov='normal', channel_name='mnormal'),
    out('/rough', result=7, material_aov='R.roughness', channel_name='rough'),
    out('/matte', result=7, material_aov='matte', channel_name='matte'),
    out('/validity', result=7, material_aov='pbr_validity', channel_name='validity'),
    out('/fcolor', result=7, material_aov='fresnel.color', channel_name='fcolor'),
    out('/spec', result=7, material_aov="'specular'.albedo", channel_name='specAlbedo'),
    out('/diffuse', result=8, lpe='diffuse', channel_name='diffuse'),
    out('/idiffuse', result=8, lpe='C<RD>[DSG]+[<L.>O]', channel_name='idiffuse'),
    out('/glossy', result=8, lpe='glossy', channel_name='glossy'),
    out('/iglossy', result=8, lpe='C<RG>[DSG]+[<L.>O]', channel_name='iglossy'),
    out('/reflection', result=8, lpe='reflection', channel_name='reflection'),
    out('/unshadowed', result=8, lpe='unoccluded;CD[<L.>O]', channel_name='unshadowed'),
    out('/envlight', result=8, lpe="C.+<L.'modo_environment'>", channel_name='envlight'),
    out('/envbg', result=8, lpe="C<L.'modo_environment'>", channel_name='envbg'),
    out('/keylight', result=8, lpe="C.*<L.'key'>", channel_name='keylight'),
    out('/speclpe', result=8, lpe="C<RS'specular'>.*L", channel_name='speclpe'),
    out('/vis', result=9, channel_name='vis'),
    out('/weight', result=11),
    out('/heat', result=5),
    out('/aux', result=12),
    out('/aaux', result=14),
    out('/myattr', result=4, primitive_attribute='myattr', primitive_attribute_type=0),
    out('/depthmin', result=2, math_filter=2, channel_name='Zmin'),
    out('/depthmax', result=2, math_filter=3, channel_name='Zmax'),
    out('/Nclosest', result=3, state_variable=2, math_filter=5, channel_name='Nclosest'),
    out('/depthsum', result=2, math_filter=1, channel_name='Zsum'),
])
# A float primitive attribute on the floor (per vertex).
GEOM_ATTR = ('UserData("/myattr_data") { ["float_key"]="myattr", ["float_values_0"]={0.0, 1.0, 2.0, 3.0} }\n')
cases = {'aov-all': ''}
for name in cases:
    text = BASE + LIGHTS + 'LightSet("/lights") { %s }\n' % NAMES + GEOM + LAYER
    text = text.replace('RenderOutput("/beauty") {', OUTPUTS + 'RenderOutput("/beauty") {')
    text = text.replace('RdlMeshGeometry("/floor") {', GEOM_ATTR + 'RdlMeshGeometry("/floor") { ["primitive_attributes"]={UserData("/myattr_data")},')
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(' '.join(cases))
