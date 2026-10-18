"""A scene read out of Modo made ready to render with the scene's MoonRay settings: its render settings, outputs,
display, environment and light multipliers and surfaces. Shared by the preview window and Export as MoonRay Scene,
which needs no preview window open."""


def values():
    """The scene's MoonRay settings, complete, as the preview window reads them (the beauty as the buffer shown)."""
    from . import properties, scene_settings
    try:
        from . import modo_color
        modo_color.refresh()
    except Exception:
        pass
    try:
        stored = properties.scene_settings()
    except Exception:
        stored = {}
    held = scene_settings.complete(stored)
    held['preview_buffer'] = 'beauty'
    return held


def configure(scene, values):
    scene['render_settings'] = values['render']
    scene['scene_variables'] = values['scene_variables']
    # The compositor's graph goes with the scene so that a render to a file can write its composite beside it.
    scene['compositor'] = values['compositor']
    scene['aovs'] = values['aovs']
    scene['production']=values['production']
    scene['asset_settings']=values['asset_settings']
    from .extra_geometry import attach as attach_geometry
    attach_geometry(scene,values['production'])
    scene['custom_aovs']=values['custom_aovs']
    scene['recovery']=values['recovery']
    # Kept out of a scene that does not ask for it, so that a checkpoint saved before still matches.
    if values['deep']['enabled']:scene['deep']=values['deep']
    # Likewise the EXR's compression, where it is not MoonRay's zip.
    if values['exr']!={'compression':1,'dwa_level':85.0}:scene['exr']=values['exr']
    scene['preview_buffer'] = values['preview_buffer']
    scene['execution_mode'] = values['execution_mode']
    scene['denoising'] = values['denoising']
    from .display import values as display_values
    scene['display'] = display_values(dict(values['display'],working_space=values['asset_settings'].get('working_space','rec709')))
    if scene['display']['working_space']=='acescg':
        if scene['display']['view']=='ocio' and scene['display']['source']=='Linear Rec.709 (sRGB)':scene['display']['source']='ACEScg'
        scene['warnings'].append('ACEScg color boundaries are enabled. Native spectral presets and volume color grids must be authored for this working space; color parity is not yet validated.')
    if values['region_enabled']:
        scene['region'] = values['region']
    if not values['modo_environment']:
        scene['environments']=[]
    for environment in scene.get('environments',[]):
        environment['intensity'] *= values['environment_multiplier']
    from .background import apply as apply_background
    apply_background(scene,values['background'])
    for light in scene['lights']:
        light['intensity'] *= values['light_multiplier']
    for mesh in scene['meshes']:
        if mesh.get('object_override'):
            continue
        # Dormant UI settings must not change the rendered-scene digest.
        if 'geometry_settings' in mesh:mesh['geometry_settings']={'override':False}
        if values['surface'] == 1:
            mesh['subdivision'] = True
        mesh['subdivision_level'] = values['subdivision_level']
    if values['surface'] == 1:
        scene['warnings'].append('Smooth subdivision rounds all exported meshes, including sharp edges.')
    # A mesh light with no mesh, or a name several meshes share, lights nothing in either engine: say so.
    from . import entities
    entities.mesh_lights(scene,scene['warnings'])
    return scene
