# python
"""Isolated GUI test: an imported MoonRay scene with motion blur becomes keyed Modo animation.

The plan of test-results/rdl-motion/moving.rdla (a box, a light and the camera moving over a shutter of -0.25 to 0.25
frames, planned outside Modo into plan.json) is applied. Each moving item's position is read at the shutter's two
ends, the render camera's shutter and the Motion Blur render setting are read, and the scene is captured as the plugin
captures it for a render with motion blur, to see the box's place at shutter close."""
import json
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/rdl-motion'
result = {}

try:
    from moonray_modo import animation, properties, rdl_import
    lx.eval('scene.new')
    scene = modo.Scene()
    data = json.loads((out / 'plan.json').read_text())
    result['import'] = rdl_import.apply(data)
    now, fps = lx.service.Selection().GetTime(), float(scene.fps)
    for name in ('box', 'key', 'camera'):
        item = next(i for i in scene.items() if i.name == name)
        locator = item if hasattr(item, 'position') else modo.LocatorSuperType(item)
        result[name] = {'open': [round(locator.position.x.get(time=now - 0.25 / fps), 4), round(locator.position.y.get(time=now - 0.25 / fps), 4)],
                        'close': [round(locator.position.x.get(time=now + 0.25 / fps), 4), round(locator.position.y.get(time=now + 0.25 / fps), 4)]}
    camera = scene.renderCamera
    result['render_camera'] = {'name': camera.name, 'blurLen': camera.channel('blurLen').get(), 'blurOff': camera.channel('blurOff').get()}
    result['final_motion'] = properties.scene_settings().get('final_motion')
    snapshot = animation.capture_current(False)
    box = next(m for m in snapshot['meshes'] if m.get('name', '').startswith('box') or 'box' in str(m.get('identity', '')))
    result['captured'] = {'motion_steps': snapshot.get('motion_steps'), 'box_open': box.get('matrix', [None] * 16)[12],
                          'box_close': (box.get('matrix_close') or [None] * 16)[12]}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
