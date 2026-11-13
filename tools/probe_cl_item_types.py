# python
"""Command line: Modo's item types whose names hold PROBE_WORDS (comma separated; blob,particle,point,sprite,metaball by
default), with their supertypes, and Modo's commands with those words. Writes test-results/item-types/report.json."""
import json
import os
import pathlib
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\item-types')
out.mkdir(parents=True, exist_ok=True)
words = [w.strip().lower() for w in os.environ.get('PROBE_WORDS', 'blob,particle,point,sprite,metaball,voxel,surfgen').split(',') if w.strip()]
report = {'types': {}, 'commands': []}
try:
    scene_service = lx.service.Scene()
    for index in range(scene_service.ItemTypeCount()):
        code = scene_service.ItemTypeByIndex(index)
        name = scene_service.ItemTypeName(code)
        if any(w in name.lower() for w in words):
            try:
                parent = scene_service.ItemTypeName(scene_service.ItemTypeSuper(code))
            except Exception:
                parent = None
            report['types'][name] = parent
    command_service = lx.service.Command()
    for index in range(command_service.CommandCount()):
        try:
            name = command_service.CommandByIndex(index).Name()
        except Exception:
            continue
        if any(w in name.lower() for w in words):
            report['commands'].append(name)
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
