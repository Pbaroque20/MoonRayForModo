# python
"""GUI: Modo's render cache as the kit reads it, for a Scene Proxy (test-results/references/proxy.lxo from
tools/probe_proxy.py, and referencing.lxo from tools/probe_references.py): each surface's item, material tag, matrix,
visibility and shader layers, and whether the main scene knows those layers. Writes test-results/references/cache.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {}


def save():
    (out / 'cache.json').write_text(json.dumps(result, indent=1, default=str))


def read(name):
    lx.eval('!scene.open {%s} normal' % (out / name))
    from moonray_modo import evaluated
    data = evaluated.capture(0.0)
    scene = modo.Scene()
    surfaces = []
    for surface in data['surfaces']:
        held = {k: v for k, v in surface.items() if k not in ('matrix_close',)}
        known = {}
        for layer in surface['layers']:
            try:
                known[layer] = scene.item(layer).type
            except Exception as exc:
                known[layer] = 'unknown: ' + str(exc)[:60]
        held['layers_known'] = known
        surfaces.append(held)
    prototypes = {key: {k: (v if k != 'segments' else [(len(s.get('vertices') or []), len(s.get('faces') or [])) for s in v])
                        for k, v in proto.items() if k not in ('features',)} for key, proto in data['prototypes'].items()}
    return {'surfaces': surfaces, 'prototypes': prototypes}


for name in ('proxy.lxo', 'referencing.lxo'):
    try:
        result[name] = read(name)
    except Exception:
        result[name] = {'error': traceback.format_exc()}
    save()
lx.eval('!app.quit')
