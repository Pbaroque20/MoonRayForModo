# python
"""GUI: whether Modo's Python can wrap an object pointer handed to it by native code (for the scene a Scene Proxy loads,
which only native code reaches). Writes test-results/references/lx_wrap.json."""
import json
import pathlib
import traceback
import lx
import lxu
import lxu.object

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references')
result = {}
for name, call in (('lx', lambda: [m for m in dir(lx) if not m.startswith('__')]),
                   ('lxu', lambda: [m for m in dir(lxu) if not m.startswith('__')]),
                   ('lxu_object', lambda: [m for m in dir(lxu.object) if not m.startswith('__')][:80]),
                   ('unknown', lambda: [m for m in dir(lx.object.Unknown) if not m.startswith('__')]),
                   ('item_doc', lambda: lx.object.Item.__doc__),
                   ('item_init_doc', lambda: lx.object.Item.__init__.__doc__),
                   ('dunder_item', lambda: [m for m in dir(lx.object.Item) if m.startswith('__')]),
                   ('dunder_unknown', lambda: [m for m in dir(lx.object.Unknown) if m.startswith('__')]),
                   ('dunder_lx', lambda: [m for m in dir(lx) if m.startswith('__')]),
                   ('bless_doc', lambda: lx.bless.__doc__),
                   ('ifc_doc', lambda: (lx.ifc.__doc__, lx.testifc.__doc__, lx.extract.__doc__)),
                   ('from_int', lambda: repr(lx.object.Unknown(0))),
                   ('scene_from_int', lambda: repr(lx.object.Scene(1)))):
    try:
        result[name] = call()
    except Exception:
        result[name] = traceback.format_exc()[-400:]
(out / 'lx_wrap.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
