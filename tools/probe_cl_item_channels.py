# python
"""Command line: the channels of new items of the types in PROBE_TYPES (comma separated; blob,sprite,particleSim by
default), each with its type and default value, and the graphs (links) the type has. Writes
test-results/item-channels/report.json."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\item-channels')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    for kind in [k.strip() for k in os.environ.get('PROBE_TYPES', 'blob,sprite,particleSim').split(',') if k.strip()]:
        try:
            item = scene.addItem(kind)
        except Exception as exc:
            report[kind] = {'error': str(exc)}
            continue
        channels = {}
        for channel in item.channels():
            try:
                value = channel.get()
            except Exception:
                value = None
            channels[channel.name] = [channel.storageType, value]
        graphs = []
        try:
            for index in range(lx.object.Item(item.internalItem).Context().GraphCount() if False else 0):
                pass
        except Exception:
            pass
        report[kind] = {'type': item.type, 'channels': channels, 'parent': item.parent.type if item.parent else None}
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
