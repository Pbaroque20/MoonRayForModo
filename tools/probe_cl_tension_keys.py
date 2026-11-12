# python
"""Command-line: how the kit can read where a Tension Texture's gradient keys lie (its input span): the default keys,
then keys set at -2, 0.5 and 3; through the channel's envelope and GradientFilter. Writes test-results/tension/keys.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tension')
report = {}


def read(layer, label):
    held = {}
    for name in ('color.R', 'value'):
        entry = held[name] = {}
        channel = layer.channel(name)
        try:
            envelope = channel.envelope
            kf = envelope.keyframes; entry['keys'] = [repr(kf)] + [repr(k) for k in list(kf)[:6]]; entry['count'] = getattr(kf, 'numKeys', None); entry['times'] = [(kf.setIndex(i) or True) and (kf.time, kf.value) for i in range(kf.numKeys)] if hasattr(kf, 'numKeys') else None
        except Exception as exc:
            entry['keys'] = 'no: %s' % exc
        try:
            gf = lx.object.GradientFilter(channel.get())
            entry['filter_methods'] = [m for m in dir(gf) if not m.startswith('_')]
            entry['samples'] = [(x, gf.Generate(x)) for x in (-5, -2, -1, 0, .5, 1, 2, 3, 5)]
        except Exception as exc:
            entry['filter'] = str(exc)
    report[label] = held


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    scene.select(next(i for i in scene.items('advancedMaterial')))
    lx.eval('shader.create tensionTexture')
    layer = next(i for i in scene.items('tensionTexture'))
    read(layer, 'default')
    for x, v in ((-2, .1), (.5, .6), (3, .9)):
        lx.eval('channel.key time:%g value:%g channel:{%s:color.R}' % (x, v, layer.id))
    read(layer, 'keyed')
except Exception:
    report['error'] = traceback.format_exc()
(out / 'keys.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
