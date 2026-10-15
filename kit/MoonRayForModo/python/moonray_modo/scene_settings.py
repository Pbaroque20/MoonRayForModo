"""The render settings a scene keeps on its Render item, and how each is shown in its form.

The settings are one record in the Render item's MoonRay tag. complete() fills in what a scene
has not set; FIELDS lists the ones edited in the Render item's MoonRay properties, in the order
and groups the form shows them. lxserv/moonray_render_settings.py makes a command for each and
tools/generate_render_forms.py lays them out.
"""
import copy
from . import options

# Preview-only choices are kept with the window, not the scene.
DEFAULTS = {
    'samples': 4, 'environment': 0.0, 'threads': 0, 'timeout': 0, 'surface': 0, 'subdivision_level': 3,
    'light_multiplier': 1.0, 'modo_environment': True, 'environment_multiplier': 1.0,
    'region_enabled': False, 'region': [0.0, 0.0, 1.0, 1.0], 'final_motion': False,
    'production': {}, 'asset_settings': {}, 'scene_variables': {},
    # A new scene outputs the object Cryptomatte, so the first render already has the mattes to look at.
    'custom_aovs': [{'name': 'crypto_object', 'kind': 'cryptomatte', 'category': 'object', 'depth': 6, 'precision': 0, 'filter': 0, 'part': '', 'expression': ''}], 'aovs': ['alpha'],
    'recovery': {'enabled': False, 'resume': True, 'minutes': 1.0},
    # A deep EXR written beside the render: every surface and volume a pixel sees, each at its own depth.
    'deep': {'enabled': False, 'format': 0, 'curvature': 45.0, 'z': 2.0, 'volume': 10},
    # How the final EXR is compressed, by MoonRay's numbers (options.EXR_COMPRESSIONS), and the level of its DWA ones.
    'exr': {'compression': 1, 'dwa_level': 85.0},
    'denoising': {'engine': 'off', 'preview': True, 'final': True, 'safe': False, 'smart': 'off', 'detail': 'some'},
    'execution_mode': 'auto', 'preview_buffer': 'beauty',
    # The camera MoonRay tessellates adaptive geometry for, by its item's identity; '' for the render camera.
    'dicing_camera': '',
    # The compositor's graph over a finished render's buffers (compositor.py); none until one is made.
    'compositor': {},
}


def complete(stored):
    """Every setting, with the default for each one the scene has not set."""
    from .display import DEFAULTS as display_defaults
    from .background import DEFAULTS as background_defaults
    result = copy.deepcopy(DEFAULTS)
    for key in DEFAULTS:
        if key in stored:
            held = copy.deepcopy(stored[key])
            if isinstance(DEFAULTS[key], dict) and key in ('recovery', 'denoising', 'deep', 'exr'):
                result[key].update(held if isinstance(held, dict) else {})
            else:
                result[key] = held
    render = dict(stored.get('render') or {})
    if render and 'sampling_mode' not in render:
        render['sampling_mode'] = 0
    try:
        result['render'] = options.render_values(render)
    except ValueError:
        result['render'] = options.render_values({})
    result['background'] = dict(background_defaults, **(stored.get('background') or {}))
    # What the scene has not chosen for itself is as last chosen through MoonRay on this machine.
    from . import display_memory
    last = display_memory.remembered()
    result['display'] = {key: (stored.get('display') or {}).get(key, last.get(key, value))
                         for key, value in display_defaults.items() if key != 'working_space'}
    return result


def field(key, path, kind, label, tip='', low=None, high=None, choices=None, scale=1.0, member=None):
    return {'key': key, 'path': path, 'kind': kind, 'label': label, 'tip': tip, 'low': low, 'high': high,
            'choices': choices, 'scale': scale, 'member': member}


def render_field(key, label, tip=''):
    default, low, high, _ = options.RENDER[key]
    if key in options.BOOLS:
        return field(key, ('render', key), 'bool', label, tip)
    if key in options.ENUMS:
        return field(key, ('render', key), 'choice', label, tip, choices=options.ENUMS[key])
    return field(key, ('render', key), 'float' if isinstance(default, float) else 'int', label, tip, low, high)


DENOISERS = [('Off', 'off'), ('NVIDIA OptiX (GPU)', 'optix'), ('Intel Open Image Denoise (CPU)', 'oidn_cpu')]
DETAILS = [('Off', 'off'), ('Some', 'some'), ('More', 'more')]
SMART = [('Off', 'off'), ('Draft: stop soonest', 'draft'), ('Medium', 'medium'), ('Fine: stop latest', 'fine')]
BACKGROUNDS = [('Scene environment', 'environment'), ('Black', 'black'), ('Solid color', 'color'), ('Image', 'image')]
SURFACES = [('As modeled', 0), ('Smooth subdivision', 1), ('Modo evaluated geometry', 2)]
VIEWS = [('Modo color management', 'modo'), ('ACES (sRGB display)', 'aces'), ('sRGB', 'srgb'), ('Highlight compression + sRGB', 'reinhard'), ('Raw linear', 'raw'), ('OCIO display / view', 'ocio')]
LUT_SPACES = [('After display transform', 'display'), ('Scene-linear, before view', 'linear')]
DEEP_FORMATS = [('OpenEXR 2', 0), ('OpenDCX 2', 1)]
MODES = [('Auto (XPU, Vector, Scalar)', 'auto'), ('XPU (NVIDIA GPU + CPU)', 'xpu'), ('Vector (CPU / AVX)', 'vectorized'), ('Scalar (CPU)', 'scalar')]

# (group, starts collapsed, fields). A field of kind 'button' runs a command instead, and one of
# kind 'command' shows a command of its own, named in its tip's place.
GROUPS = [
    ('Camera', False, [
        field('camera', None, 'command', 'Render Camera', 'Render through the Modo render camera or one of the MoonRay cameras in the scene, such as a fisheye'),
    ]),
    ('Sampling', False, [
        render_field('sampling_mode', 'Sampling', 'Adaptive stops sampling a pixel once it is clean enough'),
        field('samples', ('samples',), 'int', 'Pixel Samples', 'Uniform sampling: 4 means 4 x 4 = 16 samples per pixel', 1, 64),
        render_field('min_adaptive_samples', 'Minimum Samples', 'Adaptive sampling: fewest samples per pixel'),
        render_field('max_adaptive_samples', 'Maximum Samples', 'Adaptive sampling: most samples per pixel'),
        render_field('target_adaptive_error', 'Target Error', 'Adaptive sampling: lower is cleaner and slower'),
        render_field('light_sampling_mode', 'Light Sampling'),
        render_field('light_sampling_quality', 'Light Quality', 'Adaptive light sampling quality'),
        render_field('light_samples', 'Light Samples', '2 means 2 x 2 samples per light'),
        render_field('bsdf_samples', 'Material Samples', '2 means 2 x 2 samples per material'),
        render_field('bssrdf_samples', 'Subsurface Samples', '2 means 2 x 2 subsurface samples'),
    ]),
    ('Bounces', False, [
        render_field('max_depth', 'Total'),
        render_field('max_diffuse_depth', 'Diffuse'),
        render_field('max_glossy_depth', 'Glossy'),
        render_field('max_mirror_depth', 'Mirror / Refraction', 'Raise for stacked glass surfaces'),
        render_field('shadow_terminator_fix', 'Shadow Terminator', 'Softens the faceted shadow edge on coarse meshes'),
        render_field('max_volume_depth', 'Volume', 'How many times light bounces inside fog, smoke and clouds. 1 is quick; more brightens thick clouds'),
        render_field('max_hair_depth', 'Hair', 'Bounces from hair to hair. More brightens light hair'),
        render_field('max_presence_depth', 'Presence', 'How many see-through surfaces a ray passes before it stops'),
        render_field('max_subsurface_per_path', 'Subsurface', 'How many times one path may go beneath a surface'),
    ]),
    ('Volumes', True, [
        render_field('volume_quality', 'Quality', 'How finely fog and clouds are stepped through; higher is cleaner and slower'),
        render_field('volume_shadow_quality', 'Shadow Quality', 'The same, for the shadows volumes cast'),
        render_field('volume_illumination_samples', 'Light Samples', 'Samples of light taken along each ray through a volume; 0 turns volume lighting off'),
        render_field('volume_indirect_samples', 'Indirect Samples', 'Samples of bounced light inside volumes'),
        render_field('volume_opacity_threshold', 'Opacity Threshold', 'A ray stops once a volume has hidden this much of what is behind it'),
        render_field('volume_overlap_mode', 'Overlapping Volumes', 'What is rendered where volumes overlap'),
    ]),
    ('Noise and Filtering', True, [
        render_field('sample_clamping_value', 'Sample Clamp', 'Limits how bright one sample may be, which removes fireflies; 0 is no limit'),
        render_field('sample_clamping_depth', 'Clamp From Bounce', 'The clamp applies from this bounce on; 1 leaves what the camera sees directly alone'),
        render_field('roughness_clamping_factor', 'Roughness Clamp', 'Roughens materials after a bounce to remove fireflies; 0 is off'),
        render_field('russian_roulette_threshold', 'Russian Roulette', 'Paths dimmer than this may be ended early. Lower is cleaner and slower'),
        render_field('pixel_filter', 'Pixel Filter'),
        render_field('pixel_filter_width', 'Pixel Filter Width', 'In pixels'),
        render_field('texture_blur', 'Texture Blur', 'Softens every texture lookup'),
        render_field('transparency_threshold', 'Transparency Threshold', 'A ray stops once surfaces have hidden this much of what is behind them'),
        render_field('presence_threshold', 'Presence Threshold', 'A ray through see-through surfaces stops once they have hidden this much'),
        render_field('enable_presence_shadows', 'Presence Shadows', 'See-through surfaces cast lighter shadows. Slower'),
        render_field('lock_frame_noise', 'Same Noise Every Frame', 'The noise pattern does not change from frame to frame'),
    ]),
    # MoonRay's switches over the whole render, as it has them.
    ('Global Switches', True, [
        render_field('enable_displacement', 'Displacement', 'Off renders every displaced surface flat, as it is before its displacement'),
        render_field('enable_subsurface_scattering', 'Subsurface Scattering', 'Off renders subsurface materials with plain diffuse light, which is quicker'),
        render_field('enable_shadowing', 'Shadows', 'Off casts no shadows anywhere: lights reach everything they face'),
        render_field('lights_visible_in_camera', 'Lights Seen by the Camera', 'On shows lights to the camera as glowing shapes. Each MoonRay light can say otherwise for itself'),
        render_field('enable_max_geometry_resolution', 'Limit Geometry Resolution', 'Caps how finely subdivision surfaces and displacement are tessellated'),
        render_field('max_geometry_resolution', 'Geometry Resolution Limit', 'The cap, as a tessellation resolution'),
        field('dicing_camera', None, 'command', 'Dicing Camera', 'The camera adaptive tessellation is worked out for: the render camera, or another, for a render whose camera moves or is very close'),
    ]),
    ('Denoising', True, [
        field('denoiser', ('denoising', 'engine'), 'choice', 'Denoiser', '', choices=DENOISERS),
        field('denoise_preview', ('denoising', 'preview'), 'bool', 'Denoise Preview'),
        field('denoise_final', ('denoising', 'final'), 'bool', 'Save Denoised EXR', 'Written beside the original EXR, which is kept'),
        field('denoise_detail', ('denoising', 'detail'), 'choice', 'Keep Fine Detail', 'Hair, fur and other things a pixel or so wide, which a denoiser smooths away, are let through from the render as it was. More keeps more of them and more of their grain; Off is the denoiser alone', choices=DETAILS),
        field('smart_render', ('denoising', 'smart'), 'choice', 'Smart Render', 'A MoonRay render in the preview window is stopped once its picture is clean enough for the denoiser, and denoised: no need to wait for every sample. Draft stops soonest and leaves the denoiser the most to do; Fine stops latest. With no denoiser chosen, OptiX is used, or Open Image Denoise where OptiX will not run. A picture full of fine texture may never read as clean, and renders to its end. Switching it on switches Safe Denoising off', choices=SMART),
        field('denoise_safe', ('denoising', 'safe'), 'bool', 'Safe Denoising', 'Keep every buffer of a MoonRay render stopped by hand, and let Continue take it up again: the picture so far is saved as it renders, every few seconds where that is quick and less often for a large picture with many buffers. With this off, Stop still keeps the beauty and denoises it. Switching it on switches Smart Render off'),
    ]),
    ('Lighting', True, [
        field('light_multiplier', ('light_multiplier',), 'float', 'Light Multiplier', 'Scales every Modo light', 0.0, 10000.0),
        field('modo_environment', ('modo_environment',), 'bool', 'Use Modo Environments'),
        field('environment_multiplier', ('environment_multiplier',), 'float', 'Environment Multiplier', '', 0.0, 10000.0),
        field('environment', ('environment',), 'float', 'Uniform Fill Light', 'Extra even light from all directions; 0 is none', 0.0, 100.0),
        field('objects', None, 'button', 'Light Links, Emitters and Volumes...', 'Per-object and per-light scene controls'),
    ]),
    ('Camera Background', True, [
        field('background_mode', ('background', 'mode'), 'choice', 'Background', 'What the camera sees behind the scene', choices=BACKGROUNDS),
        field('background_color', ('background', 'color'), 'hex', 'Color'),
        field('background_image', ('background', 'image'), 'file', 'Image', 'A lat-long image'),
        field('background_intensity', ('background', 'intensity'), 'float', 'Brightness', '', 0.0, 10000.0),
        field('background_rotation', ('background', 'rotation'), 'float', 'Rotation', 'Degrees', -360.0, 360.0),
    ]),
    ('Geometry', True, [
        field('surface', ('surface',), 'choice', 'Surfaces', 'Evaluated geometry uses Modo tessellation and displacement', choices=SURFACES),
        field('subdivision_level', ('subdivision_level',), 'int', 'Subdivision Level', 'For meshes without their own MoonRay settings', 1, 5),
    ]),
    ('Render Region', True, [
        field('region_enabled', ('region_enabled',), 'bool', 'Render Region'),
        field('region_left', ('region', 0), 'float', 'Left', 'Percent of the frame', 0.0, 100.0, scale=100.0),
        field('region_top', ('region', 1), 'float', 'Top', 'Percent of the frame', 0.0, 100.0, scale=100.0),
        field('region_right', ('region', 2), 'float', 'Right', 'Percent of the frame', 0.0, 100.0, scale=100.0),
        field('region_bottom', ('region', 3), 'float', 'Bottom', 'Percent of the frame', 0.0, 100.0, scale=100.0),
    ]),
    ('Outputs (AOVs)', True,
     [field('aov_' + key, ('aovs',), 'member', label, 'Adds the ' + channel + ' channel to the EXR', member=key)
      for key, (label, _, channel) in options.AOVS.items()]),
    ('Display', True, [
        field('view', ('display', 'view'), 'choice', 'View Transform', 'How the preview is shown; EXRs stay linear. Modo color management follows the OCIO configuration and color spaces in Modo\'s system preferences; what is chosen here is remembered for new scenes; OCIO display / view uses the configuration, source, display and view named below', choices=VIEWS),
        field('exposure', ('display', 'exposure'), 'float', 'Exposure', 'Stops', -20.0, 20.0),
        field('lut', ('display', 'lut'), 'file', 'LUT File'),
        field('lut_space', ('display', 'lut_space'), 'choice', 'LUT Applies', '', choices=LUT_SPACES),
        field('ocio_config', ('display', 'config'), 'file', 'OCIO Config'),
        field('ocio_source', ('display', 'source'), 'text', 'OCIO Source'),
        field('ocio_display', ('display', 'display'), 'text', 'OCIO Display'),
        field('ocio_view', ('display', 'ocio_view'), 'text', 'OCIO View'),
        field('colors', None, 'button', 'Input Color Spaces and Texture Cache...'),
    ]),
    ('Output Renders', True, [
        field('final_motion', ('final_motion',), 'bool', 'Motion Blur', 'Motion blur and motion vectors in Render EXR and animations'),
        field('exr_compression', ('exr', 'compression'), 'choice', 'EXR Compression', 'How Render EXR and animations compress their EXRs. The lossy ones make smaller files; they are not used with checkpoints or Safe Denoising, which take a render up again from what it saved', choices=options.EXR_COMPRESSIONS),
        field('exr_dwa_level', ('exr', 'dwa_level'), 'float', 'DWA Compression Level', 'For DWAA and DWAB: higher is smaller and loses more', 0.0, 1000.0),
        field('deep', ('deep', 'enabled'), 'bool', 'Save a Deep EXR', 'Written beside the render as name.deep.exr: every surface and volume a pixel sees, each at its own depth, for deep compositing'),
        field('deep_format', ('deep', 'format'), 'choice', 'Deep Format', 'OpenEXR 2 opens everywhere. OpenDCX adds per-sample coverage masks, for compositors that read them', choices=DEEP_FORMATS),
        field('deep_curvature', ('deep', 'curvature'), 'float', 'Deep Curvature Tolerance', 'Degrees a surface may curve within a pixel before it is split into more deep samples', 0.0, 180.0),
        field('deep_z', ('deep', 'z'), 'float', 'Deep Depth Tolerance', 'How far a surface may run in depth within a pixel before it is split', 0.0, 1000000.0),
        field('deep_volume', ('deep', 'volume'), 'int', 'Deep Volume Detail', 'Lower makes smaller files for volumes', 1, 1000),
        field('checkpoint', ('recovery', 'enabled'), 'bool', 'Save Checkpoints'),
        field('checkpoint_resume', ('recovery', 'resume'), 'bool', 'Resume Matching Checkpoint'),
        field('checkpoint_minutes', ('recovery', 'minutes'), 'float', 'Checkpoint Interval', 'Minutes', 0.1, 1440.0),
    ]),
    ('System', True, [
        field('execution_mode', ('execution_mode',), 'choice', 'Rendering Mode', '', choices=MODES),
        field('threads', ('threads',), 'int', 'CPU Threads', '0 uses every thread', 0, 4096),
        field('timeout', ('timeout',), 'int', 'Time Limit', 'Minutes; 0 is no limit', 0, 10080),
        render_field('bucket_size', 'Bucket Size'),
        render_field('batch_tile_order', 'Bucket Order'),
        render_field('important_first', 'Important Parts First', 'A MoonRay render in the preview window looks over the whole picture in its first passes, then renders the buckets with the most in them (edges, detail, noise) before the plain ones, in the Bucket Order chosen'),
    ]),
    # Outputs that are written as expressions rather than ticked: a part of the light picked out by the path it took,
    # a value a material holds, an ID matte.
    ('Advanced', True, [
        field('outputs', None, 'button', 'Light Path Expressions...', 'Named outputs of the render: light path expressions, material AOVs and ID mattes'),
    ]),
]

FIELDS = [entry for _, _, entries in GROUPS for entry in entries]


def hex_to_rgb(text):
    text = str(text).strip().lstrip('#')
    try:
        return [int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except (ValueError, IndexError):
        return [0.0, 0.0, 0.0]


def rgb_to_hex(rgb):
    return '#' + ''.join('%02x' % max(0, min(255, int(round(float(v) * 255)))) for v in rgb)


def get(values, entry):
    """A field's value out of complete() settings, as its control shows it."""
    held = values
    for step in entry['path']:
        held = held[step]
    kind = entry['kind']
    if kind == 'member':
        return entry['member'] in held
    if kind == 'choice':
        known = [value for _, value in entry['choices']]
        return known.index(held) if held in known else 0
    if kind == 'hex':
        return hex_to_rgb(held)
    if kind == 'float':
        return float(held) * entry['scale']
    if kind == 'int':
        return int(held)
    if kind == 'bool':
        return bool(held)
    return str(held)


def put(stored, entry, value):
    """Set a field in a scene's stored settings from what its control gives."""
    kind, path = entry['kind'], entry['path']
    if kind == 'member':
        held = list(complete(stored)[path[0]])
        if value and entry['member'] not in held:
            held.append(entry['member'])
        elif not value and entry['member'] in held:
            held.remove(entry['member'])
        stored[path[0]] = held
        return
    if kind == 'choice':
        if not 0 <= int(value) < len(entry['choices']):
            raise ValueError('Invalid choice')
        value = entry['choices'][int(value)][1]
    elif kind == 'hex':
        value = rgb_to_hex(value)
    elif kind == 'float':
        value = min(entry['high'], max(entry['low'], float(value))) / entry['scale']
    elif kind == 'int':
        value = min(entry['high'], max(entry['low'], int(value)))
    elif kind == 'bool':
        value = bool(value)
    else:
        value = str(value).strip()
    if len(path) == 1:
        stored[path[0]] = value
        return
    if path in (('denoising', 'smart'), ('denoising', 'safe')):
        from .denoising import one_or_other
        held = dict(stored.get('denoising') or {})
        held[path[1]] = value
        stored['denoising'] = one_or_other(held, path[1])
        return
    # The parts of a group are kept together, so start from all of them.
    group = complete(stored)[path[0]]
    group = list(group) if isinstance(group, list) else dict(group)
    group[path[1]] = value
    if path[0] == 'render':
        group = options.render_values(group)
    stored[path[0]] = group
    if path[0] == 'display':
        # Kept for the scenes to come, and for the next time Modo is opened.
        from . import display_memory
        display_memory.remember(path[1], value)
