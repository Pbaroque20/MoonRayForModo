# python
"""Command-line test: every texture effect Modo has (its textureEffect servers, with their user names), beside the
ones the plugin translates (textures.EFFECTS and EFFECT_ALIASES), to find what a Shader Tree layer can drive that the
plugin leaves out."""
import json
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\texture-effects')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    host = lx.service.Host()
    guid = lx.symbol.u_TEXTUREEFFECT
    found = []
    for index in range(host.NumServers(guid)):
        factory = host.ServerByIndex(guid, index)
        name = factory.Name()
        try:
            user = factory.InfoTag(lx.symbol.sSRV_USERNAME)
        except Exception:
            user = ''
        found.append([name, user])
    result['modo'] = sorted(found)
    from moonray_modo import textures
    result['plugin'] = sorted(textures.EFFECTS)
    result['aliases'] = dict(getattr(textures, 'EFFECT_ALIASES', {}))
    known = set(textures.EFFECTS) | set(getattr(textures, 'EFFECT_ALIASES', {}))
    result['missing'] = sorted([name, user] for name, user in found if name not in known)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1))
