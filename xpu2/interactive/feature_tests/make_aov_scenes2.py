"""More AOV test scenes: make_aov_scenes2.py <folder> <pixel samples>.
aov-more: the sky seen, a subsurface ball, a mirror ball, a glass ball and an emissive card under a labelled key light,
with the LPE aliases (reflection, transmission, emission, caustic), subsurface and labelled events, material AOVs of
subsurface, emission, mirror lobes and labels, the remaining state variables, custom visibility AOVs, and a second
file of named parts in half floats with DWA compression and header metadata (OUTPUT.parts.exr).
aov-adaptive: adaptive sampling's beauty and alpha aux and weight."""
import sys
from pathlib import Path
folder, samples = Path(sys.argv[1]).resolve(), int(sys.argv[2])
folder.mkdir(parents=True, exist_ok=True)
src = (Path(__file__).parent / 'make_light_scenes.py').read_text(encoding='utf-8')
ns = {'samples': samples}
exec(src[src.index('BASE = '):src.index('GEOM = ')], ns)
BASE, sphere = ns['BASE'], ns['sphere']
BASE = BASE.replace('["two_stage_output"]=false }', '["two_stage_output"]=false, ["russian_roulette_threshold"]=0 }')
BASE = BASE.replace('UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }\n', '')
BASE = '\n'.join(l for l in BASE.split('\n') if not l.startswith(('DwaBaseMaterial', 'RdlMeshGeometry("/wall")')))
MATS = '''UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1, ["label"]="floor" }
UsdPreviewSurface("/card_m") { ["diffuseColor"]=Rgb(0.1,0.1,0.1), ["emissiveColor"]=Rgb(2.0,1.0,0.4), ["label"]="card" }
DwaBaseMaterial("/skin_m") { ["albedo"]=Rgb(0.8,0.45,0.35), ["roughness"]=0.45, ["scattering_radius"]=0.25, ["scattering_color"]=Rgb(0.9,0.55,0.45), ["bssrdf"]=1, ["label"]="skin" }
DwaBaseMaterial("/mirror_m") { ["metallic"]=1, ["metallic_color"]=Rgb(0.95,0.9,0.8), ["roughness"]=0, ["label"]="chrome" }
DwaBaseMaterial("/glass_m") { ["transmission"]=1, ["refractive_index"]=1.5, ["roughness"]=0, ["transmission_color"]=Rgb(0.9,1.0,0.95), ["label"]="glass" }
'''
LIGHTS = ('EnvLight("/fill") { ["intensity"]=0.5, ["visible_in_camera"]=1, ["label"]="modo_environment" }\n'
          'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,4.5,1,1), ["width"]=3, ["height"]=2, ["intensity"]=3, ["label"]="key" }\n'
          'LightSet("/lights") { EnvLight("/fill"), RectLight("/key") }\n')
CARD = ('RdlMeshGeometry("/card") { ["vertex_list"]={Vec3(-3.5,0.01,-2),Vec3(-2.0,0.01,-2),Vec3(-2.0,1.5,-2.5),Vec3(-3.5,1.5,-2.5)}, '
        '["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false, ["label"]="cardgeom" }\n')
GEOM = (sphere('/skin', -1.6, 1.0, 0.0, 1.0) + sphere('/mirror', 0.6, 0.8, 0.6, 0.8) + sphere('/glass', 2.4, 0.9, -0.3, 0.9) + CARD)
GEOM = GEOM.replace('RdlMeshGeometry("/skin") {', 'RdlMeshGeometry("/skin") { ["label"]="skingeom",')
LAYER = '''GeometrySet("/geometry") { RdlMeshGeometry("/floor"),RdlMeshGeometry("/skin"),RdlMeshGeometry("/mirror"),RdlMeshGeometry("/glass"),RdlMeshGeometry("/card") }
Layer("/layer") { { RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") },{ RdlMeshGeometry("/skin"), "", DwaBaseMaterial("/skin_m"), LightSet("/lights") },{ RdlMeshGeometry("/mirror"), "", DwaBaseMaterial("/mirror_m"), LightSet("/lights") },{ RdlMeshGeometry("/glass"), "", DwaBaseMaterial("/glass_m"), LightSet("/lights") },{ RdlMeshGeometry("/card"), "", UsdPreviewSurface("/card_m"), LightSet("/lights") } }
SceneVariables { ["layer"]=Layer("/layer") }
'''


def out(name, file='OUTPUT', **attrs):
    def val(v):
        if isinstance(v, bool): return 'true' if v else 'false'
        if isinstance(v, str): return v if v.startswith('Metadata(') else '"%s"' % v
        return str(v)
    a = ', '.join('["%s"]=%s' % (k, val(v)) for k, v in attrs.items())
    base = {'channel_format': 0, 'compression': 1}
    base.update(attrs)
    a = ', '.join('["%s"]=%s' % (k, val(v)) for k, v in base.items())
    return 'RenderOutput("%s") { ["file_name"]="%s", %s }\n' % (name, file, a)


OUTPUTS = ''.join([
    out('/alpha', result=1),
    out('/depth', result=2),
    out('/N', result=3, state_variable=2),
    out('/dPdt', result=3, state_variable=5),
    out('/dSdx', result=3, state_variable=6),
    out('/dSdy', result=3, state_variable=7),
    out('/dTdx', result=3, state_variable=8),
    out('/dTdy', result=3, state_variable=9),
    out('/motion', result=3, state_variable=12),
    out('/St', result=3, state_variable=3),
    out('/ssalbedo', result=7, material_aov='SS.albedo', channel_name='ssalbedo'),
    out('/ssradius', result=7, material_aov='SS.radius', channel_name='ssradius'),
    out('/emission', result=7, material_aov='emission', channel_name='emissionaov'),
    out('/rmcolor', result=7, material_aov='RM.color', channel_name='rmcolor'),
    out('/tmcolor', result=7, material_aov='TM.color', channel_name='tmcolor'),
    out('/skinalbedo', result=7, material_aov="'skin'.albedo", channel_name='skinalbedo'),
    out('/geomlabel', result=7, material_aov="'skingeom'.'skin'.'diffuse'.albedo", channel_name='geomlabel'),
    out('/lobelabel', result=7, material_aov="'specular'.R.color", channel_name='lobelabel'),
    out('/ffactor', result=7, material_aov='fresnel.factor', channel_name='ffactor'),
    out('/rnormal', result=7, material_aov='R.normal', channel_name='rnormal'),
    out('/matP', result=7, material_aov='P', channel_name='matP'),
    out('/reflection', result=8, lpe='reflection', channel_name='reflection'),
    out('/transmission', result=8, lpe='transmission', channel_name='transmission'),
    out('/emissionlpe', result=8, lpe='emission', channel_name='emissionlpe'),
    out('/caustic', result=8, lpe='caustic', channel_name='caustic'),
    out('/sss', result=8, lpe='C<TD>.*L', channel_name='sss'),
    out('/mirrorlpe', result=8, lpe='C<RS>.*[LO]', channel_name='mirrorlpe'),
    out('/glasslpe', result=8, lpe='C<TS>.*[LO]', channel_name='glasslpe'),
    out('/skinspec', result=8, lpe="C<RG'skin.specular'>.*L", channel_name='skinspec'),
    out('/spec', result=8, lpe="C<RG'specular'>.*L", channel_name='spec'),
    out('/cardem', result=8, lpe="C.*<RD><L.'key'>", channel_name='cardem'),
    out('/sky', result=8, lpe="C<L.'modo_environment'>", channel_name='sky'),
    out('/unocc', result=8, lpe="unoccluded;C<RD><L.'key'>", channel_name='unocc'),
    out('/viskey', result=9, visibility_aov="C<RD><L.'key'>", channel_name='viskey'),
    out('/visall', result=9, visibility_aov='C[<RD><TD>]L', channel_name='visall'),
    out('/lmax', result=8, lpe='CDL', math_filter=3, channel_name='lmax'),
    # The second file: two named parts, half floats, DWA compression and metadata.
    out('/pN', file='OUTPUT.parts.exr', result=3, state_variable=2, file_part='geometry', channel_format=1, compression=8,
        exr_dwa_compression_level=60.0, channel_suffix_mode=1, exr_header_attributes='Metadata("/meta")'),
    out('/pZ', file='OUTPUT.parts.exr', result=2, file_part='geometry', channel_format=1, compression=8, exr_dwa_compression_level=60.0),
    out('/pBeauty', file='OUTPUT.parts.exr', result=0, file_part='light', channel_format=1, compression=3),
    out('/pDiffuse', file='OUTPUT.parts.exr', result=8, lpe='diffuse', file_part='light', channel_format=1, compression=3, channel_name='pdiffuse'),
])
META = ('Metadata("/meta") { ["name"]={"comment","frameNumber","exposureValue","worldPos","camMatrix","crop"}, '
        '["type"]={"string","int","float","v3f","m44f","box2i"}, '
        '["value"]={"XPU2 AOV test","12","1.5","1 2 3","1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1","0 0 99 49"} }\n')
text = BASE + MATS + LIGHTS + GEOM + LAYER
text = text.replace('RenderOutput("/beauty") {', META + OUTPUTS + 'RenderOutput("/beauty") {')
(folder / 'aov-more.rdla').write_text(text, encoding='utf-8')

# Adaptive: aux buffers and weight.
ADAPT = ''.join([out('/alpha', result=1), out('/weight', result=11), out('/aux', result=12), out('/aaux', result=14)])
text = BASE.replace('["sampling_mode"]=0', '["sampling_mode"]=2, ["min_adaptive_samples"]=16, ["max_adaptive_samples"]=1024, ["target_adaptive_error"]=10') + MATS + LIGHTS + GEOM + LAYER
text = text.replace('RenderOutput("/beauty") {', ADAPT + 'RenderOutput("/beauty") {')
(folder / 'aov-adaptive.rdla').write_text(text, encoding='utf-8')
print('aov-more aov-adaptive')
