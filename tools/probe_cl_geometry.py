# python
"""Command-line test: evaluated geometry handed over as numbers gives the same as handed over as text, on shapes other
than plain meshes, and a Shader's visibility switches reach the plugin.

A scene is made with a ball, two instances of it placed apart, and a cube with subdivision on. It is read both ways and
the two readings compared. The scene's Shader is then told not to be seen by the camera and to cast no shadow, and what
visibility each surface comes back with is written down."""
import json
import pathlib
import time
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cl-geometry'
out.mkdir(parents=True, exist_ok=True)
result = {}


def same(a, b, path=''):
    if isinstance(a, dict) and isinstance(b, dict):
        for key in set(a) | set(b):
            if key in ('timing', 'handing', 'mode', 'skip'):
                continue
            if key not in a or key not in b:
                return path + '/' + str(key) + ' missing'
            found = same(a[key], b[key], path + '/' + str(key))
            if found is not True:
                return found
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return '%s lengths %d and %d' % (path, len(a), len(b))
        for index, (x, y) in enumerate(zip(a, b)):
            if isinstance(x, (list, dict)):
                found = same(x, y, path + '[%d]' % index)
            else:
                found = True if x == y or (isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) <= 1e-6 * max(1.0, abs(x), abs(y))) else '%s[%d] %r and %r' % (path, index, x, y)
            if found is not True:
                return found
        return True
    return True if a == b else '%s %r and %r' % (path, a, b)


try:
    from moonray_modo import evaluated
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('item.name {ball} mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    ball = next(m for m in modo.Scene().items('mesh') if m.name == 'ball')
    for x in (1.5, -1.5):
        lx.eval('select.item {%s} set' % ball.id)
        lx.eval('item.duplicate instance:true type:locator')
        lx.eval('transform.channel pos.X %s' % x)
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('item.name {cube} mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    try:
        lx.eval('select.typeFrom polygon')
        lx.eval('select.all')
        lx.eval('poly.convert face psubdiv true')
        result['subdivision'] = True
    except Exception as exc:
        result['subdivision'] = 'not set: ' + str(exc)[:80]
    lx.eval('select.typeFrom item')
    now = lx.service.Selection().GetTime()
    t = time.perf_counter(); fast = evaluated.capture(now); result['as_numbers_seconds'] = round(time.perf_counter() - t, 3)
    bridge = evaluated._bridge

    class Text:
        MR_geometry_snapshot_file = bridge.MR_geometry_snapshot_file
    evaluated._bridge = Text()
    t = time.perf_counter(); slow = evaluated.capture(now); result['as_text_seconds'] = round(time.perf_counter() - t, 3)
    evaluated._bridge = bridge
    result['same'] = same(fast, slow)
    result['surfaces'] = [[s['source_item'], s.get('instanced'), s.get('instance_index')] for s in fast['surfaces']]
    result['prototypes'] = {key: [[len(seg['vertices']), len(seg['faces']), len(seg['normals']), len(seg['uv_sets'])] for seg in value['segments']] for key, value in fast['prototypes'].items()}
    # The Shader's switches, as the plugin gets them.
    shaders = modo.Scene().items('defaultShader')
    result['shaders'] = len(shaders)
    result['visibility_before'] = sorted({str(s['visibility']) for s in fast['surfaces']})
    if shaders:
        for name, value in (('visCam', 0), ('shadCast', 0)):
            try:
                shaders[0].channel(name).set(value)
            except Exception as exc:
                result.setdefault('channel_errors', []).append(name + ': ' + str(exc)[:80])
        after = evaluated.capture(now)
        result['visibility_after_camera_and_shadow_off'] = sorted({str(s['visibility']) for s in after['surfaces']})
        from moonray_modo import host, moonlightipr_scene
        scene = host.snapshot(evaluated_geometry=True)
        result['meshes_seen_by'] = sorted({moonlightipr_scene.seen_by(m) for m in scene['meshes']})
        result['meshes_visibility'] = sorted({str(m.get('visibility')) for m in scene['meshes']})
        # Cast Shadows alone: seen by everything, casting no shadow. Then back on.
        shaders[0].channel('visCam').set(1)
        scene = host.snapshot(evaluated_geometry=True)
        result['shadow_off_only'] = sorted({str(m.get('visibility')) for m in scene['meshes']})
        shaders[0].channel('shadCast').set(1)
        scene = host.snapshot(evaluated_geometry=True)
        result['shadow_back_on'] = sorted({str(m.get('visibility')) for m in scene['meshes']})
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
