"""Light filter test scenes: make_filter_scenes.py <folder>. A textured cube on a floor lit by a spot light (and a fill)
with each of MoonRay's light filters the kit writes: intensity (and its light path selection), decay, colour ramp
(radial, directional), rod (and inverted), barn door (on the light's transform, and its own, physical), cookie v2
(a texture, blurred), a combine, a light filter set on one assignment, and a moving rod under motion blur."""
import math
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
TEX = (folder.parent / 'lt' / 'tex.tx').as_posix()


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % v for row in m for v in row)


def translate(x, y, z):
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [x, y, z, 1]]


def scale(s):
    return [[s, 0, 0, 0], [0, s, 0, 0], [0, 0, s, 0], [0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0, 0], [0, c, s, 0], [0, -s, c, 0], [0, 0, 0, 1]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [0, 0, 0, 1]]


CAM = mul(rot_x(-14), translate(0, 2.2, 6.0))
# The spot points down -Z of its node transform; turned to look at the cube from above and in front.
SPOT = mul(rot_x(-65), translate(0, 4.2, 2.2))


def cube():
    s = 0.5
    v = [(x * s, y * s + 1, z * s) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    uv = []
    for fi, f in enumerate(faces):
        u0, v0 = (fi % 3) / 3.0, (fi // 3) / 2.0
        uv += [(u0 + 0.02, v0 + 0.02), (u0 + 0.31, v0 + 0.02), (u0 + 0.31, v0 + 0.48), (u0 + 0.02, v0 + 0.48)]
    return ('RdlMeshGeometry("/s") { ["vertex_list_0"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["uv_list"]={%s}, '
            '["is_subd"]=false, ["smooth_normal"]=false }' % (
                ','.join('Vec3(%g,%g,%g)' % p for p in v), ','.join(str(len(f)) for f in faces),
                ','.join(str(i) for f in faces for i in f), ','.join('Vec2(%g,%g)' % p for p in uv)))


def scene(filters, names, light=None, set_entry='', sv_extra='', spot_xform=None, extra_lights=''):
    light = light or ('SpotLight("/key") { ["node_xform"]=%s, ["intensity"]=60, ["outer_cone_angle"]=70, ["inner_cone_angle"]=40, '
                      '["lens_radius"]=0.3, ["light_filters"]={%s} }' % (spot_xform or mat(SPOT), names))
    return '\n'.join([
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0%s }' % sv_extra,
        'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % mat(CAM),
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        cube(),
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'CheckerboardMap("/checker") { ["num_u_tiles"]=12, ["num_v_tiles"]=12, ["color_A"]=Rgb(0.9,0.85,0.8), ["color_B"]=Rgb(0.15,0.2,0.5) }',
        'DwaBaseMaterial("/m") { ["albedo"]=bind(CheckerboardMap("/checker"), Rgb(1,1,1)), ["roughness"]=0.3, ["specular"]=1.0 }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        filters,
        light,
        extra_lights,
        'EnvLight("/fill") { ["intensity"]=0.15 }',
        'LightSet("/lights") { SpotLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlMeshGeometry("/s"), RdlMeshGeometry("/floor") }',
        'Layer("/layer") { { RdlMeshGeometry("/s"), "", DwaBaseMaterial("/m"), LightSet("/lights")%s }, '
        '{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }' % set_entry,
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


cases = {
    'lf-intensity': scene('IntensityLightFilter("/f") { ["color"]=Rgb(1,0.5,0.25), ["intensity"]=2, ["exposure"]=-0.5 }', 'IntensityLightFilter("/f")'),
    'lf-intensity-paths': scene('IntensityLightFilter("/f") { ["color"]=Rgb(0.2,1,0.2), ["intensity"]=4, ["light_path_selection"]=3 }', 'IntensityLightFilter("/f")'),
    'lf-intensity-invert': scene('IntensityLightFilter("/f") { ["color"]=Rgb(2,1,0.5), ["invert"]=true }', 'IntensityLightFilter("/f")'),
    'lf-decay': scene('DecayLightFilter("/f") { ["falloff_near"]=true, ["falloff_far"]=true, ["near_start"]=2.5, ["near_end"]=3.5, ["far_start"]=4.2, ["far_end"]=6.0 }',
                      'DecayLightFilter("/f")'),
    'lf-ramp-radial': scene('ColorRampLightFilter("/f") { ["begin_distance"]=2.5, ["end_distance"]=6.0, ["distances"]={0,0.5,1}, '
                            '["colors"]={Rgb(1,1,1),Rgb(1,0.3,0.1),Rgb(0,0,0.2)}, ["interpolation_types"]={1,4,1}, ["density"]=0.9 }', 'ColorRampLightFilter("/f")'),
    'lf-ramp-dir': scene('ColorRampLightFilter("/f") { ["node_xform"]=%s, ["use_xform"]=true, ["mode"]=1, ["wrap_mode"]=1, ["begin_distance"]=-1.0, '
                         '["end_distance"]=1.5, ["distances"]={0,1}, ["colors"]={Rgb(1,1,1),Rgb(0.1,0.2,1)}, ["interpolation_types"]={6,6}, ["intensity"]=1.3 }'
                         % mat(mul(rot_x(-90), translate(0, 1.2, 0))), 'ColorRampLightFilter("/f")'),
    'lf-rod': scene('RodLightFilter("/f") { ["node_xform"]=%s, ["width"]=0.8, ["height"]=1.6, ["depth"]=0.8, ["radius"]=0.2, ["edge"]=0.5, ["color"]=Rgb(0,0,0) }'
                    % mat(translate(0.6, 1, 0.4)), 'RodLightFilter("/f")'),
    'lf-rod-invert': scene('RodLightFilter("/f") { ["node_xform"]=%s, ["width"]=1.5, ["height"]=2.0, ["depth"]=1.5, ["radius"]=0.1, ["edge"]=0.6, '
                           '["color"]=Rgb(0.2,0.4,1), ["intensity"]=0.5, ["invert"]=true, ["density"]=0.8 }' % mat(mul(rot_y(30), translate(0, 1, 0))), 'RodLightFilter("/f")'),
    'lf-barn': scene('BarnDoorLightFilter("/f") { ["use_light_xform"]=true, ["projector_width"]=1.0, ["projector_height"]=0.6, ["size_left"]=0.2, '
                     '["size_top"]=-0.1, ["radius"]=0.3, ["edge"]=0.2, ["edge_scale_right"]=2, ["rotation"]=20 }', 'BarnDoorLightFilter("/f")'),
    'lf-barn-physical': scene('BarnDoorLightFilter("/f") { ["node_xform"]=%s, ["use_light_xform"]=false, ["mode"]=1, ["projector_width"]=0.9, '
                              '["projector_height"]=0.9, ["projector_focal_distance"]=1.5, ["radius"]=0.5, ["edge"]=0.3, ["color"]=Rgb(1,0.8,0.6), ["density"]=0.95 }'
                              % mat(SPOT), 'BarnDoorLightFilter("/f")'),
    'lf-cookie': scene('CookieLightFilter_v2("/f") { ["node_xform"]=%s, ["texture"]="%s", ["projector_focal"]=25, ["projector_film_width_aperture"]=24, '
                       '["blur_near_distance"]=2, ["blur_near_value"]=0.0, ["blur_far_distance"]=6, ["blur_far_value"]=0.05, ["blur_midpoint"]=4, '
                       '["blur_mid_value"]=0.02, ["outside_projection"]=1, ["density"]=0.9 }' % (mat(SPOT), TEX), 'CookieLightFilter_v2("/f")'),
    'lf-combine': scene('DecayLightFilter("/a") { ["falloff_far"]=true, ["far_start"]=3.5, ["far_end"]=6.0 }\n'
                        'ColorRampLightFilter("/b") { ["begin_distance"]=2.0, ["end_distance"]=6.0, ["distances"]={0,1}, ["colors"]={Rgb(1,0.9,0.5),Rgb(0.2,0.2,1)}, ["interpolation_types"]={1,1} }\n'
                        'CombineLightFilter("/f") { ["light_filters"]={DecayLightFilter("/a"), ColorRampLightFilter("/b")}, ["mode"]=1 }', 'CombineLightFilter("/f")'),
    # The cube's assignment takes the rod alone of the light's two filters; the floor takes both.
    'lf-set': scene('RodLightFilter("/r") { ["node_xform"]=%s, ["width"]=0.8, ["height"]=1.6, ["depth"]=0.8, ["radius"]=0.2, ["edge"]=0.5 }\n'
                    'IntensityLightFilter("/i") { ["color"]=Rgb(0.3,1,0.3) }\n'
                    'LightFilterSet("/fs") { RodLightFilter("/r") }' % mat(translate(0.6, 1, 0.4)),
                    'RodLightFilter("/r"), IntensityLightFilter("/i")', set_entry=', LightFilterSet("/fs")'),
    # A rod moving through the shutter.
    'lf-rod-moving': scene('RodLightFilter("/f") { ["node_xform"]=blur(%s, %s), ["width"]=0.6, ["height"]=1.6, ["depth"]=0.6, ["radius"]=0.1, ["edge"]=0.3 }'
                           % (mat(translate(-0.8, 1, 0.4)), mat(translate(1.0, 1, 0.4))), 'RodLightFilter("/f")',
                           sv_extra=', ["enable_motion_blur"]=true, ["motion_steps"]={-0.25, 0.25}'),
    # Shadow linking: the cube casts no shadow for the key light; on no receiver but the floor (complemented); not on
    # the floor; and with presence shadows.
    'sl-shadowset': scene('ShadowSet("/ss") { SpotLight("/key") }', '', set_entry=', ShadowSet("/ss")'),
    'sl-receiver': scene('ShadowReceiverSet("/rs") { ["geometries"]={RdlMeshGeometry("/floor")} }', '', set_entry=', ShadowReceiverSet("/rs")'),
    'sl-receiver-complement': scene('ShadowReceiverSet("/rs") { ["geometries"]={RdlMeshGeometry("/s")}, ["complement"]=true }', '', set_entry=', ShadowReceiverSet("/rs")'),
}
SPOT_PRESENCE = ('SpotLight("/key") { ["node_xform"]=%s, ["intensity"]=60, ["outer_cone_angle"]=70, ["inner_cone_angle"]=40, '
                 '["lens_radius"]=0.3, ["presence_shadows"]=1 }' % mat(SPOT))
cases['sl-presence'] = scene('ShadowSet("/ss") { SpotLight("/key") }', '', light=SPOT_PRESENCE, set_entry=', ShadowSet("/ss")').replace(
    '["roughness"]=0.3, ["specular"]=1.0 }', '["roughness"]=0.3, ["specular"]=1.0, ["presence"]=0.6 }')
# Ray termination lights: a glass cube with one bounce, the fill environment a terminator; and the key light one.
GLASS = '["roughness"]=0.3, ["specular"]=1.0 }'
glass = lambda text: text.replace(GLASS, '["roughness"]=0.05, ["specular"]=1.0, ["transmission"]=1.0, ["refractive_index"]=1.45 }').replace(
    '["max_depth"]=4, ["max_diffuse_depth"]=2', '["max_depth"]=1, ["max_diffuse_depth"]=1')
cases['rt-env'] = glass(scene('', '')).replace('EnvLight("/fill") { ["intensity"]=0.15 }', 'EnvLight("/fill") { ["intensity"]=0.6, ["ray_termination"]=true }')
cases['rt-spot'] = glass(scene('', '', light=('SpotLight("/key") { ["node_xform"]=%s, ["intensity"]=60, ["outer_cone_angle"]=70, '
                                             '["inner_cone_angle"]=40, ["lens_radius"]=0.3, ["ray_termination"]=true }' % mat(SPOT))))
# Lobe light sets: the cube's diffuse lobes see the environment alone, its specular ones the key alone; and with
# subsurface scattering (the Bssrdf takes the diffuse set).
SETS = 'LightSet("/dls") { EnvLight("/fill") }' + chr(10) + 'LightSet("/sls") { SpotLight("/key") }'
lobes = lambda text, extra='': text.replace(GLASS, '["roughness"]=0.3, ["specular"]=1.0, ["diffuse_lightset"]=LightSet("/dls"), '
                                            '["specular_lightset"]=LightSet("/sls")%s }' % extra)
cases['ls-lobes'] = lobes(scene(SETS, ''))
cases['ls-lobes-sss'] = lobes(scene(SETS, ''), ', ["scattering_radius"]=Rgb(0.2,0.1,0.05)')
for name, text in cases.items():
    if '["enable_motion_blur"]=true' in text:
        text = text.replace('["enable_motion_blur"]=false, ', '', 1)
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
