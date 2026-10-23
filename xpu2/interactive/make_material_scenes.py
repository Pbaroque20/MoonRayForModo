"""Material fixtures for the shading library (SHADING.md): material balls, one scene per case.

make_material_scenes.py --output <new folder> [--cases ...]

Three spheres (smooth, with supplied normals and texture coordinates) on a floor before a back wall, lit by an
environment and a rectangular light, written as RDLA at 64 and 1024 samples a pixel. Each case gives the spheres
its materials; the floor and wall stay diffuse. The report has the large fixtures' form (resolution and scenes per
case), so run_material_benchmark.py can render each with both renderers."""
import argparse
import json
import math
import struct
from pathlib import Path

from run_material_progressive import call

RUNTIME = Path(__file__).resolve().parents[2] / 'test-results' / 'interactive-reference-042'

WIDTH, HEIGHT = 320, 240


def sphere(cx, cy, cz, r, nu=48, nv=24):
    verts, normals, uvs, tris = [], [], [], []
    for j in range(nv + 1):
        theta = math.pi * j / nv
        for i in range(nu + 1):
            phi = 2 * math.pi * i / nu
            n = (math.sin(theta) * math.cos(phi), math.cos(theta), math.sin(theta) * math.sin(phi))
            verts.append((cx + r * n[0], cy + r * n[1], cz + r * n[2]))
            normals.append(n)
            uvs.append((i / nu, 1 - j / nv))
    for j in range(nv):
        for i in range(nu):
            a, b = j * (nu + 1) + i, j * (nu + 1) + i + 1
            c, d = (j + 1) * (nu + 1) + i + 1, (j + 1) * (nu + 1) + i
            # Counter-clockwise seen from outside: MoonRay's Ng, (b - a) x (c - a), points out.
            if j != 0:
                tris += [a, b, c]
            if j != nv - 1:
                tris += [a, c, d]
    return verts, normals, uvs, tris


def quad(a, b, c, d):
    return [a, b, c, d], None, [(0, 0), (1, 0), (1, 1), (0, 1)], [0, 1, 2, 0, 2, 3]


def mesh_rdla(name, verts, normals, uvs, tris):
    attrs = ['["vertex_list"]={%s}' % ','.join('Vec3(%.6g,%.6g,%.6g)' % v for v in verts),
             '["face_vertex_count"]={%s}' % ','.join(['3'] * (len(tris) // 3)),
             '["vertices_by_index"]={%s}' % ','.join(map(str, tris)),
             '["is_subd"]=false', '["smooth_normal"]=false']
    if normals:
        attrs.append('["normal_list"]={%s}' % ','.join('Vec3(%.6g,%.6g,%.6g)' % n for n in normals))
    if uvs:
        attrs.append('["uv_list"]={%s}' % ','.join('Vec2(%.6g,%.6g)' % u for u in uvs))
    return 'RdlMeshGeometry("/%s") { %s }' % (name, ', '.join(attrs))


def strands(kind, count=400, seed=7):
    """A patch of strands before the balls: count curves of a kind's points (linear 6, Bezier 7, B-spline 6), each
    rising from the floor and bending, the radius thinning from root to tip."""
    points_per = {0: 6, 1: 7, 2: 6}[kind]
    state = seed
    def rnd():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7fffffff
        return state / 0x7fffffff
    verts, radii, counts, uvs = [], [], [], []
    for i in range(count):
        x, z = -2.6 + 5.2 * rnd(), 0.9 + 0.9 * rnd()
        height, lean, turn = 0.5 + 0.6 * rnd(), 0.15 + 0.35 * rnd(), 2 * math.pi * rnd()
        for k in range(points_per):
            t = k / (points_per - 1)
            bend = lean * t * t
            verts.append((x + bend * math.cos(turn), height * t, z + bend * math.sin(turn)))
            radii.append(0.016 * (1 - t) + 0.004 * t)
            uvs.append((i / count, t))
        counts.append(points_per)
    return verts, radii, counts, uvs


def curve_rdla(name, kind, subtype, verts, radii, counts, uvs=None, tessellation=4):
    attrs = ['["vertex_list_0"]={%s}' % ','.join('Vec3(%.6g,%.6g,%.6g)' % v for v in verts),
             '["radius_list"]={%s}' % ','.join('%.6g' % r for r in radii),
             '["curves_vertex_count"]={%s}' % ','.join(map(str, counts)),
             '["curve_type"]=%d' % kind, '["curves_subtype"]=%d' % subtype, '["tessellation_rate"]=%d' % tessellation]
    if uvs:
        attrs.append('["uv_list"]={%s}' % ','.join('Vec2(%.6g,%.6g)' % u for u in uvs))
    return 'RdlCurveGeometry("/%s") { %s }' % (name, ', '.join(attrs))


class Raw(str):
    """A value written as it is: an object reference or a vector."""


def value(v):
    if isinstance(v, Raw):
        return str(v)
    if isinstance(v, tuple):
        return 'Rgb(%g,%g,%g)' % v
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return '%g' % v if isinstance(v, float) else str(v)


def mat(cls, name, **a):
    return '%s("/%s") { %s }' % (cls, name, ', '.join('["%s"]=%s' % (k, value(v)) for k, v in a.items()))


def usd(name, **a):
    return mat('UsdPreviewSurface', name, **a)


def dwa(name, **a):
    return mat('DwaBaseMaterial', name, **a)


def ref(cls, name):
    return Raw('%s("/%s")' % (cls, name))


# Each case: the three spheres' materials, as RDLA material declarations named /s0, /s1, /s2.
CASES = {
    'usd-dielectric': [usd('s0', diffuseColor=(0.8, 0.15, 0.1), roughness=0.3),
                       usd('s1', diffuseColor=(0.1, 0.6, 0.15), roughness=0.5),
                       usd('s2', diffuseColor=(0.15, 0.25, 0.8), roughness=0.8)],
    'usd-metal': [usd('s0', diffuseColor=(0.95, 0.64, 0.54), metallic=1.0, roughness=0.2),
                  usd('s1', diffuseColor=(0.91, 0.92, 0.92), metallic=1.0, roughness=0.45),
                  usd('s2', diffuseColor=(1.0, 0.78, 0.34), metallic=1.0, roughness=0.75)],
    'usd-mirror': [usd('s0', diffuseColor=(0.95, 0.95, 0.95), metallic=1.0, roughness=0.0),
                   usd('s1', diffuseColor=(0.9, 0.6, 0.4), metallic=0.5, roughness=0.0),
                   usd('s2', diffuseColor=(0.2, 0.2, 0.25), roughness=0.0)],
    'usd-glass': [usd('s0', diffuseColor=(0.0, 0.0, 0.0), opacity=0.0, roughness=0.0, ior=1.5),
                  usd('s1', diffuseColor=(0.0, 0.0, 0.0), opacity=0.0, roughness=0.25, ior=1.5),
                  usd('s2', diffuseColor=(0.3, 0.3, 0.3), opacity=0.5, roughness=0.1, ior=1.33)],
    'usd-clearcoat': [usd('s0', diffuseColor=(0.7, 0.05, 0.05), roughness=0.6, clearcoat=1.0, clearcoatRoughness=0.0),
                      usd('s1', diffuseColor=(0.05, 0.3, 0.7), roughness=0.6, clearcoat=1.0, clearcoatRoughness=0.08),
                      usd('s2', diffuseColor=(0.8, 0.7, 0.2), metallic=1.0, roughness=0.5, clearcoat=0.5,
                          clearcoatRoughness=0.2)],
    'usd-mixed': [usd('s0', diffuseColor=(0.6, 0.6, 0.6), metallic=0.3, roughness=0.35),
                  usd('s1', diffuseColor=(0.5, 0.2, 0.6), useSpecularWorkflow=1, roughness=0.4),
                  usd('s2', diffuseColor=(0.2, 0.2, 0.2), emissiveColor=(0.6, 0.3, 0.1), roughness=0.5)],
    # The DwaBase family.
    'dwa-base': [dwa('s0', albedo=(0.8, 0.15, 0.1), roughness=0.3),
                 dwa('s1', metallic=1.0, metallic_color=(0.95, 0.75, 0.35), metallic_edge_color=(1.0, 0.9, 0.7), roughness=0.3),
                 dwa('s2', albedo=(0.1, 0.25, 0.8), roughness=0.5, diffuse_roughness=0.6, show_clearcoat=True, clearcoat=1.0,
                     clearcoat_roughness=0.05)],
    'dwa-family': [mat('DwaMetalMaterial', 's0', metallic_color=(0.95, 0.64, 0.54), roughness=0.4, anisotropy=0.6),
                   mat('DwaRefractiveMaterial', 's1', roughness=0.15, transmission_color=(0.85, 0.95, 0.9), refractive_index=1.45),
                   mat('DwaSolidDielectricMaterial', 's2', albedo=(0.2, 0.6, 0.3), roughness=0.4, diffuse_transmission=0.5,
                       diffuse_transmission_color=(0.8, 0.8, 0.3))],
    'dwa-fabric': [mat('DwaFabricMaterial', 's0', warp_color=(0.8, 0.2, 0.3), warp_roughness=0.4, albedo=(0.6, 0.1, 0.15),
                       fabric_diffuse_scattering=0.4),
                   mat('DwaVelvetMaterial_v2', 's1', fuzz_albedo=(0.3, 0.1, 0.6), fuzz_coverage=0.4, albedo=(0.2, 0.05, 0.3)),
                   dwa('s2', albedo=(0.3, 0.5, 0.2), roughness=0.6, show_fuzz=True, fuzz_albedo=(0.9, 0.9, 0.8), fuzz_roughness=0.3,
                       fuzz=0.7)],
    'dwa-iridescence': [mat('DwaEmissiveMaterial', 's0', emission=(0.9, 0.5, 0.2)),
                        dwa('s1', albedo=(0.05, 0.05, 0.05), roughness=0.25, iridescence=1.0,
                            iridescence_primary_color=(1.0, 0.0, 0.0), iridescence_secondary_color=(0.0, 0.0, 1.0),
                            iridescence_at_0_incidence=0.2),
                        dwa('s2', albedo=(0.5, 0.5, 0.5), roughness=0.35, iridescence=0.8, iridescence_color_control=1,
                            iridescence_ramp_interpolation_mode=1, iridescence_thickness=0.6, iridescence_exponent=2.0)],
    # The combinators.
    'dwa-layer': [dwa('m_plastic', albedo=(0.7, 0.7, 0.65), roughness=0.4),
                  mat('DwaMetalMaterial', 'm_gold', metallic_color=(1.0, 0.78, 0.34), roughness=0.25),
                  dwa('m_red', albedo=(0.8, 0.1, 0.1), roughness=0.6),
                  mat('DwaLayerMaterial', 's0', material_A=ref('DwaMetalMaterial', 'm_gold'),
                      material_B=ref('DwaBaseMaterial', 'm_plastic'), mask=0.5),
                  mat('DwaMixMaterial', 's1', material0=ref('DwaBaseMaterial', 'm_plastic'), material1=ref('DwaMetalMaterial', 'm_gold'),
                      material2=ref('DwaBaseMaterial', 'm_red'), mix=0.7),
                  mat('DwaLayerMaterial', 's2', material_A=ref('DwaBaseMaterial', 'm_red'),
                      material_B=ref('DwaLayerMaterial', 's0'), mask=0.35, blend_color_space=1)],
    'dwa-adjust': [dwa('m_plastic', albedo=(0.2, 0.5, 0.7), roughness=0.3),
                   mat('DwaMetalMaterial', 'm_steel', metallic_color=(0.8, 0.8, 0.82), roughness=0.35),
                   mat('DwaAdjustMaterial', 's0', input_material=ref('DwaBaseMaterial', 'm_plastic'), disable_specular=True,
                       emission_mode=2, emission=(0.05, 0.02, 0.0)),
                   mat('DwaSwitchMaterial', 's1', material0=ref('DwaBaseMaterial', 'm_plastic'),
                       material1=ref('DwaMetalMaterial', 'm_steel'), choice=1),
                   mat('DwaColorCorrectMaterial', 's2', input_material=ref('DwaBaseMaterial', 'm_plastic'), hue_shift=0.3,
                       saturation=0.5, gain=1.2, TMI_enabled=True, TMI=(0.3, -0.2, 0.0))],
    # Maps: procedural ones, the kit's, and bindings through colour corrections.
    'map-procedural': [
        mat('CheckerboardMap', 'checker', color_A=(0.8, 0.2, 0.1), color_B=(0.95, 0.9, 0.8), num_u_tiles=12, num_v_tiles=6),
        mat('RampMap', 'ramp', ramp_type=0, space=6, positions=Raw('{0.0, 0.5, 1.0}'),
            colors=Raw('{Rgb(0.1,0.2,0.8), Rgb(0.9,0.9,0.2), Rgb(0.8,0.1,0.3)}'), interpolations=Raw('{1, 1, 1}')),
        mat('ColorCorrectHsvMap', 'hsv', hue_shift=40.0, saturation_factor=0.8),
        mat('GradientMap', 'gradient', color_A=(0.2, 0.7, 0.3), color_B=(0.9, 0.5, 0.1), start=Raw('Vec3(1.0,0.0,0.0)'),
            end=Raw('Vec3(1.0,1.4,0.0)'), space=2, falloff_type=2),
        mat('OpMap', 'op', operation=2, op1=(1.0, 1.0, 1.0)),
        mat('ConstantScalarMap', 'half', scalar_value=0.5),
        dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.4),
        dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.35),
        usd('s2', diffuseColor=(1.0, 1.0, 1.0), roughness=0.5),
        'DwaBaseMaterial("/s0") { ["albedo"]=bind(CheckerboardMap("/checker"),Rgb(1,1,1)), ["roughness"]=bind(ConstantScalarMap("/half"),1.0) }',
        'ColorCorrectHsvMap("/hsv") { ["input"]=bind(RampMap("/ramp"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s1") { ["albedo"]=bind(ColorCorrectHsvMap("/hsv"),Rgb(1,1,1)) }',
        'OpMap("/op") { ["op2"]=bind(GradientMap("/gradient"),Rgb(1,1,1)) }',
        'UsdPreviewSurface("/s2") { ["diffuseColor"]=bind(OpMap("/op"),Rgb(1,1,1)) }',
    ],
    'map-modo': [
        mat('ModoTextureMap', 'noise', mode=3, background=(0.15, 0.3, 0.6), foreground=(0.9, 0.85, 0.7), scale=Raw('Vec2(10,10)')),
        mat('ModoTextureMap', 'heights', mode=3, scale=Raw('Vec2(14,14)'), octaves=3),
        mat('ModoTextureMap', 'bump', mode=1, height=1.0, bump_strength=0.03, bump_step=0.002),
        mat('ModoNormalMap', 'bump_normal'),
        mat('ModoTextureMap', 'checks', mode=2, background=(0.9, 0.2, 0.2), foreground=(0.2, 0.2, 0.9), scale=Raw('Vec2(6,3)')),
        mat('ModoTextureMap', 'modo_layer', mode=0, blend=1, foreground=(0.8, 0.9, 1.0), opacity=0.7),
        dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.5),
        dwa('s1', albedo=(0.7, 0.55, 0.3), roughness=0.3, input_normal=ref('ModoNormalMap', 'bump_normal')),
        dwa('s2', albedo=(1.0, 1.0, 1.0), roughness=0.6),
        'DwaBaseMaterial("/s0") { ["albedo"]=bind(ModoTextureMap("/noise"),Rgb(1,1,1)) }',
        'ModoTextureMap("/bump") { ["height"]=bind(ModoTextureMap("/heights"),1.0) }',
        'ModoNormalMap("/bump_normal") { ["input"]=bind(ModoTextureMap("/bump"),Vec3(0,0,1)) }',
        'ModoTextureMap("/modo_layer") { ["background"]=bind(ModoTextureMap("/checks"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s2") { ["albedo"]=bind(ModoTextureMap("/modo_layer"),Rgb(1,1,1)) }',
    ],
    'dwa-toon': [
        mat('DwaToonMaterial', 's0', albedo=(0.85, 0.35, 0.2), diffuse_model=1, positions=Raw('{0.0, 0.45, 0.55, 1.0}'),
            colors=Raw('{Rgb(1,1,1), Rgb(1,1,1), Rgb(0.35,0.35,0.35), Rgb(0.2,0.2,0.2)}'), interpolations=Raw('{1, 1, 1, 1}'), specular=0.6,
            specular_model=2, toon_specular_tint=(1.0, 0.95, 0.8), toon_specular_stretch_u=0.3),
        mat('DwaToonMaterial', 's1', albedo=(0.3, 0.6, 0.85), diffuse_model=0, diffuse_flatness=0.6, terminator_shift=0.2,
            specular=1.0, specular_model=1, roughness=0.35),
        mat('DwaToonMaterial', 's2', albedo=(0.5, 0.8, 0.3), diffuse_model=1, extend_ramp=True, ramp_input_scale=0.8,
            specular=0.8, specular_model=2, toon_specular_enable_indirect_reflections=True,
            toon_specular_indirect_reflections_roughness=0.3, toon_specular_indirect_reflections_intensity=0.5),
    ],
    'map-noise': [
        mat('NoiseMap_v2', 'perlin', space=2, frequency_multiplier=3.0, max_level=4.5, color_A=(0.1, 0.2, 0.5),
            color_B=(0.9, 0.8, 0.6)),
        mat('NoiseMap_v2', 'simplex', space=4, noise_type=1, color=True, distortion=0.4, max_level=3.0, flow_angle=0.7,
            flow_advection_rate=0.3, frequency_multiplier=2.0, seed=7),
        mat('NoiseWorleyMap_v3', 'worley', space=2, frequency=4.0, F1=-1.0, F2=1.0, max_level=2.5, color_A=(0.9, 0.85, 0.3),
            color_B=(0.15, 0.1, 0.4)),
        mat('NoiseWorleyMap_v2', 'cells', space=2, frequency=6.0, output_mode=2, distance_method=2),
        mat('BlendMap', 'mix', blend_type=0, blend_amount=0.5),
        dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.4),
        dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.35),
        dwa('s2', albedo=(1.0, 1.0, 1.0), roughness=0.5),
        'DwaBaseMaterial("/s0") { ["albedo"]=bind(NoiseMap_v2("/perlin"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s1") { ["albedo"]=bind(NoiseMap_v2("/simplex"),Rgb(1,1,1)) }',
        'BlendMap("/mix") { ["color_A"]=bind(NoiseWorleyMap_v3("/worley"),Rgb(1,1,1)), ["color_B"]=bind(NoiseWorleyMap_v2("/cells"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s2") { ["albedo"]=bind(BlendMap("/mix"),Rgb(1,1,1)) }',
    ],
    # ColorCorrectLegacyMap over a noise: brightness, contrast, hue, saturation; inverted monochrome with a mask and a
    # clamp; the maximum after a negative hue shift.
    'map-cc-legacy': [
        mat('NoiseMap_v2', 'perlin', space=2, frequency_multiplier=3.0, max_level=4.5, color_A=(0.1, 0.2, 0.5),
            color_B=(0.9, 0.8, 0.6)),
        mat('ColorCorrectLegacyMap', 'cc0', brightness=20.0, contrast=40.0, hue=90.0, saturation=-30.0),
        mat('ColorCorrectLegacyMap', 'cc1', contrast=-50.0, invert=True, monochrome=1, multiplier=(0.9, 0.6, 0.3), clamp=True,
            mask=0.7),
        mat('ColorCorrectLegacyMap', 'cc2', saturation=60.0, monochrome=4, hue=-200.0),
        dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.4),
        dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.35),
        dwa('s2', albedo=(1.0, 1.0, 1.0), roughness=0.5),
        'ColorCorrectLegacyMap("/cc0") { ["input"]=bind(NoiseMap_v2("/perlin"),Rgb(1,1,1)) }',
        'ColorCorrectLegacyMap("/cc1") { ["input"]=bind(NoiseMap_v2("/perlin"),Rgb(1,1,1)) }',
        'ColorCorrectLegacyMap("/cc2") { ["input"]=bind(NoiseMap_v2("/perlin"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s0") { ["albedo"]=bind(ColorCorrectLegacyMap("/cc0"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s1") { ["albedo"]=bind(ColorCorrectLegacyMap("/cc1"),Rgb(1,1,1)) }',
        'DwaBaseMaterial("/s2") { ["albedo"]=bind(ColorCorrectLegacyMap("/cc2"),Rgb(1,1,1)) }',
    ],
    'dwa-sss': [
        dwa('s0', albedo=(0.9, 0.75, 0.65), scattering_color=(0.95, 0.45, 0.3), scattering_radius=0.25, specular=0.5,
            roughness=0.4),
        mat('DwaSkinMaterial', 's1', albedo=(0.85, 0.6, 0.5), scattering_color=(0.9, 0.35, 0.25), scattering_radius=0.2, bssrdf=1,
            roughness=0.45),
        dwa('s2', albedo=(0.3, 0.6, 0.9), scattering_color=(0.4, 0.7, 1.0), scattering_radius=0.35, specular=0.0,
            show_clearcoat=True, clearcoat=1.0, clearcoat_roughness=0.1),
    ],
    # Random-walk subsurface (bssrdf 2): MoonRay's VolumeSubsurface.
    # Glitter (object space): large flakes, two styles, and the additive layering at part strength.
    'dwa-glitter': [
        dwa('s0', albedo=(0.5, 0.05, 0.1), roughness=0.5, show_glitter=True, glitter_space=4, glitter_size_A=0.08,
            glitter_density=20.0, glitter_color_A=(1.0, 0.8, 0.3), glitter_color_hue_variation=0.1, glitter_color_value_variation=0.3),
        mat('DwaMetalMaterial', 's1', metallic_color=(0.6, 0.6, 0.65), roughness=0.3, show_glitter=True, glitter_space=4,
            glitter_size_A=0.06, glitter_density=25.0, glitter_style_A_frequency=0.6, glitter_style_B_frequency=0.4,
            glitter_color_B=(0.3, 0.6, 1.0), glitter_size_B=0.04, glitter_seed=3),
        dwa('s2', albedo=(0.1, 0.2, 0.5), roughness=0.35, show_glitter=True, glitter_space=4, glitter_size_A=0.1,
            glitter_density=15.0, glitter_layering_mode=1, glitter_randomness=0.9, glitter=0.7, glitter_roughness_A=0.3),
    ],
    # Dense glitter: micro flakes (the stochastic flakes lobe), blended toward its GGX lobe, and GGX alone.
    'dwa-glitter-micro': [
        dwa('s0', albedo=(0.05, 0.05, 0.08), roughness=0.5, show_glitter=True, glitter_space=4, glitter_size_A=0.003,
            glitter_density=600.0, glitter_color_A=(0.9, 0.85, 0.7), glitter_LOD_quality=0.0, glitter_color_saturation_variation=0.4),
        dwa('s1', albedo=(0.3, 0.02, 0.05), roughness=0.4, show_glitter=True, glitter_space=4, glitter_size_A=0.0018,
            glitter_density=1000.0, glitter_color_A=(1.0, 0.5, 0.6), glitter_LOD_quality=0.0, glitter_randomness=0.3),
        dwa('s2', albedo=(0.1, 0.3, 0.1), roughness=0.4, show_glitter=True, glitter_space=4, glitter_size_A=0.0006,
            glitter_density=3000.0, glitter_color_A=(0.7, 1.0, 0.7)),
    ],
    'dwa-sss-rw': [
        dwa('s0', albedo=(0.9, 0.75, 0.65), scattering_color=(0.95, 0.45, 0.3), scattering_radius=0.25, specular=0.5,
            roughness=0.4, bssrdf=2),
        mat('DwaSkinMaterial', 's1', albedo=(0.85, 0.6, 0.5), scattering_color=(0.9, 0.35, 0.25), scattering_radius=0.2, bssrdf=2,
            roughness=0.45),
        dwa('s2', albedo=(0.3, 0.6, 0.9), scattering_color=(0.4, 0.7, 1.0), scattering_radius=0.35, specular=0.0, bssrdf=2,
            show_clearcoat=True, clearcoat=1.0, clearcoat_roughness=0.1),
    ],
    'dwa-twosided': [dwa('m_front', albedo=(0.8, 0.6, 0.1), roughness=0.3),
                     mat('DwaRefractiveMaterial', 'm_glass', roughness=0.0, transmission_color=(0.9, 0.95, 1.0)),
                     mat('DwaTwoSidedMaterial', 's0', front_material=ref('DwaBaseMaterial', 'm_front'),
                         back_material=ref('DwaBaseMaterial', 'm_front')),
                     mat('DwaColorCorrectMaterial', 's1', input_material=ref('DwaRefractiveMaterial', 'm_glass'), gain=0.8),
                     mat('DwaLayerMaterial', 's2', material_A=ref('DwaRefractiveMaterial', 'm_glass'),
                         material_B=ref('DwaBaseMaterial', 'm_front'), mask=0.6)],
}


def write_pfm(path, w, h, fn):
    """A float RGB image, fn(u, v) per texel (u, v in [0, 1), v up)."""
    rows = []
    for j in range(h):  # PFM rows run bottom to top
        for i in range(w):
            rows.append(struct.pack('<3f', *fn((i + 0.5) / w, (j + 0.5) / h)))
    path.write_bytes(b'PF\n%d %d\n-1.0\n' % (w, h) + b''.join(rows))


def bump_normal(u, v):
    """A tangent-space normal of ripples, encoded in [0, 1]."""
    a, f = 0.35, 6.0
    n = (-a * math.cos(2 * math.pi * f * u), -a * math.cos(2 * math.pi * f * v), 1.0)
    length = math.sqrt(sum(c * c for c in n))
    return tuple(0.5 * c / length + 0.5 for c in n)


def textures(assets):
    """The image maps' textures, mip-mapped TX files in the frozen asset folder."""
    out = {}
    checker = assets / 'checker.tx'
    call([RUNTIME / 'oiiotool.exe', '--pattern', 'checker:width=16:height=16:color1=0.85,0.25,0.15:color2=0.95,0.9,0.75', '256x256',
          '3', '-d', 'uint8', '--otex', checker], RUNTIME, assets, 'make-checker')
    out['checker'] = checker
    pfm = assets / 'bump.pfm'
    write_pfm(pfm, 128, 128, bump_normal)
    bump = assets / 'bump.tx'
    call([RUNTIME / 'oiiotool.exe', pfm, '-d', 'float', '--otex', bump], RUNTIME, assets, 'make-bump')
    out['bump'] = bump
    pfm = assets / 'stripes.pfm'
    write_pfm(pfm, 128, 64, lambda u, v: (0.2 + 0.6 * (int(u * 12) % 2), 0.3 + 0.5 * v, 0.6 - 0.4 * u))
    stripes = assets / 'stripes.tx'
    call([RUNTIME / 'oiiotool.exe', pfm, '-d', 'float', '--otex', stripes], RUNTIME, assets, 'make-stripes')
    out['stripes'] = stripes
    # A UDIM set: tiles 1001 and 1002 (1011 left missing).
    for tile, colour in ((1001, (0.85, 0.3, 0.2)), (1002, (0.2, 0.45, 0.85))):
        pfm = assets / ('udim.%d.pfm' % tile)
        write_pfm(pfm, 64, 64, lambda u, v, c=colour: tuple(x * (0.6 + 0.4 * (int(u * 8 + v * 8) % 2)) for x in c))
        call([RUNTIME / 'oiiotool.exe', pfm, '-d', 'float', '--otex', assets / ('udim.%d.tx' % tile)], RUNTIME, assets,
             'make-udim-%d' % tile)
    out['udim'] = assets / 'udim.<UDIM>.tx'
    return out


def path_value(p):
    return Raw('"%s"' % str(p).replace('\\', '/'))


# A UDIM pattern in Windows' own form: MoonRay's tile search on Windows joins the folder's listing with a backslash
# and compares whole paths, so a pattern with forward slashes finds no tile there.
def native_path_value(p):
    return Raw('"%s"' % str(p).replace('/', '\\').replace('\\', '\\\\'))


# Cases built with the fixture's asset folder (their textures live there).
TEXTURED = {
    'map-image': lambda t: [
        'SceneVariables { ["max_diffuse_depth"]=0 }',  # textured bounces need secondary ray differentials
        mat('ImageMap', 'tex_checker', texture=path_value(t['checker'])),
        mat('ImageNormalMap', 'tex_bump', tangent_space_normal_texture=path_value(t['bump'])),
        mat('ImageMap', 'tex_stripes', texture=path_value(t['stripes']), scale=Raw('Vec2(2,1.5)'), rotation_angle=30.0),
        dwa('s0', albedo=Raw('Rgb(1,1,1)'), roughness=0.45),
        dwa('s1', albedo=(0.6, 0.62, 0.65), metallic=1.0, metallic_color=(0.9, 0.85, 0.8), roughness=0.3,
            input_normal=ref('ImageNormalMap', 'tex_bump')),
        usd('s2', diffuseColor=(1.0, 1.0, 1.0), roughness=0.5),
        'DwaBaseMaterial("/s0") { ["albedo"]=bind(ImageMap("/tex_checker"),Rgb(1,1,1)) }',
        'UsdPreviewSurface("/s2") { ["diffuseColor"]=bind(ImageMap("/tex_stripes"),Rgb(1,1,1)) }',
    ],
}


# The same image maps with full bounces (secondary ray differentials, MoonRay's indirect texture options).
TEXTURED['map-image-bounce'] = lambda t: TEXTURED['map-image'](t)[1:]
TEXTURED['map-projection'] = lambda t: [
    mat('ProjectPlanarMap', 'planar', projection_mode=2, scale=Raw('Vec3(1.4,1.4,1.4)'), translate=Raw('Vec3(-1.6,0.7,0)')),
    mat('ProjectSphericalMap', 'spherical', projection_mode=2, translate=Raw('Vec3(0,0.7,0)'), rotate=Raw('Vec3(0,30,0)')),
    mat('ProjectCylindricalMap', 'cylindrical', projection_mode=2, translate=Raw('Vec3(1.6,0.2,0)'), black_outside_projection=False),
    mat('ImageMap', 'via_planar', texture=path_value(t['checker']), texture_coordinates=2),
    mat('ImageMap', 'via_spherical', texture=path_value(t['stripes']), texture_coordinates=2),
    mat('ImageMap', 'via_udim', texture=native_path_value(t['udim']), texture_coordinates=2, use_default_color_when_missing=True,
        default_color=(0.1, 0.9, 0.1)),
    mat('ProjectPlanarMap', 'udim_planar', projection_mode=2, scale=Raw('Vec3(0.7,1.4,1.4)'), translate=Raw('Vec3(1.6,0.7,0)')),
    dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.45),
    dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.4),
    usd('s2', diffuseColor=(1.0, 1.0, 1.0), roughness=0.5),
    'ImageMap("/via_planar") { ["input_texture_coordinates"]=bind(ProjectPlanarMap("/planar"),Vec3(0,0,0)) }',
    'ImageMap("/via_spherical") { ["input_texture_coordinates"]=bind(ProjectSphericalMap("/spherical"),Vec3(0,0,0)) }',
    'ImageMap("/via_udim") { ["input_texture_coordinates"]=bind(ProjectPlanarMap("/udim_planar"),Vec3(0,0,0)) }',
    'DwaBaseMaterial("/s0") { ["albedo"]=bind(ImageMap("/via_planar"),Rgb(1,1,1)) }',
    'DwaBaseMaterial("/s1") { ["albedo"]=bind(ImageMap("/via_spherical"),Rgb(1,1,1)) }',
    'UsdPreviewSurface("/s2") { ["diffuseColor"]=bind(ImageMap("/via_udim"),Rgb(1,1,1)) }',
]


# Triplanar projection (ProjectTriplanarMap_v2): three textures with a narrow transition; six with random rotation, offset
# and flip and per-face transforms; one, its S inverted and S and T swapped, with the widest transition.
TEXTURED['map-triplanar'] = lambda t: [
    mat('ProjectTriplanarMap_v2', 'tri3', projection_mode=2, scale=Raw('Vec3(0.6,0.6,0.6)'), translate=Raw('Vec3(-1.6,0.7,0)'),
        number_of_textures=3, transition_width=0.3, positive_x_texture=path_value(t['checker']),
        positive_y_texture=path_value(t['stripes']), positive_z_texture=path_value(t['checker'])),
    mat('ProjectTriplanarMap_v2', 'tri6', projection_mode=2, translate=Raw('Vec3(0,0.7,0)'), rotate=Raw('Vec3(0,25,10)'),
        number_of_textures=6, randomize_rotation=True, randomize_offset=True, randomize_flip=True, random_seed=5,
        positive_x_texture=path_value(t['checker']), positive_y_texture=path_value(t['stripes']),
        positive_z_texture=path_value(t['checker']), negative_x_texture=path_value(t['stripes']),
        negative_y_texture=path_value(t['checker']), negative_z_texture=path_value(t['stripes']),
        positive_x_rotation=30.0, positive_x_rotation_center=Raw('Vec2(0.2,0.1)'), negative_y_scale=Raw('Vec2(0.5,0.7)'),
        negative_z_offset=Raw('Vec2(0.3,0.1)'), positive_y_active=False, negative_x_wrap_around=False),
    mat('ProjectTriplanarMap_v2', 'tri1', projection_mode=2, translate=Raw('Vec3(1.6,0.7,0)'), number_of_textures=1,
        transition_width=1.0, positive_x_texture=path_value(t['stripes']), positive_x_invert_s=True, positive_x_swap_st=True),
    dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.45),
    dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.4),
    usd('s2', diffuseColor=(1.0, 1.0, 1.0), roughness=0.5),
    'DwaBaseMaterial("/s0") { ["albedo"]=bind(ProjectTriplanarMap_v2("/tri3"),Rgb(1,1,1)) }',
    'DwaBaseMaterial("/s1") { ["albedo"]=bind(ProjectTriplanarMap_v2("/tri6"),Rgb(1,1,1)) }',
    'UsdPreviewSurface("/s2") { ["diffuseColor"]=bind(ProjectTriplanarMap_v2("/tri1"),Rgb(1,1,1)) }',
]


# Camera projection (ProjectCameraMap_v2) from a second camera: the checker in front only, black outside; the stripes
# on back faces too, beyond the frame, with a custom aspect ratio; the bump as ProjectCameraNormalMap.
TEXTURED['map-camera'] = lambda t: [
    'PerspectiveCamera("/projector") { ["node_xform"]=Mat4(0.965926,0,-0.258819,0, 0,1,0,0, 0.258819,0,0.965926,0, 0.8,1.0,3.5,1),'
    ' ["focal"]=30.0, ["film_width_aperture"]=24.0, ["near"]=0.1, ["far"]=100.0 }',
    mat('ProjectCameraMap_v2', 'camproj', projector=Raw('PerspectiveCamera("/projector")'), texture=path_value(t['checker'])),
    mat('ProjectCameraMap_v2', 'camproj2', projector=Raw('PerspectiveCamera("/projector")'), texture=path_value(t['stripes']),
        project_on_back_faces=True, black_outside_projection=False, aspect_ratio_source=1, custom_aspect_ratio=0.75),
    dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.45),
    dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.4),
    mat('ProjectCameraNormalMap', 'camnorm', projector=Raw('PerspectiveCamera("/projector")'), texture=path_value(t['bump'])),
    dwa('s2', albedo=(0.6, 0.65, 0.7), roughness=0.3, specular=1.0, input_normal=Raw('ProjectCameraNormalMap("/camnorm")')),
    'DwaBaseMaterial("/s0") { ["albedo"]=bind(ProjectCameraMap_v2("/camproj"),Rgb(1,1,1)) }',
    'DwaBaseMaterial("/s1") { ["albedo"]=bind(ProjectCameraMap_v2("/camproj2"),Rgb(1,1,1)) }',
]


# Normal maps that combine others: two tangent-space bumps (one scaled and turned) joined by CombineNormalMap, a
# SwitchNormalMap choosing the combination, and a constant normal from RgbToNormalMap.
TEXTURED['map-normals'] = lambda t: [
    mat('ImageNormalMap', 'nm_a', tangent_space_normal_texture=path_value(t['bump'])),
    mat('ImageNormalMap', 'nm_b', tangent_space_normal_texture=path_value(t['bump']), scale=Raw('Vec2(2.5,1.5)'), rotation_angle=40.0),
    mat('CombineNormalMap', 'comb', input_1=Raw('ImageNormalMap("/nm_a")'), input_2=Raw('ImageNormalMap("/nm_b")'),
        normal_map_2_dial=0.6),
    mat('SwitchNormalMap', 'sw', choice=1.0, input0=Raw('ImageNormalMap("/nm_a")'), input1=Raw('CombineNormalMap("/comb")')),
    mat('RgbToNormalMap', 'rgbn', input=(0.3, 0.8, 0.5)),
    dwa('s0', albedo=(0.8, 0.5, 0.3), roughness=0.3, specular=1.0, input_normal=Raw('CombineNormalMap("/comb")')),
    dwa('s1', albedo=(0.4, 0.6, 0.8), roughness=0.25, specular=1.0, input_normal=Raw('SwitchNormalMap("/sw")')),
    dwa('s2', albedo=(0.5, 0.7, 0.4), roughness=0.4, specular=1.0, input_normal=Raw('RgbToNormalMap("/rgbn")'), input_normal_dial=0.5),
]


# Projected normal maps: ProjectTriplanarNormalMap_v2 with the bump texture on three axes, and on six with random
# turns; ProjectPlanarNormalMap, clamped.
TEXTURED['map-triplanar-normal'] = lambda t: [
    mat('ProjectTriplanarNormalMap_v2', 'tn3', projection_mode=2, scale=Raw('Vec3(0.5,0.5,0.5)'), translate=Raw('Vec3(-1.6,0.7,0)'),
        number_of_textures=3, positive_x_texture=path_value(t['bump']), positive_y_texture=path_value(t['bump']),
        positive_z_texture=path_value(t['bump'])),
    mat('ProjectTriplanarNormalMap_v2', 'tn6', projection_mode=2, translate=Raw('Vec3(0,0.7,0)'), number_of_textures=6,
        randomize_rotation=True, random_seed=11, transition_width=0.8,
        **{f + '_texture': path_value(t['bump']) for f in ('positive_x', 'positive_y', 'positive_z', 'negative_x', 'negative_y', 'negative_z')}),
    dwa('s0', albedo=(0.8, 0.5, 0.3), roughness=0.3, specular=1.0, input_normal=Raw('ProjectTriplanarNormalMap_v2("/tn3")')),
    dwa('s1', albedo=(0.4, 0.6, 0.8), roughness=0.25, specular=1.0, input_normal=Raw('ProjectTriplanarNormalMap_v2("/tn6")'),
        input_normal_dial=0.7),
    mat('ProjectPlanarNormalMap', 'pn', projection_mode=2, scale=Raw('Vec3(0.8,0.8,0.8)'), translate=Raw('Vec3(1.6,0.7,0)'),
        rotate=Raw('Vec3(0,20,0)'), texture=path_value(t['bump']), wrap_around=False),
    dwa('s2', albedo=(0.5, 0.7, 0.4), roughness=0.3, specular=1.0, input_normal=Raw('ProjectPlanarNormalMap("/pn")')),
]


# UVTransformMap feeding ImageMap's texture coordinates: texture space turned about its centre and scaled; world space
# turned about an axis; render space scaled and offset.
TEXTURED['map-uvtransform'] = lambda t: [
    mat('UVTransformMap', 'uv_tex', rotation_angle=35.0, scale=Raw('Vec2(3,2)'), offset=Raw('Vec2(0.1,0.2)')),
    mat('UVTransformMap', 'uv_world', space=2, rotation_angle=30.0, rotation_axis=Raw('Vec3(0.3,1,0.2)'), scale=Raw('Vec2(1.5,1.5)')),
    mat('UVTransformMap', 'uv_render', space=0, scale=Raw('Vec2(0.8,0.8)'), offset=Raw('Vec2(0.5,0.25)')),
    mat('ImageMap', 'via_tex', texture=path_value(t['checker']), texture_coordinates=2),
    mat('ImageMap', 'via_world', texture=path_value(t['stripes']), texture_coordinates=2),
    mat('ImageMap', 'via_render', texture=path_value(t['checker']), texture_coordinates=2),
    dwa('s0', albedo=(1.0, 1.0, 1.0), roughness=0.45),
    dwa('s1', albedo=(1.0, 1.0, 1.0), roughness=0.4),
    usd('s2', diffuseColor=(1.0, 1.0, 1.0), roughness=0.5),
    'ImageMap("/via_tex") { ["input_texture_coordinates"]=bind(UVTransformMap("/uv_tex"),Vec3(0,0,0)) }',
    'ImageMap("/via_world") { ["input_texture_coordinates"]=bind(UVTransformMap("/uv_world"),Vec3(0,0,0)) }',
    'ImageMap("/via_render") { ["input_texture_coordinates"]=bind(UVTransformMap("/uv_render"),Vec3(0,0,0)) }',
    'DwaBaseMaterial("/s0") { ["albedo"]=bind(ImageMap("/via_tex"),Rgb(1,1,1)) }',
    'DwaBaseMaterial("/s1") { ["albedo"]=bind(ImageMap("/via_world"),Rgb(1,1,1)) }',
    'UsdPreviewSurface("/s2") { ["diffuseColor"]=bind(ImageMap("/via_render"),Rgb(1,1,1)) }',
]


# Glitter in reference space: the balls carry ref_P (their points 10% further from their centres).
GLITTER_REF = [
    dwa('s0', albedo=(0.5, 0.05, 0.1), roughness=0.5, show_glitter=True, glitter_size_A=0.08, glitter_density=20.0,
        glitter_color_A=(1.0, 0.8, 0.3)),
    mat('DwaMetalMaterial', 's1', metallic_color=(0.6, 0.6, 0.65), roughness=0.3, show_glitter=True, glitter_size_A=0.002,
        glitter_density=800.0, glitter_compensate_reference_space_deformation=False),
    dwa('m_glitter', albedo=(0.1, 0.2, 0.5), roughness=0.35, show_glitter=True, glitter_space=4, glitter_size_A=0.1,
        glitter_density=15.0),
    dwa('m_plain', albedo=(0.7, 0.7, 0.65), roughness=0.4),
    mat('DwaLayerMaterial', 's2', material_A=ref('DwaBaseMaterial', 'm_glitter'), material_B=ref('DwaBaseMaterial', 'm_plain'),
        mask=0.6),
]
REF_P_CASES = {'dwa-glitter-ref': GLITTER_REF}


def box(cx, cy, cz, sx, sy, sz):
    """A closed box, its faces counter-clockwise seen from outside."""
    x0, x1, y0, y1, z0, z1 = cx - sx, cx + sx, cy - sy, cy + sy, cz - sz, cz + sz
    verts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    quads = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5)]
    tris = []
    for a, b, c, d in quads:
        tris += [a, b, c, a, c, d]
    return verts, None, None, tris


# Volume cases: the balls' materials and volumes, the extra meshes that bound volumes alone (name, mesh, volume), the
# volumes of the balls (ball name -> volume name) and scene variables.
GLASS = dict(roughness=0.0, transmission_color=(1.0, 1.0, 1.0), refractive_index=1.5)
VOLUMES = {
    # Absorption inside glass (the kit's Modo absorption distance): no scattering.
    'volume-absorption': dict(
        materials=[mat('DwaRefractiveMaterial', 's0', **GLASS), mat('DwaRefractiveMaterial', 's1', **GLASS), dwa('s2', albedo=(0.6, 0.6, 0.6), roughness=0.4),
                   mat('BaseVolume', 'v0', diffuse_color=(0.0, 0.0, 0.0), attenuation_color=(0.3, 1.2, 2.5)),
                   mat('BaseVolume', 'v1', diffuse_color=(0.0, 0.0, 0.0), attenuation_color=(2.0, 0.8, 0.2), attenuation_intensity=0.6)],
        ball_volumes={'ball0': 'v0', 'ball1': 'v1'}, extra=[], variables=''),
    # A fog box over the balls, lit by the key light and the sky: single scattering.
    'volume-fog': dict(
        materials=None, ball_volumes={}, extra=[('fog', box(0.0, 1.05, 0.0, 2.6, 0.95, 1.2), 'fogv')],
        volume_materials=[mat('BaseVolume', 'fogv', diffuse_color=(0.8, 0.8, 0.8), attenuation_color=(0.35, 0.35, 0.35))],
        variables=''),
    # Forward scattering, two overlapping volumes and the multiple scattering approximation (max volume depth 3).
    'volume-fog-multi': dict(
        materials=None, ball_volumes={},
        extra=[('fog', box(-0.6, 1.05, 0.0, 1.8, 0.95, 1.2), 'fogv'), ('fog2', box(1.0, 1.2, 0.0, 1.4, 0.9, 1.0), 'fogv2')],
        volume_materials=[mat('BaseVolume', 'fogv', diffuse_color=(0.9, 0.85, 0.8), attenuation_color=(0.5, 0.5, 0.5), anisotropy=0.5),
                          mat('BaseVolume', 'fogv2', diffuse_color=(0.5, 0.7, 0.9), attenuation_color=(0.8, 0.6, 0.4))],
        variables='SceneVariables { ["max_volume_depth"]=3 }'),
    # Attenuation and density ramps over the depth a ray travels through the volume, inside a glass ball.
    'volume-ramp': dict(
        materials=[mat('DwaRefractiveMaterial', 's0', **GLASS), dwa('s1', albedo=(0.6, 0.6, 0.6), roughness=0.4), mat('DwaRefractiveMaterial', 's2', **GLASS),
                   mat('BaseVolume', 'v0', diffuse_color=(0.7, 0.7, 0.7), attenuation_color=(0.5, 0.5, 0.5), use_attenuation_ramp=True,
                       attenuation_colors=Raw('{Rgb(0.2,0.5,1.0), Rgb(2.0,1.0,0.3)}'), attenuation_distances=Raw('{0.0, 1.0}'),
                       attenuation_min_depth=0.2, attenuation_max_depth=1.2,
                       densities=Raw('{0.5, 2.0}'), density_min_depth=0.0, density_max_depth=1.4),
                   mat('BaseVolume', 'v2', diffuse_color=(0.0, 0.0, 0.0), attenuation_color=(1.0, 1.0, 1.0), match_diffuse=False,
                       invert_attenuation_color=True)],
        ball_volumes={'ball0': 'v0', 'ball2': 'v2'}, extra=[], variables=''),
}
FOG_BALLS = [dwa('s0', albedo=(0.8, 0.2, 0.15), roughness=0.4), dwa('s1', albedo=(0.2, 0.6, 0.2), roughness=0.4),
             dwa('s2', albedo=(0.2, 0.3, 0.8), roughness=0.4)]
for _case in VOLUMES.values():
    if _case['materials'] is None:
        _case['materials'] = FOG_BALLS + _case['volume_materials']


# Displacement cases (given the fixture's textures): the balls' materials and displacements, and each displaced ball's
# displacement and mesh resolution (1: displaced as it is; n: each edge cut into n, uniformly).
DISPLACEMENT = {
    'disp-noise': lambda t: dict(materials=[
        mat('NoiseMap_v2', 'bumps', space=2, frequency_multiplier=3.0, max_level=4.5, color_A=(0.0, 0.0, 0.0), color_B=(1.0, 1.0, 1.0)),
        mat('NoiseWorleyMap_v3', 'cells', space=2, frequency=4.0, F1=-1.0, F2=1.0, max_level=2.5),
        dwa('s0', albedo=(0.8, 0.35, 0.2), roughness=0.4), dwa('s1', albedo=(0.3, 0.6, 0.3), roughness=0.35, specular=0.8),
        dwa('s2', albedo=(0.3, 0.4, 0.8), roughness=0.5),
        mat('NormalDisplacement', 'd0', zero_value=0.5, height_multiplier=0.15),
        'NormalDisplacement("/d0") { ["height"]=bind(NoiseMap_v2("/bumps"),1.0) }',
        mat('VectorDisplacement', 'd1', vector=Raw('Vec3(0.03,0.06,0.0)')),
        mat('NormalDisplacement', 'd2', height_multiplier=0.1),
        'NormalDisplacement("/d2") { ["height"]=bind(NoiseWorleyMap_v3("/cells"),1.0) }',
    ], displaced={'ball0': ('d0', 4), 'ball1': ('d1', 1), 'ball2': ('d2', 5)}),
    # Image maps: a tessellated ball raised by stripes, one moved along its tangent frame by a checker.
    'disp-image': lambda t: dict(materials=[
        'SceneVariables { ["max_diffuse_depth"]=0 }',  # textured bounces need secondary ray differentials
        mat('ImageMap', 'tex_checker', texture=path_value(t['checker'])),
        mat('ImageMap', 'tex_stripes', texture=path_value(t['stripes']), scale=Raw('Vec2(2,1.5)')),
        dwa('s0', albedo=(0.8, 0.8, 0.75), roughness=0.4), dwa('s1', albedo=(0.7, 0.5, 0.3), roughness=0.3, specular=0.8),
        dwa('s2', albedo=(0.3, 0.4, 0.8), roughness=0.5),
        mat('NormalDisplacement', 'd0', height_multiplier=0.08),
        'NormalDisplacement("/d0") { ["height"]=bind(ImageMap("/tex_stripes"),1.0) }',
        mat('VectorDisplacement', 'd1', factor=0.05, tangent_space_style=1),
        'VectorDisplacement("/d1") { ["vector"]=bind(ImageMap("/tex_checker"),Vec3(0,0,0)) }',
    ], displaced={'ball0': ('d0', 6), 'ball1': ('d1', 3)}),
}


def scene(grid, materials, curves=(), ref_p=False, volumes=None, displaced=None):
    lines = [
        'SceneVariables { ["image_width"]=%d, ["image_height"]=%d, ["pixel_samples"]=%d, ["sampling_mode"]=0, ["frame"]=0,'
        ' ["pixel_filter"]=0, ["pixel_filter_width"]=1.0, ["max_depth"]=5, ["max_diffuse_depth"]=2,'
        ' ["lights_visible_in_camera"]=false, ["two_stage_output"]=false, ["enable_motion_blur"]=false,'
        ' ["enable_dof"]=false }' % (WIDTH, HEIGHT, grid),
        # A slight downward look: the camera turned 12 degrees about X.
        'PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,0.978148,0.207912,0, 0,-0.207912,0.978148,0,'
        ' 0,1.9,6.2,1), ["focal"]=40.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }',
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'EnvLight("/sky") { ["intensity"]=0.35, ["color"]=Rgb(0.8,0.9,1.0) }',
        # Above and in front, facing down (its local -Z turned to world -Y), tilted toward the balls.
        'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0.258819,-0.965926,0, 0,0.965926,0.258819,0, 1.5,4.5,2.5,1),'
        ' ["width"]=2.5, ["height"]=2.5, ["intensity"]=0.06 }',
        'LightSet("/lights") { EnvLight("/sky"), RectLight("/key") }',
        'RenderOutput("/beauty") { ["file_name"]="beauty.exr", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="beauty.exr", ["result"]=1, ["channel_format"]=0, ["compression"]=1 }',
        usd('floor_m', diffuseColor=(0.45, 0.45, 0.42), useSpecularWorkflow=1),
        usd('wall_m', diffuseColor=(0.35, 0.4, 0.5), useSpecularWorkflow=1),
    ] + materials
    meshes = [('floor', quad((-8, 0, 4), (8, 0, 4), (8, 0, -6), (-8, 0, -6)), 'floor_m'),
              ('wall', quad((-8, 0, -4), (8, 0, -4), (8, 6, -4), (-8, 6, -4)), 'wall_m'),
              ('ball0', sphere(-1.6, 0.7, 0, 0.7), 's0'), ('ball1', sphere(0, 0.7, 0, 0.7), 's1'),
              ('ball2', sphere(1.6, 0.7, 0, 0.7), 's2')]
    # Meshes that bound volumes alone: no material.
    if volumes:
        meshes += [(name, m, None) for name, m, _ in volumes['extra']]
        if volumes['variables']:
            lines.append(volumes['variables'])
    for name, m, _ in meshes:
        declaration = mesh_rdla(name, *m)
        if ref_p and name.startswith('ball'):
            centre = [sum(v[k] for v in m[0]) / len(m[0]) for k in range(3)]
            rest = [tuple(centre[k] + 1.1 * (v[k] - centre[k]) for k in range(3)) for v in m[0]]
            lines.append('UserData("/refp_%s") { ["vec3f_key"]="ref_P", ["vec3f_values_0"]={%s}, ["rate"]=4 }'
                         % (name, ','.join('Vec3(%.6g,%.6g,%.6g)' % v for v in rest)))
            declaration = declaration[:-2] + ', ["primitive_attributes"]={UserData("/refp_%s")} }' % name
        if displaced and name in displaced:
            declaration = declaration[:-2] + ', ["mesh_resolution"]=%g }' % displaced[name][1]
        lines.append(declaration)
    # Curves: (name, RdlCurveGeometry declaration, material).
    for _, declaration, _ in curves:
        lines.append(declaration)
    geometry = [('RdlMeshGeometry', name, m) for name, _, m in meshes] + [('RdlCurveGeometry', name, m) for name, _, m in curves]
    lines.append('GeometrySet("/geometry") { %s }' % ','.join('%s("/%s")' % (cls, name) for cls, name, _ in geometry))
    # Each mesh's material by its declaration's class (the floor and wall UsdPreviewSurface, the balls their case's).
    classes = {d[d.index('("/') + 3:d.index('")')]: d[:d.index('("/')] for d in lines if '("/' in d}
    volume_of = {}
    if volumes:
        volume_of.update(volumes['ball_volumes'])
        volume_of.update({name: v for name, _, v in volumes['extra']})

    def entry(cls, name, m):
        parts = ['%s("/%s")' % (cls, name), '""']
        if m:
            parts.append('%s("/%s")' % (classes[m], m))
        parts.append('LightSet("/lights")')
        if name in volume_of:
            parts.append('BaseVolume("/%s")' % volume_of[name])
        if displaced and name in displaced:
            parts.append('%s("/%s")' % (classes[displaced[name][0]], displaced[name][0]))
        return '{ %s }' % ', '.join(parts)
    lines.append('Layer("/layer") { %s }' % ','.join(entry(cls, name, m) for cls, name, m in geometry))
    lines.append('SceneVariables { ["layer"]=Layer("/layer") }')
    return '\n'.join(lines) + '\n'


# Curve cases: the balls' materials, and a patch of strands of a type (0 linear, 1 Bezier, 2 B-spline) and subtype
# (0 facing the ray, 1 round) with material /c0.
CURVE_BALLS = [dwa('s0', albedo=(0.8, 0.2, 0.15), roughness=0.4), dwa('s1', albedo=(0.2, 0.6, 0.2), roughness=0.4),
               dwa('s2', albedo=(0.2, 0.3, 0.8), roughness=0.4)]
CURVE_MATERIAL = dwa('c0', albedo=(0.75, 0.55, 0.3), roughness=0.35)
# Hair materials for the strands (HairMaterial_v3, HairDiffuseMaterial), and whether the strands carry scatter_tag.
HAIR = mat('HairMaterial_v3', 'c0', hair_color=(0.45, 0.28, 0.14))
HAIR_CURVES = {
    'curve-hair': (0, 0, HAIR, False),
    'curve-hair-separate': (0, 0, mat('HairMaterial_v3', 'c0', hair_color=(0.45, 0.28, 0.14), use_optimized_sampling=False), False),
    'curve-hair-round': (0, 1, HAIR, False),
    'curve-hair-bspline': (2, 0, HAIR, False),
    'curve-hair-diffuse': (0, 0, mat('HairDiffuseMaterial', 'c0', hair_color=(0.6, 0.4, 0.25)), False),
    'curve-hair-glint': (0, 0, mat('HairMaterial_v3', 'c0', hair_color=(0.2, 0.12, 0.08), fresnel_type=2, show_hair_glint=True,
                                   glint_roughness=0.3), True),
    # HairToonMaterial: hair diffuse, a surface toon specular and a hair toon specular with indirect reflections.
    'curve-hair-toon': (0, 0, mat('HairToonMaterial', 'c0', hair_color=(0.5, 0.3, 0.15), specular_1_stretch_u=0.2,
                                  specular_2_show=True, specular_2_model=3, specular_2_roughness=0.3, specular_2_tint=(1.0, 0.9, 0.7),
                                  specular_2_enable_indirect_reflections=True, specular_2_indirect_reflections_intensity=0.5), False),
    'curve-hair-toon-hair': (2, 0, mat('HairToonMaterial', 'c0', hair_color=(0.3, 0.35, 0.6), hair_diffuse=0.7, specular_1_model=3,
                                       specular_1_roughness=0.25, specular_1_intensity=2.0), False),
}
CURVES = {'curve-linear': (0, 0), 'curve-linear-round': (0, 1), 'curve-bezier': (1, 0), 'curve-bspline': (2, 0),
          'curve-bspline-round': (2, 1)}
CURVES.update({k: v[:2] for k, v in HAIR_CURVES.items()})


def curve_case(case):
    kind, subtype = CURVES[case]
    verts, radii, counts, uvs = strands(kind)
    material, scatter = (HAIR_CURVES[case][2], HAIR_CURVES[case][3]) if case in HAIR_CURVES else (CURVE_MATERIAL, False)
    declaration = curve_rdla('hair', kind, subtype, verts, radii, counts, uvs)
    extra = []
    if scatter:
        # A random number a strand (the kit's scatter_tag), uniform over the curves.
        tags = [((i * 2654435761) % 1000003) / 1000003.0 for i in range(len(counts))]
        extra.append('UserData("/scatter") { ["float_key"]="scatter_tag", ["float_values_0"]={%s} }' % ','.join('%.6f' % t for t in tags))
        declaration = declaration[:-2] + ', ["primitive_attributes"]={UserData("/scatter")} }'
    return CURVE_BALLS + [material] + extra, [('hair', declaration, 'c0')]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cases', nargs='+', default=list(CASES) + list(TEXTURED) + list(CURVES) + list(REF_P_CASES) + list(VOLUMES) + list(DISPLACEMENT))
    a = p.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'cases': {}}
    for case in a.cases:
        entry = report['cases'][case] = {'resolution': [WIDTH, HEIGHT], 'domain': 'material balls', 'scenes': {}}
        for grid in (8, 32):
            d = out / case / f'grid-{grid}' / 'frozen'
            (d / 'assets').mkdir(parents=True)
            curves = ()
            displaced = None
            if case in DISPLACEMENT:
                spec = DISPLACEMENT[case](textures(d / 'assets'))
                materials, displaced = spec['materials'], spec['displaced']
            elif case in CURVES:
                materials, curves = curve_case(case)
            elif case in REF_P_CASES:
                materials = REF_P_CASES[case]
            elif case in VOLUMES:
                materials = VOLUMES[case]['materials']
            else:
                materials = TEXTURED[case](textures(d / 'assets')) if case in TEXTURED else CASES[case]
            (d / 'scene.rdla').write_text(scene(grid, materials, curves, case in REF_P_CASES, VOLUMES.get(case), displaced), encoding='utf-8')
            entry['scenes'][str(grid)] = str(d / 'scene.rdla')
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(out / 'report.json')


if __name__ == '__main__':
    main()
