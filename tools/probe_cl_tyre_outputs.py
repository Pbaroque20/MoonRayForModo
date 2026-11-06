# python
"""Command line: why Modo's render of the rebuilt tyre (test-results/tyre-group-mask/tyre_group_mask.lxo) has no
colour at all. Writes down the render outputs (effect, enable, filename), the Shader Tree's top level top first with
each item's type, effect, polygon tag and enable, the render passes (group items of pass type and their channels),
and the render item's channels that override shading. Writes test-results/tyre-group-mask/outputs.json."""
import json
import pathlib
import traceback
import lx
import modo

result = {}


def get(item, name):
    try:
        held = item.channel(name)
        return held.get() if held is not None else None
    except Exception as exc:
        return 'error %s' % exc


try:
    lx.eval('scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\tyre_group_mask.lxo')
    scene = modo.Scene()
    render = scene.renderItem
    result['top'] = [(c.name, c.type, get(c, 'effect'), get(c, 'ptag'), get(c, 'enable')) for c in reversed(list(render.children()))]
    result['outputs'] = [(o.name, get(o, 'effect'), get(o, 'enable'), get(o, 'filename'), get(o, 'colorspace')) for o in scene.items('renderOutput')]
    result['groups'] = [(g.name, get(g, 'type')) for g in scene.items('group')]
    result['render'] = {n: get(render, n) for n in ('globEnable', 'globIllum', 'ambColor.R', 'ambRad', 'renderType', 'clay', 'shadeOverride',
                                                  'aa', 'outputMode')}
    shaders = [(s.name, s.type, get(s, 'enable'), get(s, 'effect')) for s in scene.iterItems() if s.type in ('defaultShader', 'shaderOverride')]
    result['shaders'] = shaders
    materials = [m for m in scene.iterItems() if m.type == 'advancedMaterial' and m.name in ('Purple', 'M_Reifen_Laufflaeche', 'Material (2)')]
    result['materials'] = {m.name: {n: get(m, n) for n in ('enable', 'opacity', 'diffAmt', 'diffCol.R', 'diffCol.G', 'diffCol.B', 'blend')} for m in materials}
    result['passes'] = []
    for g in scene.items('group'):
        if get(g, 'type') == 'render':
            result['passes'].append((g.name, [c.name for c in g.groupChannels] if hasattr(g, 'groupChannels') else None,
                                     lx.eval('layer.active ? ') if False else None))
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-group-mask\outputs.json').write_text(json.dumps(result, indent=1, default=str))
