# python
"""Isolated GUI test: the render camera converted into MoonRay camera items.

The render camera is given a lens, a film offset, depth of field and a place. It is converted into a perspective and
an orthographic MoonRay camera through moonray.camera.convert; each new item's world matrix and MoonRay settings are
written down beside what the plugin reads from the Modo camera when it renders through it (host.snapshot)."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-convert'
out.mkdir(parents=True, exist_ok=True)
result = {}

try:
    from moonray_modo import entities, host
    scene = modo.Scene()
    camera = scene.renderCamera
    placed = modo.LocatorSuperType(camera)
    placed.position.set((1.0, 2.0, 6.0))
    placed.rotation.set((-0.2, 0.3, 0.0))
    for name, value in (('focalLen', 0.035), ('offsetX', 0.002), ('dof', True), ('fStop', 2.8), ('focusDist', 3.5), ('irisBlades', 6)):
        camera.channel(name).set(value)
    snapshot = host.snapshot()
    result['modo_camera'] = {k: snapshot['camera'][k] for k in ('matrix', 'focal_mm', 'film_mm', 'film_offset', 'f_stop', 'focus_distance', 'iris_blades')}
    result['enabled'] = lx.eval('query commandservice moonray.camera.convert ?') if False else None
    made = {}
    for index, kind in ((0, 'PerspectiveCamera'), (1, 'OrthographicCamera')):
        scene.select(camera)
        lx.eval('moonray.camera.convert %d' % index)
        item = next(i for i in scene.selected)
        values = {}
        for key in ('focal', 'film_width_aperture', 'horizontal_film_offset', 'vertical_film_offset', 'dof', 'dof_aperture',
                    'dof_focus_distance', 'bokeh', 'bokeh_sides', 'modo_render_camera'):
            try:
                values[key] = item.channel(entities.CHANNEL_PREFIX + key).get()
            except Exception:
                pass
        made[kind] = {'name': item.name, 'type': item.type, 'matrix': host.world_matrix(item), 'values': values}
    result['made'] = made
    result['render_camera_unchanged'] = scene.renderCamera.id == camera.id
    result['same_place'] = {kind: max(abs(a - b) for a, b in zip(entry['matrix'], result['modo_camera']['matrix'])) for kind, entry in made.items()}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
