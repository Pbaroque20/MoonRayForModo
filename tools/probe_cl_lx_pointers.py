# python
"""Headless: an &item value made in Python, set from Python with an item of the main scene (SetObject), read back and
released, under the debug heap: whether such references work at all."""
import gc, json, traceback, lx
out = {'steps': []}
path = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\lx_pointers.json'
def step(text):
    out['steps'].append(text); open(path, 'w').write(json.dumps(out, indent=1, default=str))
try:
    lx.eval(r'!scene.open {C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\proxy2-test.lxo} normal')
    import modo
    scene = modo.Scene()
    item = scene.items('proxy', superType=False)[0]
    for attempt in range(3):
        ref = lx.object.ValueReference(lx.service.Value().CreateValue('&item'))
        step('made, set %s' % ref.IsSet())
        ref.SetObject(lx.object.Item(item))
        step('set')
        back = lx.object.Item(ref.GetObject())
        step('back %s' % back.Ident())
        del back, ref
        gc.collect()
        step('released %d' % attempt)
except Exception:
    out['error'] = traceback.format_exc()
step('done')
