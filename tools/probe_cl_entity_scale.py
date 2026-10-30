# python
"""Command-line test: a MoonRay RectLight's scale put into its Width and Height (moonray.entity.applyScale), its world
size unchanged, one undo step, and an undo that brings the scale back left alone. Writes
test-results/cl-export/prep/entity_scale.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\entity_scale.json')
result = {'steps': []}


def state(light, label):
    from moonray_modo.host import world_matrix
    m = world_matrix(light)
    axis = lambda v: round(sum(x * x for x in v) ** .5, 4)
    width, height = float(light.channel('mr_width').get()), float(light.channel('mr_height').get())
    result['steps'].append({'step': label, 'width': round(width, 4), 'height': round(height, 4),
                            'scale': [axis(m[0:3]), axis(m[4:7]), axis(m[8:11])],
                            'world_width': round(width * axis(m[0:3]), 4), 'world_height': round(height * axis(m[4:7]), 4)})


try:
    lx.eval('scene.new')
    light = modo.Scene().addItem('moonray.RectLight')
    light.channel('mr_width').set(0.5)
    light.channel('mr_height').set(0.25)
    lx.eval('select.item {%s} set' % light.id)
    state(light, 'made')
    lx.eval('transform.channel scl.X 2.0')
    lx.eval('transform.channel scl.Y 3.0')
    state(light, 'scaled 2 x 3')
    lx.eval('moonray.entity.applyScale')
    state(light, 'scale put into the size')
    lx.eval('app.undo')
    state(light, 'undone once')
    lx.eval('moonray.entity.applyScale')
    state(light, 'command again after the undo')
    lx.eval('app.undo')
    state(light, 'undone twice')
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1, default=str))
