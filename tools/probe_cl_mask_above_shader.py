# python
"""Command-line test: a Shader Tree group moved above the Base Shader, where Modo applies it to nothing. The mask
reference scene (tools/make_mask_reference.py) is opened, its Part mask moved to the top of the Shader Tree, and the
scene exported (test-results/mask-reference/above_shader.rdla) with its notices."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mask-reference')
result = {}
try:
    lx.eval('scene.open {%s} normal' % (out / 'mask_reference.lxo'))
    scene = modo.Scene()
    render = scene.renderItem
    part = next(m for m in scene.items('mask', superType=False) if m.name == 'Part mask')
    lx.eval('texture.parent {%s} %d item:{%s}' % (render.id, len(render.children()), part.id))
    result['order'] = [item.name for item in render.children()]
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'above_shader.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'above_shader.json').write_text(json.dumps(result, indent=1, default=str))
