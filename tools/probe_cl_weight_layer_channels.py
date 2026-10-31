# python
"""Command-line check: what Modo's weight map texture layer is: the item types that sound like one, and the channels and
values of one made. Writes test-results/weight-layer/channels.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\weight-layer')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    service = lx.service.Scene()
    names = []
    for index in range(service.ItemTypeCount()):
        try:
            names.append(service.ItemTypeName(service.ItemTypeByIndex(index)))
        except Exception:
            pass
    report['types'] = sorted(n for n in names if any(w in n.lower() for w in ('vmap', 'weight', 'vertex')))
    lx.eval('scene.new')
    scene = modo.Scene()
    for kind in report['types']:
        try:
            item = scene.addItem(kind)
            channels = {}
            for name in item.channelNames:
                try:
                    channels[name] = str(item.channel(name).get())
                except Exception as error:
                    channels[name] = 'error: ' + str(error)[:40]
            report[kind] = {'supertype': lx.service.Scene().ItemTypeName(lx.service.Scene().ItemTypeSuper(lx.object.Item(item).Type())) if False else '', 'channels': channels}
        except Exception as error:
            report.setdefault('not_made', {})[kind] = str(error)[:100]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'channels.json').write_text(json.dumps(report, indent=1, default=str))
