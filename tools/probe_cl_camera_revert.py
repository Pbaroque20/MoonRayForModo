# python
"""Command-line test: Change to Modo Camera. The render camera is moved, converted to a MoonRay perspective camera and
given an 85 mm lens and depth of field, then changed back: it should be a plain Modo camera again (no MoonRay
package), the same item in the same place, with an 85 mm focal length and the depth of field, and each right-click
entry enabled only where it applies."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\camera-revert')
out.mkdir(parents=True, exist_ok=True)
result = {}


def enabled(name):
    try:
        spawned = lx.object.Command(lx.service.Command().Spawn(lx.symbol.iCTAG_NULL, name))
        spawned.Enable(lx.service.Message().Allocate())
        return True
    except Exception:
        return False


try:
    from moonray_modo import entities
    scene = modo.Scene()
    camera = scene.renderCamera
    camera.position.set((1.0, 2.0, 3.0))
    lx.eval('select.item {%s} set' % camera.id)
    result['modo camera'] = {'convert': enabled('moonray.camera.convert'), 'revert': enabled('moonray.camera.revert')}
    lx.eval('moonray.camera.convert 0')
    camera = scene.item(camera.id)
    camera.channel(entities.CHANNEL_PREFIX + 'focal').set(85.0)
    camera.channel(entities.CHANNEL_PREFIX + 'dof').set(True)
    camera.channel(entities.CHANNEL_PREFIX + 'dof_focus_distance').set(7.5)
    result['converted'] = {'class': entities.class_of(camera), 'convert': enabled('moonray.camera.convert'), 'revert': enabled('moonray.camera.revert')}
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('moonray.camera.revert')
    camera = scene.item(camera.id)
    result['changed back'] = {'class': entities.class_of(camera), 'type': camera.type, 'same item': camera.id == scene.renderCamera.id,
                              'position': list(camera.position.get()), 'focalLen': camera.channel('focalLen').get(),
                              'dof': camera.channel('dof').get(), 'focusDist': camera.channel('focusDist').get(),
                              'convert': enabled('moonray.camera.convert'), 'revert': enabled('moonray.camera.revert')}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
