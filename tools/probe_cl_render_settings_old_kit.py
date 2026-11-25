# python
"""Command-line (modo_cl), run with a kit from before the render settings were channels: a scene saved with them
(test-results/render-settings-channels/saved-scene.lxo, from probe_cl_render_settings_channels.py) opens, and what the
older kit reads of its settings. Writes test-results/render-settings-channels/old-kit-report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\sweet-wilbur-4f4598\test-results\render-settings-channels')
report = {}
try:
    lx.eval('!scene.open {%s} normal' % (out / 'saved-scene.lxo'))
    from moonray_modo import properties, scene_settings
    report['kit_has_render_channels'] = hasattr(properties, 'read_render_channels')
    render = modo.Scene().renderItem
    internal = render.internalItem
    report['mr_channels_seen'] = len([internal.ChannelName(i) for i in range(internal.ChannelCount()) if internal.ChannelName(i).startswith('mr_')])
    held = scene_settings.complete(properties.scene_settings())
    report['samples'] = held['samples']
    report['sample_clamping_value'] = held['render']['sample_clamping_value']
    report['moonlightipr_sample_clamp'] = held['moonlightipr']['sample_clamp']
    report['denoiser'] = held['denoising']['engine']
    report['meshes'] = [m.name for m in modo.Scene().items('mesh')]
    lx.eval('moonray.render.samples 6')
    report['form_edit_samples'] = scene_settings.complete(properties.scene_settings())['samples']
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'old-kit-saved.lxo'))
    report['saved'] = True
except Exception:
    report['error'] = traceback.format_exc()
(out / 'old-kit-report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
