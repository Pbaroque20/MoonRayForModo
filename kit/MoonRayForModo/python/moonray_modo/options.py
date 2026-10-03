"""Supported scene settings and explicit EXR outputs."""
import math
ENUMS = {'sampling_mode': [('Uniform',0),('Adaptive',2)],
         'light_sampling_mode': [('Uniform lights',0),('Adaptive lights',1)],
         'shadow_terminator_fix': [('Off',0),('Targeted',1),('Sine',2),('GGX',3),('Cosine',4)]}
ENUMS['batch_tile_order'] = [('Morton (default)',4),('Top to bottom',0),('Bottom to top',1),('Left to right',2),('Right to left',3),('Random',5),('Spiral square',6),('Spiral rectangle',7),('Morton shift / flip',8)]
RENDER = {
    'batch_tile_order': (4, 0, 8, 'Tile order (preview and final)'),
    'sampling_mode': (2, 0, 2, 'Sampling mode'),
    'min_adaptive_samples': (16, 1, 1048576, 'Minimum samples / pixel'),
    'max_adaptive_samples': (256, 1, 1048576, 'Maximum samples / pixel'),
    'target_adaptive_error': (1.5, 0.000001, 1000.0, 'Target adaptive error'),
    'light_sampling_mode': (0, 0, 1, 'Light sampling mode'),
    'light_sampling_quality': (0.5, 0.0, 1.0, 'Adaptive light quality'),
    'bsdf_samples': (2, 1, 16, 'Material / BSDF sample grid'),
    'bssrdf_samples': (2, 1, 16, 'Subsurface sample grid'),
    'max_depth': (8, 0, 64, 'Total bounces'),
    'max_diffuse_depth': (2, 0, 64, 'Diffuse bounces'),
    'max_glossy_depth': (2, 0, 64, 'Glossy bounces'),
    'max_mirror_depth': (8, 0, 64, 'Mirror / refraction bounces'),
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
}
AOVS = {
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
    for key in ('override', 'subdivision', 'smooth', 'normal_override', 'angular_tessellation', 'share_instances', 'dynamic_tessellation'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid object setting: ' + key)
    if type(result['level']) is not int or not 1 <= result['level'] <= 5:
        raise ValueError('Subdivision level must be between 1 and 5')
    for key,low,high in [('smoothing_angle',0,180),('tessellation_angle',0.1,180),('adaptive_error',0,64)]:
        value=result[key]
        if type(value) not in (float,int) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError('Invalid object setting: '+key)
    return result
