# python
"""Command line: the tread's own Shader Tree rows in the tyre Group Mask scene (tools/probe_cl_tyre_group_mask.py),
top first: each material's colour, amounts and effect, each image layer's effect, blend and opacity, and the Purple
Group's. Written to test-results/tyre-group-mask/tread.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask')
CHANNELS = ('enable', 'effect', 'blend', 'opacity', 'invert', 'diffCol.R', 'diffCol.G', 'diffCol.B', 'diffAmt', 'specAmt', 'rough',
            'reflAmt', 'subsAmt', 'coatAmt', 'metallic', 'lumiCol.R', 'radiance', 'tranAmt', 'bumpAmp', 'ptag', 'ptyp')
report = {}
try:
    lx.eval('scene.open {%s} normal' % str(out / 'tyre_group_mask.lxo'))
    scene = modo.Scene()
    tread = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Reifen_Laufflaeche')

    def rows(item, depth):
        held = []
        for child in reversed(list(item.children())):
            values = {}
            for name in CHANNELS:
                try:
                    channel = child.channel(name)
                    if channel is not None:
                        values[name] = channel.get()
                except Exception:
                    pass
            held.append({'depth': depth, 'name': child.name, 'type': child.type, 'channels': values})
            held += rows(child, depth + 1)
        return held
    report['tread_top_first'] = rows(tread, 0)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'tread.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')
