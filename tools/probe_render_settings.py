# python
"""Isolated GUI test: the render settings and one-click outputs added from MoonRay's documentation work from the
Render item's form.

Each kind of control is read as it starts, set, and read back: a number, a tick box, a popup and an output's tick box.
What the scene then holds, and the lines the scene written for MoonRay has for them, are written down."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/render-settings'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    from moonray_modo import host, properties, rdla, scene_settings
    form = (root / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
    changes = (('max_volume_depth', 3), ('volume_quality', 0.8), ('enable_presence_shadows', 1), ('pixel_filter', 0), ('sample_clamping_value', 5.0),
               ('lock_frame_noise', 1), ('aov_albedo', 1), ('aov_indirect_diffuse', 1), ('aov_motion_vectors', 1))
    result['in_the_form'] = {key: ('moonray.render.%s ?' % key) in form for key, _ in changes}
    result['before'] = {key: lx.eval('moonray.render.%s ?' % key) for key, _ in changes}
    for key, value in changes:
        lx.eval('moonray.render.%s %s' % (key, value))
    result['after'] = {key: lx.eval('moonray.render.%s ?' % key) for key, _ in changes}
    stored = scene_settings.complete(properties.scene_settings())
    result['stored'] = {key: stored['render'].get(key) for key, _ in changes if key in stored['render']}
    result['aovs'] = stored['aovs']
    taken = host.snapshot(refresh_materials=True)
    # As the preview window does before it writes the scene.
    taken['render_settings'], taken['aovs'] = stored['render'], stored['aovs']
    text = rdla.scene_text(taken, 160, 90, 2, 0.5, str(out / 'check.exr'))
    result['written'] = [line.strip() for line in text.splitlines() if any(('"%s"' % key) in line for key, _ in changes)]
    result['outputs_written'] = [key for key in ('albedo', 'indirect_diffuse', 'motion_vectors') if ('"%s"' % key) in text]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
