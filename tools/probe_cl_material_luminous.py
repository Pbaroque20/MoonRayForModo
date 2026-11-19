# python
"""Command line: every material's Luminous Color and Luminous Intensity (radiance) in a scene, and its effect: two
materials blended by a mask where one has a white colour at no intensity and the other a black colour at full
intensity glow part-way in a channel-by-channel blend. MOONRAY_PROBE_SCENE: the scene (the tyre with its Group Mask at
Normal by default). Written beside it as luminous.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

scene_path = pathlib.Path(os.environ.get('MOONRAY_PROBE_SCENE', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-as-saved-normal\tyre_group_mask.lxo'))
report = {}
try:
    lx.eval('scene.open {%s} normal' % scene_path)
    for material in modo.Scene().items('advancedMaterial'):
        values = {}
        for name in ('effect', 'lumiCol.R', 'lumiCol.G', 'lumiCol.B', 'radiance', 'lumiAmt'):
            try:
                channel = material.channel(name)
                values[name] = channel.get() if channel is not None else None
            except Exception as exc:
                values[name] = 'error %s' % exc
        report[material.name] = values
except Exception:
    report['error'] = traceback.format_exc()
(pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results') / 'luminous.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
