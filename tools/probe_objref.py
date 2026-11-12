# python
"""GUI: which value type Modo's Python makes an object reference from (for handing a scene from native code)."""
import json
import pathlib
import traceback
import lx

result = {}
for name in ('objref', getattr(lx.symbol, 'sTYPE_OBJREF', 'objref'), 'objectref', '&item'):
    try:
        value = lx.service.Value().CreateValue(name)
        entry = {'repr': repr(value), 'type': value.Type() if hasattr(value, 'Type') else None, 'dir': [m for m in dir(value) if not m.startswith('__')]}
        try:
            entry['ref'] = repr(lx.object.ValueReference(value))
        except Exception as exc:
            entry['ref'] = 'raised ' + str(exc)
        result[name] = entry
    except Exception:
        result[name] = traceback.format_exc()[-300:]
result['symbols'] = [s for s in dir(lx.symbol) if 'OBJREF' in s or 'REFERENCE' in s.upper()][:20]
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\objref.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
