# python
"""Command line: the arguments of Modo commands (PROBE_COMMANDS, comma-separated): each argument's name and type, and
the command's own help text where it has one. Writes test-results/command-args/report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\command-args')
out.mkdir(parents=True, exist_ok=True)
result = {}
for name in (os.environ.get('PROBE_COMMANDS') or '').split(','):
    if not name:
        continue
    try:
        command = lx.service.Command().Spawn(lx.symbol.iCTAG_NULL, name)
        attributes = lx.object.Attributes(command)
        args = []
        for index in range(attributes.Count()):
            entry = [attributes.Name(index)]
            try:
                entry.append(attributes.TypeName(index))
            except Exception:
                pass
            try:
                entry.append(lx.object.Command(command).ArgFlags(index))
            except Exception:
                pass
            args.append(entry)
        result[name] = args
    except Exception:
        result[name] = traceback.format_exc()[-300:]
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
