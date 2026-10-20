# python
"""Command-line test: the mask reference scene (tools/make_mask_reference.py, run in the user's Modo) exported as the
plugin writes it (test-results/mask-reference/masks.rdla), with its notices, for tools/check_mask_reference.py."""
import json
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mask-reference')
result = {}
try:
    lx.eval('scene.open {%s} normal' % (out / 'mask_reference.lxo'))
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'masks.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'export.json').write_text(json.dumps(result, indent=1, default=str))
