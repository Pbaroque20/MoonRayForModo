# python
"""Command line: how much of a scene's reading (host.snapshot) goes to Modo's Shader Tree, for PROBE_SCENE: the whole
reading timed, then profiled, the time inside the material readers summed (material_values, image_layers,
material_stack, evaluated.assign_materials, shader_library.mend, the ordered Shader Tree walk), as a render reads the
scene (evaluated geometry off) and as realtime does (on). Writes PROBE_OUT/report.json (test-results/material-read)."""
import cProfile
import json
import os
import pathlib
import pstats
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\material-read'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE')}
# The readers whose time is the Shader Tree's: (module file, function).
READERS = [('host.py', 'material_values'), ('host.py', 'image_layers'), ('layers.py', 'material_stack'), ('layers.py', 'ordered'),
           ('evaluated.py', 'assign_materials'), ('shader_library.py', 'mend'), ('host.py', 'tension_maps')]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host
    for mode, evaluated in (('render', False), ('realtime', True)):
        try:
            host.snapshot(evaluated_geometry=evaluated)   # a first reading warms Modo's caches
            start = time.perf_counter()
            scene = host.snapshot(evaluated_geometry=evaluated)
            whole = time.perf_counter() - start
            # Each channel read counted by item and channel: how many ask again for one already read.
            held, asked, kinds = host.channel, {}, {}

            def counted(item, name, *rest, **named):
                try:
                    key = (item.id, name)
                    asked[key] = asked.get(key, 0) + 1
                    kinds[item.type] = kinds.get(item.type, 0) + 1
                except Exception:
                    pass
                return held(item, name, *rest, **named)
            host.channel = counted
            try:
                host.snapshot(evaluated_geometry=evaluated)
            finally:
                host.channel = held
            result[mode + '_channel_reads'] = {'reads': sum(asked.values()), 'distinct': len(asked),
                                              'items': len({k[0] for k in asked}),
                                              'by_type': dict(sorted(kinds.items(), key=lambda kv: -kv[1])[:12])}
            profile = cProfile.Profile()
            profile.enable()
            host.snapshot(evaluated_geometry=evaluated)
            profile.disable()
            stats = pstats.Stats(profile).stats
            spent = {}
            for (path, _line, name), (_cc, _nc, _tt, cumulative, _callers) in stats.items():
                for file, function in READERS:
                    if path.replace('\\', '/').endswith('moonray_modo/' + file) and name == function:
                        spent[file + ':' + function] = spent.get(file + ':' + function, 0.0) + cumulative
            profiled = sum(v[3] for (p, l, n), v in stats.items() if n == '_snapshot')
            # The busiest kit and Modo calls, by their own time and by calls, for where the readers spend it.
            rows = [(path.replace('\\', '/').split('/')[-1], name, nc, round(tt, 4), round(ct, 4)) for (path, _l, name), (_cc, nc, tt, ct, _c) in stats.items()]
            result[mode + '_top_own'] = sorted(rows, key=lambda r: -r[3])[:25]
            result[mode + '_top_calls'] = sorted(rows, key=lambda r: -r[2])[:15]
            # What the Shader Tree readers spend their time in: the calls they make, by time spent inside them.
            for reader in ('material_stack', 'material_values', 'collect', 'layer_groups', 'texture_groups'):
                calls = []
                for (path, _l, name), (_cc, _nc, _tt, _ct, callers) in stats.items():
                    for (cpath, _cl, cname), timing in callers.items():
                        if cname == reader and cpath.replace('\\', '/').endswith(('layers.py', 'host.py')):
                            calls.append((round(timing[3], 4), timing[1], path.replace('\\', '/').split('/')[-1] + ':' + name))
                result[mode + "_callees_" + reader] = sorted(calls, reverse=True)[:12]
            result[mode] = {'seconds': round(whole, 3), 'profiled_seconds': round(profiled, 3),
                            'readers': {k: round(v, 3) for k, v in sorted(spent.items(), key=lambda kv: -kv[1])},
                            'materials': len(scene.get('materials') or {}), 'meshes': len(scene.get('meshes') or [])}
        except Exception:
            result[mode + '_error'] = traceback.format_exc()
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
