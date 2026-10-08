"""Supported scene settings and explicit EXR outputs."""
import math
ENUMS = {'sampling_mode': [('Uniform',0),('Adaptive',2)],
         'light_sampling_mode': [('Uniform lights',0),('Adaptive lights',1)],
         'shadow_terminator_fix': [('Off',0),('Targeted',1),('Sine',2),('GGX',3),('Cosine',4)]}
ENUMS['batch_tile_order'] = [('Morton',4),('Top to bottom',0),('Bottom to top',1),('Left to right',2),('Right to left',3),('Random',5),('Spiral square (default)',6),('Spiral rectangle',7),('Morton shift / flip',8)]
ENUMS['bucket_size'] = [('Auto (resolution)',0),('32 × 32',32),('64 × 64',64),('128 × 128',128),('256 × 256',256)]
RENDER = {
    'bucket_size': (0, 0, 256, 'Bucket size (preview and final)'),
    'batch_tile_order': (6, 0, 8, 'Tile order (preview and final)'),
    'sampling_mode': (2, 0, 2, 'Sampling mode'),
    'min_adaptive_samples': (4, 1, 1048576, 'Minimum samples / pixel'),
    'max_adaptive_samples': (12, 1, 1048576, 'Maximum samples / pixel'),
    'target_adaptive_error': (1.5, 0.000001, 1000.0, 'Target adaptive error'),
    'light_sampling_mode': (1, 0, 1, 'Light sampling mode'),
    'light_sampling_quality': (0.5, 0.0, 1.0, 'Adaptive light quality'),
    'bsdf_samples': (2, 1, 16, 'Material / BSDF sample grid'),
    'bssrdf_samples': (2, 1, 16, 'Subsurface sample grid'),
    'max_depth': (4, 0, 64, 'Total bounces'),
    'max_diffuse_depth': (2, 0, 64, 'Diffuse bounces'),
    'max_glossy_depth': (2, 0, 64, 'Glossy bounces'),
    'max_mirror_depth': (4, 0, 64, 'Mirror / refraction bounces'),
    'light_samples': (2, 1, 16, 'Light sample grid'),
    'shadow_terminator_fix': (1, 0, 4, 'Shadow boundary correction'),
}
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
}
AOVS = {
    'environment_background': ('Environment background', {'result':8,'lpe':"C<L.'modo_environment'>"}, 'environment_background'),
    'environment_lighting': ('Environment lighting', {'result':8,'lpe':"C.+<L.'modo_environment'>"}, 'environment_lighting'),
    'sample_count': ('Sample count', {'result': 11}, 'sample_count'),
    'alpha': ('Alpha', {'result': 1}, 'alpha'),
    'depth': ('Camera depth', {'result': 2}, 'depth'),
    'normal': ('Shading normal', {'result': 3, 'state_variable': 2}, 'normal'),
    'geometric_normal': ('Geometric normal', {'result': 3, 'state_variable': 1}, 'geometric_normal'),
    'position': ('World position', {'result': 3, 'state_variable': 10}, 'position'),
    'uv': ('UV coordinates', {'result': 3, 'state_variable': 3}, 'uv'),
    'wireframe': ('Wireframe', {'result': 6}, 'wireframe'),
    'diffuse_direct': ('Direct diffuse', {'result': 8, 'lpe': 'diffuse'}, 'diffuse_direct'),
    'glossy_direct': ('Direct glossy', {'result': 8, 'lpe': 'glossy'}, 'glossy_direct'),
    'emission': ('Emission', {'result': 8, 'lpe': 'emission'}, 'emission'),
    'transmission': ('Refraction / transmission', {'result': 8, 'lpe': 'C<T.>.*[<L.>O]'}, 'transmission'),
}


def render_values(values):
    result = {}
    for key, (default, minimum, maximum, _) in RENDER.items():
        value = values.get(key, default)
        valid_type=type(value) in (int,float) if isinstance(default,float) else type(value) is int
        if not valid_type or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError('Invalid render setting: ' + key)
        if key in ENUMS and value not in [entry[1] for entry in ENUMS[key]]: raise ValueError('Invalid setting: '+key)
        result[key] = value
    if result['min_adaptive_samples']>result['max_adaptive_samples']:
        raise ValueError('Minimum adaptive samples must not exceed maximum samples')
    return result


def object_values(values):
    result = {key: values.get(key, default) for key, (default, _) in OBJECT.items()}
    for key in ('override', 'subdivision', 'smooth', 'normal_override', 'angular_tessellation', 'share_instances', 'dynamic_tessellation', 'curves', 'curve_uv'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid object setting: ' + key)
    if type(result['level']) is not int or not 1 <= result['level'] <= 5:
        raise ValueError('Subdivision level must be between 1 and 5')
    if type(result['curve_samples']) is not int or not 1 <= result['curve_samples'] <= 256:
        raise ValueError('Samples per curve bend must be between 1 and 256')
    for key,low,high in [('smoothing_angle',0,180),('tessellation_angle',0.1,180),('adaptive_error',0,64),
                         ('curve_root_width',0,100000),('curve_tip_width',0,100000),('curve_envelope',0.01,100)]:
        value=result[key]
        if type(value) not in (float,int) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Invalid object setting: '+key)
    return result
