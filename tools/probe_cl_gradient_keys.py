# python
"""Command-line: setting a Gradient layer's keys from a script, for measuring its inputs: an identity ramp (the colour at
input x is x, from -100 to 100) by channel.key on each colour channel, read back through the evaluated gradient.
Writes test-results/gradient-keys/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gradient-keys')
out.mkdir(parents=True, exist_ok=True)
result = {'tries': {}}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    material = next(i for i in scene.items('advancedMaterial'))
    scene.select(material)
    lx.eval('shader.create gradient')
    gradient = next(i for i in scene.items('gradient'))
    gradient.channel('effect').set('lumiColor')
    gradient.channel('param').set('cameraDistance')
    for axis in 'RGB':
        for x in (-100.0, 0.0, 100.0):
            name = 'color.' + axis
            for form in ('channel.key time:%g value:%g channel:{%s:%s}' % (x, x, gradient.id, name),):
                try:
                    lx.eval(form)
                    result['tries'].setdefault(name, []).append('ok %g' % x)
                except Exception as exc:
                    result['tries'].setdefault(name, []).append('%g: %s' % (x, exc))
    value = gradient.channel('color.R').get()
    filt = lx.object.GradientFilter(value)
    result['read'] = {str(x): filt.Generate(x) for x in (-5.0, 0.0, 0.5, 1.0, 3.0, 9.5, 50.0)}
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
