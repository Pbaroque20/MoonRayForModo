"""Supported scene settings and explicit EXR outputs."""
import math
ENUMS = {'sampling_mode': [('Uniform',0),('Adaptive',2)],
         'light_sampling_mode': [('Uniform lights',0),('Adaptive lights',1)],
         'shadow_terminator_fix': [('Off',0),('Targeted',1),('Sine',2),('GGX',3),('Cosine',4)]}
ENUMS['batch_tile_order'] = [('Morton',4),('Top to bottom',0),('Bottom to top',1),('Left to right',2),('Right to left',3),('Random',5),('Spiral square (default)',6),('Spiral rectangle',7),('Morton shift / flip',8)]
ENUMS['displacement_tessellation'] = [('Uniform (mesh resolution)',0),('Follow Modo (Displacement Rate)',1),('Fixed dicing camera',2)]
ENUMS['bucket_size'] = [('Auto (resolution)',0),('32 x 32',32),('64 x 64',64),('128 x 128',128),('256 x 256',256)]
RENDER = {
    'bucket_size': (0, 0, 256, 'Bucket size (preview and final)'),
    'batch_tile_order': (6, 0, 8, 'Tile order (preview and final)'),
    'important_first': (0, 0, 1, 'Important parts first (preview)'),
    'sampling_mode': (0, 0, 2, 'Sampling mode'),
    'min_adaptive_samples': (16, 1, 1048576, 'Minimum samples / pixel'),
    'max_adaptive_samples': (4096, 1, 1048576, 'Maximum samples / pixel'),
    'target_adaptive_error': (10.0, 0.000001, 1000.0, 'Target adaptive error'),
    'light_sampling_mode': (0, 0, 1, 'Light sampling mode'),
    'light_sampling_quality': (0.5, 0.0, 1.0, 'Adaptive light quality'),
    'bsdf_samples': (2, 1, 16, 'Material / BSDF sample grid'),
    'bssrdf_samples': (2, 1, 16, 'Subsurface sample grid'),
    'max_depth': (4, 0, 64, 'Total bounces'),
    'max_diffuse_depth': (2, 0, 64, 'Diffuse bounces'),
    'max_glossy_depth': (2, 0, 64, 'Glossy bounces'),
    'max_mirror_depth': (4, 0, 64, 'Mirror / refraction bounces'),
    'light_samples': (2, 1, 16, 'Light sample grid'),
    'shadow_terminator_fix': (1, 0, 4, 'Shadow boundary correction'),
    # MoonRay's own scene variables, each starting at MoonRay's own value, so a scene that leaves them alone renders
    # as it did before they were here.
    'max_volume_depth': (1, 0, 64, 'Volume bounces'),
    'max_presence_depth': (16, 0, 256, 'Presence depth'),
    'max_hair_depth': (5, 0, 64, 'Hair bounces'),
    'max_subsurface_per_path': (1, 0, 64, 'Subsurface per path'),
    'russian_roulette_threshold': (0.0375, 0.0, 1.0, 'Russian roulette threshold'),
    'transparency_threshold': (1.0, 0.0, 1.0, 'Transparency threshold'),
    'presence_threshold': (0.999, 0.0, 1.0, 'Presence threshold'),
    'enable_presence_shadows': (0, 0, 1, 'Presence shadows'),
    # Below this path throughput, presence is sampled by chance (as Russian roulette): 1 never, 0 always.
    'presence_quality': (0.75, 0.0, 1.0, 'Presence quality'),
    # Each see-through surface a ray passes a sample of the Cryptomatte of its own.
    'cryptomatte_multi_presence': (0, 0, 1, 'Cryptomatte multi-presence'),
    # Each hair lobe sampled on its own, as light path expressions need to tell the lobes apart.
    'disable_optimized_hair_sampling': (0, 0, 1, 'Sample hair lobes separately'),
    'volume_quality': (0.5, 0.0, 1.0, 'Volume quality'),
    'volume_shadow_quality': (1.0, 0.0, 1.0, 'Volume shadow quality'),
    'volume_illumination_samples': (4, 0, 64, 'Volume illumination samples'),
    'volume_indirect_samples': (0, 0, 64, 'Volume indirect samples'),
    'volume_opacity_threshold': (0.995, 0.0, 1.0, 'Volume opacity threshold'),
    'volume_overlap_mode': (0, 0, 2, 'Overlapping volumes'),
    # How each further bounce of light inside a volume counts for less (MoonRay's multiple scattering, after
    # Wrenninge): its fog stops less, it sends less, and it is thrown more evenly. Only with Volume bounces above 1.
    'volume_attenuation_factor': (0.65, 0.0, 1.0, 'Volume attenuation factor'),
    'volume_contribution_factor': (0.65, 0.0, 1.0, 'Volume contribution factor'),
    'volume_phase_attenuation_factor': (0.5, 0.0, 1.0, 'Volume phase attenuation factor'),
    'sample_clamping_value': (10.0, 0.0, 1000000.0, 'Sample clamp'),
    'sample_clamping_depth': (1, 0, 64, 'Sample clamp from bounce'),
    'roughness_clamping_factor': (0.0, 0.0, 1.0, 'Roughness clamp'),
    'texture_blur': (0.0, 0.0, 1000.0, 'Texture blur'),
    'pixel_filter': (1, 0, 5, 'Pixel filter'),
    'pixel_filter_width': (3.0, 0.1, 64.0, 'Pixel filter width'),
    'lock_frame_noise': (0, 0, 1, 'Lock noise across frames'),
    # MoonRay's global switches, each at MoonRay's own value: on for displacement, subsurface and shadows, off for lights
    # seen by the camera and for a limit to geometry resolution (whose limit then matters not).
    'enable_displacement': (1, 0, 1, 'Displacement'),
    # How a displaced polygon mesh is tessellated where the object says nothing (the kit's own, OWN): 1 follows Modo, by
    # its render item's Displacement Rate, from the render camera; 2 the same from a dicing camera held at the Dicing
    # Frame (the triangles stay put while the camera moves: no shimmer in an animation); 0 uniformly, by mesh resolution.
    'displacement_tessellation': (1, 0, 2, 'Displacement tessellation'),
    # The screen error in pixels (adaptive_error) in place of Modo's Displacement Rate; 0: Modo's.
    'displacement_adaptive_error': (0.0, 0.0, 64.0, 'Adaptive error override (pixels; 0 = Modo\'s Displacement Rate)'),
    # The frame the fixed dicing camera is held at; below 0: the scene's first frame.
    'dicing_frame': (-1.0, -1000000.0, 1000000.0, 'Dicing frame (-1 = the first frame)'),
    'enable_subsurface_scattering': (1, 0, 1, 'Subsurface scattering'),
    'enable_shadowing': (1, 0, 1, 'Shadows'),
    'lights_visible_in_camera': (0, 0, 1, 'Lights seen by the camera'),
    'enable_max_geometry_resolution': (0, 0, 1, 'Limit geometry resolution'),
    'max_geometry_resolution': (1024, 1, 2147483647, 'Geometry resolution limit'),
}
# Settings MoonRay holds as on or off; they are kept here as 0 or 1.
BOOLS = ('enable_presence_shadows', 'cryptomatte_multi_presence', 'disable_optimized_hair_sampling', 'lock_frame_noise', 'important_first', 'enable_displacement', 'enable_subsurface_scattering',
         'enable_shadowing', 'lights_visible_in_camera', 'enable_max_geometry_resolution')
# Settings that are the kit's own, and are not written into a MoonRay scene by their names.
OWN = ('batch_tile_order', 'bucket_size', 'important_first', 'displacement_adaptive_error', 'displacement_tessellation', 'dicing_frame')
ENUMS['volume_overlap_mode'] = [('Add them up', 0), ('The densest', 1), ('One at random', 2)]
# The first three are MoonRay's own, from its source. The other three are this plugin's additions to MoonRay: filters that
# never go negative, which is what MoonRay's filter importance sampling needs (it places samples by the filter's shape).
ENUMS['pixel_filter'] = [('Box', 0), ('Cubic B-spline (default)', 1), ('Quadratic B-spline', 2),
                         ('Gaussian (MoonRay-compatible)', 3), ('Triangle (MoonRay-compatible)', 4),
                         ('Blackman-Harris (MoonRay-compatible)', 5)]
# The pixel filters a runtime has only where its MoonRay was built with them (modo-session.json says pixel_filters).
NEWER_PIXEL_FILTERS = {3: 'Gaussian', 4: 'Triangle', 5: 'Blackman-Harris'}
OBJECT = {
    'override': (False, 'Use object overrides'),
    'subdivision': (True, 'Subdivide in MoonRay'),
    'level': (3, 'Subdivision level'),
    'smooth': (True, 'Smooth shading'),
    'share_instances': (True, 'Share replica / instance geometry'),
    'dynamic_tessellation': (False, 'Camera-adaptive subdivision (expands instances)'),
    'normal_override': (False, 'Override normals by smoothing angle'),
    'smoothing_angle': (60.0, 'Smoothing angle (degrees)'),
    'angular_tessellation': (False, 'Estimate subdivision density from angle'),
    'tessellation_angle': (10.0, 'Target face angle (degrees, estimated)'),
    'adaptive_error': (0.0, 'Subdivision screen error (pixels; 0 = uniform)'),
    'curves': (True, 'Render curves as tubes'),
    'curve_root_width': (2.0, 'Curve width at the root (mm)'),
    'curve_tip_width': (2.0, 'Curve width at the tip (mm)'),
    'curve_envelope': (1.0, 'Curve envelope (1 = even taper; higher keeps the root width longer)'),
    'curve_samples': (8, 'Samples per curve bend'),
    'curve_uv': (True, 'Curve UVs along the length'),
    'curve_round': (False, 'Round curves (true tubes)'),
    'curve_basis': (0, 'What the points of a line are: the line itself, or the control points of a smooth curve'),
    'hair': (False, 'Grow hair from the curves, as guides'),
    'hair_scalp': ('', 'The mesh the hair grows on'),
    'hair_mode': (0, 'How strands are grown: around each guide, or between guides'),
    'hair_count': (100, 'Strands grown per guide'),
    'hair_width': (0.0, 'Width of a cluster at its root (mm); 0 sizes it from the guides'),
    'hair_clump': (0.3, 'How far a cluster closes toward its tip (0 to 1)'),
    'hair_length': (0.1, 'How much strands vary in length (0 to 1)'),
    'hair_seed': (1, 'Seed: another number grows other hair'),
    'hair_guides': (False, 'Render the guides as well'),
    # Cryptomatte: items given the same name share one matte; a number other than 0 is the matte's ID itself.
    'crypto_name': ('', 'Cryptomatte name (empty: the item\'s own)'),
    'crypto_id': (0, 'Cryptomatte ID (0: worked out from the name)'),
}
# The largest Cryptomatte ID that can be typed: Modo's whole numbers stop at 2147483647.
CRYPTO_ID_MAX = 2147483647
CURVE_BASES = [('The line itself', 0), ('Bezier control points', 1), ('B-spline control points', 2)]
HAIR_MODES = [('Around each guide (locks)', 0), ('Between guides (fur)', 1)]
# In the order the preview's buffer list and the form show them: what the surface is and how it is lit first (colour,
# diffuse, glossy, reflection, refraction, subsurface, emission, and diffuse without shadows for a shadow pass), then
# the environment, then what is for compositing and checking.
# Each: its label, its render output, and its channel in the EXR, by the names compositors look for: the beauty's alpha is A, depth is depth.Z.
AOVS = {
    'albedo': ('Albedo', {'result': 7, 'material_aov': 'albedo'}, 'albedo'),
    'diffuse_direct': ('Direct diffuse', {'result': 8, 'lpe': 'diffuse'}, 'diffuse_direct'),
    'indirect_diffuse': ('Indirect diffuse', {'result': 8, 'lpe': 'C<RD>[DSG]+[<L.>O]'}, 'indirect_diffuse'),
    'glossy_direct': ('Direct glossy', {'result': 8, 'lpe': 'glossy'}, 'glossy_direct'),
    'indirect_glossy': ('Indirect glossy', {'result': 8, 'lpe': 'C<RG>[DSG]+[<L.>O]'}, 'indirect_glossy'),
    'mirror_reflection': ('Mirror reflections', {'result': 8, 'lpe': 'reflection'}, 'mirror_reflection'),
    'transmission': ('Refraction / transmission', {'result': 8, 'lpe': 'C<T.>.*[<L.>O]'}, 'transmission'),
    'subsurface': ('Subsurface and translucency', {'result': 8, 'lpe': 'translucent'}, 'subsurface'),
    'emission': ('Emission', {'result': 8, 'lpe': 'emission'}, 'emission'),
    'unshadowed_diffuse': ('Diffuse without shadows (shadow pass)', {'result': 8, 'lpe': 'unoccluded;CD[<L.>O]'}, 'unshadowed_diffuse'),
    'environment_lighting': ('Environment lighting', {'result':8,'lpe':"C.+<L.'modo_environment'>"}, 'environment_lighting'),
    'environment_background': ('Environment background', {'result':8,'lpe':"C<L.'modo_environment'>"}, 'environment_background'),
    'alpha': ('Alpha', {'result': 1}, 'A'),
    'depth': ('Camera depth', {'result': 2}, 'depth.Z'),
    'normal': ('Shading normal', {'result': 3, 'state_variable': 2}, 'normal'),
    'geometric_normal': ('Geometric normal', {'result': 3, 'state_variable': 1}, 'geometric_normal'),
    'position': ('World position', {'result': 3, 'state_variable': 10}, 'position'),
    'uv': ('UV coordinates', {'result': 3, 'state_variable': 3}, 'uv'),
    'motion_vectors': ('Motion vectors', {'result': 3, 'state_variable': 12}, 'motion_vectors'),
    'wireframe': ('Wireframe', {'result': 6}, 'wireframe'),
    'sample_count': ('Sample count', {'result': 11}, 'sample_count'),
    # MoonRay's heat map: how long each pixel took to render.
    'time_per_pixel': ('Time per pixel', {'result': 5}, 'time_per_pixel'),
}
# MoonRay's compressions for an EXR, by its own numbers. The lossy ones (pxr24, b44, b44a, dwaa, dwab) are not used
# where a render may be taken up again from what it saved.
EXR_COMPRESSIONS = [('Zip (default)', 1), ('None', 0), ('RLE', 2), ('Zips', 3), ('PIZ', 4), ('PXR24 (lossy)', 5), ('B44 (lossy)', 6),
                    ('B44A (lossy)', 7), ('DWAA (lossy)', 8), ('DWAB (lossy)', 9)]
LOSSY_COMPRESSIONS = (5, 6, 7, 8, 9)


def render_values(values):
    result = {}
    for key, (default, minimum, maximum, _) in RENDER.items():
        value = values.get(key, default)
        if key in BOOLS and type(value) is bool: value = int(value)
        if isinstance(default, float) and type(value) is int: value = float(value)
        valid_type=type(value) in (int,float) if isinstance(default,float) else type(value) is int
        if not valid_type or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError('Invalid render setting: ' + key)
        if key in ENUMS and value not in [entry[1] for entry in ENUMS[key]]: raise ValueError('Invalid setting: '+key)
        result[key] = value
    if result['min_adaptive_samples']>result['max_adaptive_samples']:
        raise ValueError('Minimum adaptive samples must not exceed maximum samples')
    return result


# Worked out once for each set of values: a scene from Modo asks for every one of its meshes, most with none set.
_OBJECT_VALUES = {}


def object_values(values):
    try:
        key = (tuple(values.items()), tuple(map(type, values.values())))   # True is not 1 here
        held = _OBJECT_VALUES.get(key)
    except TypeError:
        return _object_values(values)
    if held is None:
        held = _object_values(values)
        if len(_OBJECT_VALUES) > 4096:
            _OBJECT_VALUES.clear()
        _OBJECT_VALUES[key] = held
    return dict(held)


def _object_values(values):
    result = {key: values.get(key, default) for key, (default, _) in OBJECT.items()}
    for key in ('override', 'subdivision', 'smooth', 'normal_override', 'angular_tessellation', 'share_instances', 'dynamic_tessellation', 'curves', 'curve_uv', 'curve_round', 'hair', 'hair_guides'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid object setting: ' + key)
    if type(result['level']) is not int or not 1 <= result['level'] <= 5:
        raise ValueError('Subdivision level must be between 1 and 5')
    for key in ('hair_scalp', 'crypto_name'):
        if type(result[key]) is not str:
            raise ValueError('Invalid object setting: ' + key)
    result['crypto_name'] = result['crypto_name'].strip()
    # Numbers past their limits are brought back to them rather than refused.
    for key, low, high in (('curve_basis', 0, 2), ('hair_mode', 0, 1), ('hair_count', 1, 2000), ('hair_seed', 0, 1000000), ('crypto_id', 0, CRYPTO_ID_MAX)):
        if type(result[key]) is not int:
            raise ValueError('Invalid object setting: ' + key)
        result[key] = min(high, max(low, result[key]))
    for key, low, high in (('hair_width', 0.0, 100000.0), ('hair_clump', 0.0, 1.0), ('hair_length', 0.0, .95)):
        if type(result[key]) not in (float, int) or not math.isfinite(result[key]):
            raise ValueError('Invalid object setting: ' + key)
        result[key] = min(high, max(low, float(result[key])))
    if type(result['curve_samples']) is not int or not 1 <= result['curve_samples'] <= 256:
        raise ValueError('Samples per curve bend must be between 1 and 256')
    for key,low,high in [('smoothing_angle',0,180),('tessellation_angle',0.1,180),('adaptive_error',0,64),
                         ('curve_root_width',0,100000),('curve_tip_width',0,100000),('curve_envelope',0.01,100)]:
        value=result[key]
        if type(value) not in (float,int) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Invalid object setting: '+key)
    return result
