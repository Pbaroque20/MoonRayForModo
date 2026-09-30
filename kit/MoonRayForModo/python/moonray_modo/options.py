"""Supported scene settings and explicit EXR outputs."""
RENDER = {
    'max_depth': (5, 0, 64, 'Total bounces'),
    'max_diffuse_depth': (2, 0, 64, 'Diffuse bounces'),
    'max_glossy_depth': (2, 0, 64, 'Glossy bounces'),
    'max_mirror_depth': (3, 0, 64, 'Mirror / refraction bounces'),
    'light_samples': (2, 1, 16, 'Light sample grid'),
    'shadow_terminator_fix': (1, 0, 4, 'Shadow boundary correction'),
}
OBJECT = {
    'override': (False, 'Use object overrides'),
    'subdivision': (True, 'Subdivide in MoonRay'),
    'level': (3, 'Subdivision level'),
    'smooth': (True, 'Smooth shading'),
}
AOVS = {
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
}


def render_values(values):
    result = {}
    for key, (default, minimum, maximum, _) in RENDER.items():
        value = values.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError('Invalid render setting: ' + key)
        result[key] = value
    return result


def object_values(values):
    result = {key: values.get(key, default) for key, (default, _) in OBJECT.items()}
    for key in ('override', 'subdivision', 'smooth'):
        if type(result[key]) is not bool:
            raise ValueError('Invalid object setting: ' + key)
    if type(result['level']) is not int or not 1 <= result['level'] <= 5:
        raise ValueError('Subdivision level must be between 1 and 5')
    return result
