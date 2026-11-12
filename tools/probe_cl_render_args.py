# python
"""Headless: the referencing scene's render items and frame ranges."""
import json, os, traceback, lx
out = {}
try:
    lx.eval(r'!scene.open {C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\referencing.lxo} normal')
    import modo
    scene = modo.Scene()
    out['render_items'] = [(i.id, i.name, i.channel('first').get(), i.channel('last').get()) for i in scene.items('polyRender')]
    out['renderItem'] = scene.renderItem.id
    out['time_range'] = [lx.eval('time.range scene in:?'), lx.eval('time.range scene out:?')]
except Exception:
    out['error'] = traceback.format_exc()
open(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\render_args.json', 'w').write(json.dumps(out, indent=1, default=str))
