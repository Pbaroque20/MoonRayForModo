# python
"""Command-line (modo_cl): the render settings as channels of the Render item (moonray_modo/render_channels.py).

An old scene (the tag alone, as kits before wrote it) is saved first; then the Render item is given the channels
(moonray.render.toChannels, which a scene opened or made runs by itself in Modo's window), the form's commands and
item.channel each set a setting and the other side reads it, a setting is keyed and read at two frames, the scene is
saved, closed and opened again, the old scene is opened and moved, and the scene is exported as MoonRay renders it
(scene_export) to see the values in the scene text. Writes test-results/render-settings-channels/cl-report.json."""
import json
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\sweet-wilbur-4f4598\test-results\render-settings-channels')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'cl-report.json').write_text(json.dumps(report, indent=1, default=str))


def step(name, action):
    try:
        report[name] = action()
    except Exception:
        report[name] = {'error': traceback.format_exc()}
    save()


def settings():
    from moonray_modo import properties, scene_settings
    return scene_settings.complete(properties.scene_settings())


def channel(name):
    return modo.Scene().renderItem.channel(name).get()


def cube():
    scene = modo.Scene()
    mesh = scene.addMesh('Cube')
    with mesh.geometry as geo:
        c = [geo.vertices.new((a - .5, b - .5, d - .5)) for a in (0, 1) for b in (0, 1) for d in (0, 1)]
        for f in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in f])


def old_scene():
    """A scene as an older kit saved it: the tag, no channels."""
    from moonray_modo import properties
    lx.eval('scene.new')
    cube()
    render = modo.Scene().renderItem
    render.setTag(properties.TAG, json.dumps({'samples': 7, 'render': dict(__import__('moonray_modo.options', fromlist=['x']).render_values({}),
                                                                           max_depth=6, sample_clamping_value=2.5),
                                              'denoising': {'engine': 'optix'}, 'background': {'color': '#336699', 'mode': 'color'},
                                              'region_enabled': True, 'region': [0.1, 0.2, 0.9, 0.8], 'aovs': ['alpha', 'depth']}))
    path = out / 'old-scene.lxo'
    lx.eval('!scene.saveAs {%s} $LXOB false' % path)
    return {'has_channels': properties.has_render_channels(render), 'saved': str(path)}


def package():
    from moonray_modo import properties, render_channels
    render = modo.Scene().renderItem
    before = properties.has_render_channels(render)
    lx.eval('!moonray.render.toChannels')
    internal = render.internalItem
    names = [internal.ChannelName(i) for i in range(internal.ChannelCount())]
    ours = [n for n in names if n.startswith('mr_')]
    types = {}
    for n in ours:
        types[internal.ChannelType(internal.ChannelLookup(n))] = types.get(internal.ChannelType(internal.ChannelLookup(n)), 0) + 1
    return {'before': before, 'after': properties.has_render_channels(render), 'count': len(ours), 'expected': len(render_channels.entries()),
            'types': types, 'first': ours[:5], 'values': {n: channel(n) for n in ('mr_samples', 'mr_max_depth', 'mr_sample_clamping_value',
            'mr_denoiser', 'mr_background_color.R', 'mr_region_left', 'mr_aov_depth', 'mr_aov_alpha', 'mr_view', 'mr_lut')}}


def form_to_channel():
    lx.eval('moonray.render.samples 11')
    lx.eval('moonray.render.sample_clamping_value 4.25')
    lx.eval('moonray.render.denoiser 2')
    lx.eval('moonray.render.lut {C:/luts/look.cube}')
    lx.eval('moonray.render.background_color {0.5 0.25 1.0}')
    return {'mr_samples': channel('mr_samples'), 'mr_sample_clamping_value': channel('mr_sample_clamping_value'),
            'mr_denoiser': channel('mr_denoiser'), 'mr_lut': channel('mr_lut'),
            'color': [channel('mr_background_color.' + p) for p in 'RGB'],
            'tag_samples': json.loads(modo.Scene().renderItem.readTag('MRAY')).get('samples')}


def channel_to_form():
    render = modo.Scene().renderItem.id
    lx.eval('item.channel mr_samples 13 item:{%s}' % render)
    lx.eval('item.channel mr_moonlightipr_sample_clamp 1.5 item:{%s}' % render)
    lx.eval('item.channel mr_pixel_filter 2 item:{%s}' % render)
    lx.eval('item.channel mr_aov_albedo true item:{%s}' % render)
    lx.eval('item.channel mr_lut {} item:{%s}' % render)
    held = settings()
    queried = lx.eval('moonray.render.samples ?')
    return {'samples': held['samples'], 'moonlightipr_clamp': held['moonlightipr']['sample_clamp'], 'pixel_filter': held['render']['pixel_filter'],
            'albedo': 'albedo' in held['aovs'], 'lut': held['display']['lut'], 'form_query_samples': queried,
            'tag_samples_unchanged': json.loads(modo.Scene().renderItem.readTag('MRAY')).get('samples')}


def timing():
    from moonray_modo import properties
    started = time.perf_counter()
    for _ in range(200):
        properties.scene_settings()
    each = (time.perf_counter() - started) / 200
    started = time.perf_counter()
    for _ in range(50):
        lx.eval('moonray.render.max_depth ?')
    query = (time.perf_counter() - started) / 50
    started = time.perf_counter()
    for _ in range(200):
        properties.read_render_channels(modo.Scene().renderItem)
    reads = (time.perf_counter() - started) / 200
    started = time.perf_counter()
    for _ in range(200):
        properties.read(modo.Scene().renderItem)
    tag_only = (time.perf_counter() - started) / 200
    return {'tag_only_ms': tag_only * 1000, 'scene_settings_ms': each * 1000, 'form_query_ms': query * 1000, 'channel_reads_ms': reads * 1000}


def keyed():
    render = modo.Scene().renderItem
    fps = modo.Scene().fps
    render.channel('mr_max_depth').set(3, time=0.0, key=True)
    render.channel('mr_max_depth').set(9, time=10.0 / fps, key=True)
    selection = lx.service.Selection()
    selection.SetTime(0.0)
    first = settings()['render']['max_depth']
    selection.SetTime(10.0 / fps)
    last = settings()['render']['max_depth']
    selection.SetTime(5.0 / fps)
    middle = settings()['render']['max_depth']
    selection.SetTime(0.0)
    return {'frame0': first, 'frame10': last, 'frame5': middle}


def reopen():
    path = out / 'saved-scene.lxo'
    before = settings()
    lx.eval('!scene.saveAs {%s} $LXOB false' % path)
    lx.eval('!scene.close')
    lx.eval('!scene.open {%s} normal' % path)
    after = settings()
    from moonray_modo import properties
    return {'has_channels': properties.has_render_channels(modo.Scene().renderItem),
            'same': {k: (before[k] == after[k]) for k in ('samples', 'render', 'denoising', 'display', 'aovs', 'moonlightipr', 'background')},
            'samples': after['samples'], 'max_depth_keyed_frame0': after['render']['max_depth']}


def migrate():
    from moonray_modo import properties
    lx.eval('!scene.close')
    lx.eval('!scene.open {%s} normal' % (out / 'old-scene.lxo'))
    render = modo.Scene().renderItem
    before = settings()
    had = properties.has_render_channels(render)
    lx.eval('!moonray.render.toChannels')
    after = settings()
    return {'had_channels': had, 'has_channels': properties.has_render_channels(render),
            'unchanged': before == after, 'differences': {k: [before.get(k), after.get(k)] for k in set(before) | set(after) if before.get(k) != after.get(k)},
            'samples': channel('mr_samples'), 'max_depth': channel('mr_max_depth'),
            'clamp': channel('mr_sample_clamping_value'), 'denoiser': channel('mr_denoiser'),
            'color': [channel('mr_background_color.' + p) for p in 'RGB'], 'region_top': channel('mr_region_top'),
            'aov_depth': channel('mr_aov_depth'), 'view_left_default': channel('mr_view')}


def export():
    from moonray_modo import scene_export
    render = modo.Scene().renderItem.id
    lx.eval('item.channel mr_samples 5 item:{%s}' % render)
    lx.eval('item.channel mr_sample_clamping_value 7.75 item:{%s}' % render)
    lx.eval('item.channel mr_max_depth 4 item:{%s}' % render)
    warnings = []
    written = scene_export.export({'path': str(out / 'channels.rdla'), 'format': 'rdla', 'frames': False, 'outputs': True, 'collect': False}, warnings)
    text = pathlib.Path(written[0]).read_text(errors='replace') if written else ''
    found = [line.strip() for line in text.splitlines() if any(k in line for k in ('pixel_samples', 'sample_clamping_value', '"max_depth"', 'max_depth'))]
    return {'written': [str(p) for p in written], 'lines': found[:12], 'warnings': warnings[:5]}


step('old_scene', old_scene)
step('new_scene', lambda: (lx.eval('scene.new'), cube(), 'ok')[-1])
step('package', package)
step('form_to_channel', form_to_channel)
step('channel_to_form', channel_to_form)
step('timing', timing)
step('keyed', keyed)
step('reopen', reopen)
step('migrate', migrate)
step('export', export)
report['done'] = True
save()
lx.eval('!app.quit')
