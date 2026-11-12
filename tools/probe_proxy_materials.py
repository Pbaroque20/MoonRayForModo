# python
"""GUI: a Scene Proxy's shader layers reached through the adapter's MR_foreign_layers, and the proxy's scene through
them. Opens test-results/references/proxy.lxo; the adapter from PROBE_BRIDGE where given (a build not yet in the kit).
Writes test-results/references/proxy_materials.json."""
import ctypes
import json
import os
import pathlib
import traceback
import lx
import lxu.select
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {}


def save():
    (out / 'proxy_materials.json').write_text(json.dumps(result, indent=1, default=str))


try:
    lx.eval('!scene.open {%s} normal' % (out / 'proxy.lxo'))
    from moonray_modo import evaluated
    bridge = evaluated._load(os.environ.get('PROBE_BRIDGE') or None)
    call = bridge.MR_foreign_layers
    call.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_double, ctypes.c_int]
    call.restype = ctypes.c_char_p
    main = lx.object.Scene(lxu.select.SceneSelection().current())
    values = []
    for _ in range(4):
        value = lx.service.Value().CreateValue('&item')
        result.setdefault('made', []).append((repr(value), value.TypeName()))
        save()
        values.append(value)
    refs = [lx.object.ValueReference(v) for v in values]
    pointers = (ctypes.c_void_p * len(refs))(*[r.__peekobj__() for r in refs])
    save()
    answer = json.loads(call(main.__peekobj__(), pointers, len(refs), 0.0, 1).decode('utf-8'))
    result['answer'] = answer
    scenes = [lx.object.Scene(lx.object.Item(r.GetObject()).Context()) for r in refs[:answer['scenes']]]
    result['scenes'] = [s.Filename() for s in scenes]
    save()
    proxy_scene = modo.Scene(scenes[0])
    result['layers'] = [(i, proxy_scene.item(i).type, proxy_scene.item(i).name) for i in answer['surfaces'][0]['layers']]
    material = [i for i in proxy_scene.iterItems() if i.type == 'advancedMaterial' and 'RefRed' in i.name][0]
    result['material'] = (material.id, material.name, str(material.channel('diffCol').get()))
    result['render_item'] = proxy_scene.renderItem.id if proxy_scene.renderItem else None
    result['current_still'] = modo.Scene().scene.Filename()
    from moonray_modo.layers import ordered_items
    result['ordered'] = [(i.id, i.type) for i in ordered_items(proxy_scene.renderItem)]
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
