# python
"""Command-line: Modo's texture effects, which a Gradient's Input Parameter chooses among: each one's internal name and
the menu category it sits in, from the shader service. Writes test-results/texture-effects/report.json."""
import json
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\texture-effects')
out.mkdir(parents=True, exist_ok=True)
result = {'effects': []}
try:
    service = lx.service.Shader()
    names = [n for n in dir(service) if 'Effect' in n or 'TexEff' in n or 'Category' in n]
    result['service_methods'] = names
    count = service.TextureEffectCount() if hasattr(service, 'TextureEffectCount') else None
    result['count'] = count
    if count:
        for i in range(count):
            entry = {'index': i}
            try:
                effect = service.TextureEffectByIndex(i)
                entry['object'] = str(type(effect))
                for getter in ('Name', 'Category', 'Type', 'TypeName'):
                    try:
                        obj = lx.object.TextureEffect(effect)
                        entry[getter] = getattr(obj, getter)()
                    except Exception as exc:
                        entry[getter + '_error'] = str(exc)[:80]
            except Exception as exc:
                entry['error'] = str(exc)[:120]
            result['effects'].append(entry)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
