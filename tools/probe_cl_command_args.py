# python
"""Command line: the arguments of Modo's commands named in PROBE_COMMANDS (comma separated): each argument's name, type
and flags. Writes test-results/command-args/report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\command-args')
out.mkdir(parents=True, exist_ok=True)
report = {}
service = lx.service.Command()
for name in [n.strip() for n in os.environ.get('PROBE_COMMANDS', 'volume.particle,texture.particle,replicator.particle').split(',') if n.strip()]:
    try:
        command = service.Spawn(lx.symbol.iCTAG_NULL, name)
        attributes = lx.object.Attributes(command)
        args = []
        for index in range(attributes.Count()):
            try:
                kind = attributes.TypeName(index)
            except Exception:
                kind = None
            args.append({'name': attributes.Name(index), 'type': kind})
        report[name] = {'args': args}
        try:
            report[name]['usage'] = lx.eval('query commandservice command.usage ? {%s}' % name)
        except Exception as exc:
            report[name]['usage'] = str(exc)
    except Exception:
        report[name] = {'error': traceback.format_exc()[-300:]}
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
