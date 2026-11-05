# python
"""Command line: why moonray.entity.volumeFile fails. A dwVdbVolume made and selected, the command run with a file, and
its steps done one by one here to find the one that throws. Writes test-results/vdb-volume-file/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\vdb-volume-file')
out.mkdir(parents=True, exist_ok=True)
VDB = r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\vdb\ball.vdb'
result = {}


def attempt(name, fn):
    try:
        result[name] = fn()
    except Exception:
        result[name] = 'error: ' + traceback.format_exc()[-1500:]


try:
    from moonray_modo import entities
    scene = modo.Scene()
    volume = entities.make_item(scene, 'VdbVolume', 'Probe Volume')
    lx.eval('select.item {%s} set' % volume.id)
    attempt('selected_classes', lambda: [entities.class_of(i) for i in scene.selected])
    attempt('command', lambda: [lx.eval('moonray.entity.volumeFile {%s}' % VDB), 'ok'][-1])
    prefix = entities.CHANNEL_PREFIX
    def steps():
        done = []
        shape = entities.make_item(scene, 'VdbGeometry', 'VDB ball');done.append('made')
        for key, value in entities.starting('VdbGeometry').items():
            try:shape.channel(prefix + key).set(value)
            except Exception as exc:done.append('starting %s: %s' % (key, exc))
        shape.channel(prefix + 'modo_volume').set(volume.name);done.append('volume set')
        shape.channel(prefix + 'model').set(VDB.replace('\\', '/'));done.append('model set')
        grids = entities.vdb_grids(VDB);done.append(['grids', grids])
        return done
    attempt('steps', steps)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
