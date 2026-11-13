# python
"""Command line: what an item of a closed scene answers. A material in scene A; scene B opened beside it; A closed. The
material's id, name and scene asked before and after, each answer or the error it raises. Writes
test-results/closed-item/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\closed-item')
out.mkdir(parents=True, exist_ok=True)
report = {}


def ask(item, label):
    answers = {}
    for name, call in (('id', lambda: item.id), ('name', lambda: item.name), ('Ident', lambda: lx.object.Item(item).Ident()),
                       ('Context', lambda: lx.object.Scene(lx.object.Item(item).Context()).Filename()),
                       ('in current scene', lambda: modo.Scene().item(item.id).id),
                       ('test', lambda: lx.object.Item(item).test())):
        try:
            answers[name] = call()
        except Exception as exc:
            answers[name] = 'raised %s: %s' % (type(exc).__name__, exc)
    report[label] = answers


try:
    lx.eval('scene.new')
    material = modo.Scene().addMaterial(name='In scene A')
    first = lx.object.Scene(lx.object.Item(material).Context())
    ask(material, 'before')
    lx.eval('scene.new')
    ask(material, 'another scene current')
    lx.eval('scene.set {%s}' % first.Ident() if hasattr(first, 'Ident') else 'scene.set 0')
    lx.eval('!scene.close')
    ask(material, 'after its scene closed')
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
