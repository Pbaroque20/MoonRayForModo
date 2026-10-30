# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): what a realtime preview does through fast moves of
the camera after its first picture. The scene in MOONRAY_PROBE_SCENE is followed by MOONRAY_PROBE_ENGINE (moonlightipr,
or moonray with IPR on); the render camera is moved sideways in bursts (MOONRAY_PROBE_BURSTS of 15 moves, 0.1 s
apart, as a drag does), and each reading of the scene, digest, plan, simplification, pack and submit is written down
with its time and thread, beside every stall of Modo's thread over 0.2 s (a heartbeat on it every 20 ms), into
MOONRAY_PROBE_OUT/report.json."""
import json
import os
import pathlib
import threading
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')
result = {'engine': ENGINE, 'events': [], 'stalls': [], 'status': []}
held = {'zero': time.perf_counter(), 'beat': None}
lock = threading.Lock()


def now():
    return round(time.perf_counter() - held['zero'], 3)


def save():
    with lock:
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def note(kind, seconds, detail=None):
    with lock:
        result['events'].append((now(), kind, round(seconds, 4), threading.current_thread().name[:16], detail))


def wrap(owner, name, kind):
    original = getattr(owner, name)

    def timed(*a, **k):
        began = time.perf_counter()
        try:
            return original(*a, **k)
        finally:
            note(kind, time.perf_counter() - began)
    setattr(owner, name, timed)


def beat():
    t = time.perf_counter()
    if held['beat'] is not None and t - held['beat'] > 0.2:
        with lock:
            result['stalls'].append((now(), round(t - held['beat'], 3)))
    held['beat'] = t


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        from moonray_modo import moonlightipr_scene, moonlightipr_detail, simplify
        # MOONRAY_PROBE_PREFS ("key=value;..."): the test profile's preferences set first (true/false as switches).
        if os.environ.get('MOONRAY_PROBE_PREFS'):
            from moonray_modo.native import settings_name
            store = QtCore.QSettings('MoonRayForModo', settings_name())
            for pair in os.environ['MOONRAY_PROBE_PREFS'].split(';'):
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    store.setValue(key.strip(), {'true': True, 'false': False}.get(value.strip().lower(), value.strip()))
            store.sync()
            result['prefs'] = os.environ['MOONRAY_PROBE_PREFS']
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
        # MOONRAY_PROBE_BUFFER: the picture shown (denoised_beauty, ...).
        if os.environ.get('MOONRAY_PROBE_BUFFER'):
            held['buffer'] = os.environ['MOONRAY_PROBE_BUFFER']
        QtWidgets.QApplication.processEvents()
        if ENGINE != 'moonlightipr' and not panel.ipr_mode.isChecked():
            panel.ipr_mode.setChecked(True)
        wrap(panel, '_capture', 'read scene')
        wrap(panel, '_capture_preview', 'read scene (motion)')
        # Why each reading was asked for: what it reuses, from where, and whether the time or settings had changed.
        captured = panel._capture

        def asked(reuse=False, transform_items=None):
            try:
                import traceback as trace
                where = [frame.name + ':' + str(frame.lineno) for frame in trace.extract_stack()[-6:-1]]
                current = {k: v for k, v in panel._settings_values().items() if k not in ('display', 'preview_buffer', 'aovs', 'recovery', 'denoising', 'compositor')}
                before = panel._live_settings or {}
                differ = sorted(k for k in set(current) | set(before) if current.get(k) != before.get(k))[:8]
                note('asked', 0.0, {'reuse': reuse if not isinstance(reuse, dict) else 'dirty', 'where': where, 'settings': differ,
                                    'time': (panel._last_time, lx.service.Selection().GetTime())})
            except Exception as exc:
                note('asked', 0.0, {'error': str(exc)[:120]})
            return captured(reuse, transform_items)
        panel._capture = asked
        # A failure's traceback, as the panel only says its message.
        failed = panel._failed

        def failing(message):
            import traceback as trace
            note('failed', 0.0, {'message': str(message)[:200], 'trace': trace.format_exc()[-3000:]})
            save()
            return failed(message)
        panel._failed = failing
        # And what Modo's notices said each time they were taken (full: read whole).
        def consumed_notices(_consume=panel.changes.consume):
            value = _consume()
            if value[0] or value[1]:
                note('notices', 0.0, {'full': value[0], 'items': sorted(value[1])[:6]})
            return value
        panel.changes.consume = consumed_notices
        # Which notice set full, on the listener's own class (Modo calls it through the class: methods set on the
        # instance cut it off from the notices).
        kind = type(panel.changes)
        for name in [n for n in vars(kind) if n.startswith('sil_')]:
            method = vars(kind)[name]

            def told(self, *a, _name=name, _method=method):
                before = self.full
                value = _method(self, *a)
                if self.full and not before:
                    note('full by', 0.0, _name)
                return value
            setattr(kind, name, told)
        wrap(panel, '_digest', 'digest')
        wrap(panel, '_submit', 'submit')
        wrap(moonlightipr_scene, 'pack', 'pack')
        wrap(moonlightipr_detail, 'plan', 'plan')
        wrap(simplify, 'polygon_mesh', 'simplify polygons')
        wrap(simplify, 'arrays', 'simplify arrays')
        # Why the scene is read whole: Modo's notices (full, or items), the asset check, and what an edit was found to be.
        from moonray_modo import assets, incremental
        consume = panel.changes.consume

        def consumed(*a, **k):
            value = consume(*a, **k)
            try:
                full, items = value
                if full or items:
                    note('notices', 0.0, {'full': bool(full), 'items': sorted(items)[:6], 'count': len(items)})
            except Exception:
                pass
            return value
        panel.changes.consume = consumed
        signature = assets.signature

        def signed(*a, **k):
            value = signature(*a, **k)
            before = getattr(panel, '_asset_signature', None)
            if before is not None and value != before:
                try:
                    gone = [str(x)[:160] for x in before if x not in value][:3]
                    new = [str(x)[:160] for x in value if x not in before][:3]
                except Exception:
                    gone, new = '?', '?'
                note('assets differ', 0.0, {'gone': gone, 'new': new})
            return value
        assets.signature = signed
        classify = incremental.classify

        def classified(scene, identities, cache):
            value = classify(scene, identities, cache)
            try:
                facts = {'value': value if not isinstance(value, dict) else {k: sorted(v)[:4] for k, v in value.items()},
                         'deformers': incremental.deformers(scene), 'steady': incremental.steady(scene),
                         'meshInst': len(scene.items('meshInst', superType=False)), 'replicator': len(scene.items('replicator', superType=False)),
                         'evaluated': cache.get('_evaluated_data') is not None, 'extra': len(cache.get('extra_geometry') or [])}
                kinds = sorted({item.type for item in scene.iterItems()})
                facts['kinds'] = [k for k in kinds if k not in incremental.STEADY and not k.startswith(('material.', 'moonray.'))][:12]
            except Exception as exc:
                facts = {'value': str(value)[:80], 'error': str(exc)[:120]}
            note('classify', 0.0, facts)
            return value
        incremental.classify = classified
        # Each plan's cut, and each refinement: what makes a pack long with nothing moving.
        plan = moonlightipr_detail.plan

        def planned(meshes, camera, width, detail='fine', displaces=lambda mesh: False):
            began = time.perf_counter()
            cuts, refinable = plan(meshes, camera, width, detail, displaces)
            summary = {'detail': detail, 'refinable': refinable, 'meshes': len(cuts),
                       'subdivision': sum(c['subdivision'] for c in cuts.values()), 'splits': sum(c['splits'] for c in cuts.values()),
                       'simplified': sum(1 for c in cuts.values() if c['simplify']),
                       'cut': hash(tuple(sorted((str(m.get('identity', m.get('name'))), c['subdivision'], c['splits'],
                                                 (c['simplify'] or {}).get('triangles')) for m in meshes for c in [cuts.get(id(m))] if c)))}
            note('plan', time.perf_counter() - began, summary)
            return cuts, refinable
        moonlightipr_detail.plan = planned
        wrap(panel, '_refine_detail', 'refine detail')
        submit = panel._submit

        def submitted(scene, *a, **k):
            value = submit(scene, *a, **k)
            note('sent', 0.0, {'detail': getattr(panel, '_detail_now', None), 'recut': getattr(panel, '_detail_recut', None)})
            return value
        panel._submit = submitted
        payload = moonlightipr_scene.mesh_payload

        def payloaded(mesh, *a, **k):
            began = time.perf_counter()
            value = payload(mesh, *a, **k)
            took = time.perf_counter() - began
            if took > 0.5:
                note('mesh packed', took, {'name': str(mesh.get('name'))[:40], 'faces': len(mesh.get('faces') or []), 'cut': bool(a[2] if len(a) > 2 else k.get('simplified'))})
            return value
        moonlightipr_scene.mesh_payload = payloaded
        # The first scene packed, kept for the pack to be timed and profiled away from Modo (MOONRAY_PROBE_DUMP).
        dump = os.environ.get('MOONRAY_PROBE_DUMP')
        if dump:
            pack = moonlightipr_scene.pack

            def kept(*a, **k):
                if not held.get('dumped'):
                    held['dumped'] = True
                    try:
                        import pickle
                        with open(dump, 'wb') as stream:
                            pickle.dump((a, k), stream, protocol=pickle.HIGHEST_PROTOCOL)
                        note('dumped', 0.0)
                    except Exception:
                        result.setdefault('errors', []).append(traceback.format_exc())
                return pack(*a, **k)
            moonlightipr_scene.pack = kept
        said = panel.status.setText

        def say(text):
            result['status'].append((now(), str(text)[:120]))
            return said(text)
        panel.status.setText = say
        held['camera'] = modo.Scene().renderCamera.id
        held['x'] = 0.0
        timer = QtCore.QTimer(panel)
        timer.timeout.connect(beat)
        timer.start(20)
        held['timer'] = timer
        note('start', 0.0)
        # MoonRay's realtime has an RT switch of its own where the preview has one (MOONRAY_PROBE_RT).
        if hasattr(panel, 'rt') and (ENGINE == 'moonlightipr' or os.environ.get('MOONRAY_PROBE_RT')):
            panel.rt.click()
        else:
            panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    # MOONRAY_PROBE_POSES: the camera set to these poses in turn ("x y z rx ry rz;..."), each picture kept, in place
    # of the bursts of moves; MoonLightIPR's own lines written down.
    for name in ('moonlightipr', 'session'):
        # MoonLightIPR's own lines, or the MoonRay session's.
        try:
            session = getattr(panel.renderer, name)
            session.output.connect(lambda text: result.setdefault('session', []).extend(
                (now(), line[:200]) for line in text.splitlines() if line.strip() and not line.startswith('@@')))
        except Exception:
            result.setdefault('errors', []).append(traceback.format_exc())
    first = (lambda: pose(0)) if os.environ.get('MOONRAY_PROBE_POSES') else (lambda: burst(0, 0))
    # MOONRAY_PROBE_START=orbit: the turns of the scene's root alone (and the reading whole after, with VERIFY).
    if os.environ.get('MOONRAY_PROBE_START') == 'orbit':
        first = lambda: (panel_widget().preview.image.save(str(out / 'before.png')), orbit(0))
    # MOONRAY_PROBE_START=part: the edited mesh chosen as edit() would, then the moves of parts, the turns and the rest.
    if os.environ.get('MOONRAY_PROBE_START') == 'part':
        def moves():
            meshes = sorted(((len(modo.Mesh(m).geometry.vertices), m) for m in modo.Scene().items('mesh')), key=lambda entry: entry[0])
            sized = [m for n, m in meshes if n >= 2000]
            held['mesh'] = (sized[len(sized) // 2] if sized else meshes[-1][1]).id
            panel_widget().preview.image.save(str(out / 'before.png'))
            part(0)
        first = moves
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_SETTLE', '90')) * 1000, first)


def pose(step):
    """The render camera set to the next of MOONRAY_PROBE_POSES, its picture kept 25 s later with its brightness."""
    poses = [p.split() for p in os.environ['MOONRAY_PROBE_POSES'].split(';') if p.strip()]
    if step >= len(poses):
        finish()
        return
    try:
        x, y, z, rx, ry, rz = poses[step]
        lx.eval('select.item {%s} set' % held['camera'])
        for channel, value in (('pos.X', x), ('pos.Y', y), ('pos.Z', z), ('rot.X', rx), ('rot.Y', ry), ('rot.Z', rz)):
            lx.eval('transform.channel %s %s' % (channel, value))
        note('pose %d' % step, 0.0, poses[step])
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())

    def look():
        try:
            bright = picture_brightness()
            panel_widget().preview.image.save(str(out / ('pose-%02d.png' % step)))
            result.setdefault('poses', []).append((step, poses[step], bright))
        except Exception:
            result.setdefault('errors', []).append(traceback.format_exc())
        save()
        pose(step + 1)
    QtCore.QTimer.singleShot(25000, look)


def burst(number, step):
    try:
        if step == 0:
            note('burst %d' % number, 0.0)
            if number == 0:
                # From where the camera stands: set from 0, the camera left the car behind.
                try:
                    held['x'] = float(modo.LocatorSuperType(modo.Scene().item(held['camera'])).position.x.get())
                except Exception:
                    result.setdefault('errors', []).append(traceback.format_exc())
            if number == 0 and held.get('buffer'):
                # The picture to show while moving (MOONRAY_PROBE_BUFFER), now that realtime offers it.
                buffer = panel_widget().buffer
                at = buffer.findData(held['buffer'])
                result['buffer'] = held['buffer'] if at >= 0 else 'not offered'
                if at >= 0:
                    buffer.setCurrentIndex(at)
        lx.eval('select.item {%s} set' % held['camera'])
        held['x'] += 0.02
        lx.eval('transform.channel pos.X %s' % held['x'])
        if step in (5, 10) and number == 0:
            # Pictures in the middle of the moves: what realtime shows while the view moves.
            panel_widget().preview.image.save(str(out / ('moving-%02d.png' % step)))
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    if step < 14:
        QtCore.QTimer.singleShot(100, lambda: burst(number, step + 1))
    elif number + 1 < int(os.environ.get('MOONRAY_PROBE_BURSTS', '2')):
        save()
        QtCore.QTimer.singleShot(20000, lambda: burst(number + 1, 0))
    elif os.environ.get('MOONRAY_PROBE_ONLY_BURSTS'):
        # The bursts alone (pictures while moving), then done.
        save()
        QtCore.QTimer.singleShot(5000, finish)
    else:
        save()
        QtCore.QTimer.singleShot(20000, lambda: edit(0))


def edit(count):
    """One object edited, as a tool's drag lets go: a mesh's points moved by Modo's move tool, twice."""
    try:
        if 'mesh' not in held:
            meshes = sorted(((len(modo.Mesh(m).geometry.vertices), m) for m in modo.Scene().items('mesh')), key=lambda entry: entry[0])
            sized = [m for n, m in meshes if n >= 2000]
            chosen = sized[len(sized) // 2] if sized else meshes[-1][1]
            held['mesh'] = chosen.id
            result['edited'] = {'name': chosen.name, 'vertices': len(modo.Mesh(chosen).geometry.vertices)}
        note('edit %d' % count, 0.0)
        lx.eval('select.item {%s} set' % held['mesh'])
        lx.eval('select.typeFrom vertex')
        lx.eval('select.drop vertex')
        lx.eval('tool.set TransformMove on')
        lx.eval('tool.attr xfrm.transform TY %s' % (0.002 * (count + 1)))
        lx.eval('tool.doApply')
        lx.eval('tool.set TransformMove off')
        lx.eval('select.typeFrom item')
        note('edit done', 0.0)
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    if count < 1:
        QtCore.QTimer.singleShot(25000, lambda: edit(count + 1))
    else:
        QtCore.QTimer.singleShot(25000, lambda: part(0))


def part(step):
    """Parts of the scene moved by their items, as a drag lets go (MOONRAY_PROBE_PARTS steps, 8 s apart): first an item
    with meshes under it that is not the root (a wheel with its hub), then the edited mesh's own item, alternately."""
    if step >= int(os.environ.get('MOONRAY_PROBE_PARTS', '4')):
        orbit(0)
        return
    try:
        if 'part' not in held:
            scene = modo.Scene()
            meshes = scene.items('mesh')
            under = []
            for item in scene.iterItems():
                if item.parent is None or item.type == 'mesh':
                    continue
                count = sum(1 for child in item.children(recursive=True) if child.type == 'mesh')
                if 0 < count < len(meshes) // 2:
                    under.append((count, item))
            held['part'] = max(under, key=lambda entry: entry[0])[1].id if under else held['mesh']
            result['part'] = {'name': scene.item(held['part']).name, 'type': scene.item(held['part']).type}
        target = held['part'] if step % 2 == 0 else held['mesh']
        lx.eval('select.item {%s} set' % target)
        lx.eval('transform.channel pos.X %s' % (0.05 * (step + 1)))
        note('part %d' % step, 0.0, {'item': modo.Scene().item(target).name})
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(8000, lambda: part(step + 1))


def picture_brightness():
    """The preview's mean brightness over a grid of its pixels (0-255), and the picture saved for a look."""
    image = panel_widget().preview.image
    if image.isNull():
        return None
    total, n = 0, 0
    for y in range(0, image.height(), max(1, image.height() // 24)):
        for x in range(0, image.width(), max(1, image.width() // 32)):
            c = QtGui.QColor(image.pixel(x, y))
            total += (c.red() + c.green() + c.blue()) / 3.0
            n += 1
    return round(total / max(n, 1), 1)


def orbit(step):
    """The camera taken round the scene's middle in steps of 15 degrees (MOONRAY_PROBE_ORBIT steps), each picture's
    brightness written down and the picture kept: a car that goes missing at some angle shows as one far darker."""
    import math
    steps = int(os.environ.get('MOONRAY_PROBE_ORBIT', '0'))
    if step >= steps:
        # The picture of the last move kept once the renderer has had time to take it (MOONRAY_PROBE_SETTLE_LAST s).
        if os.environ.get('MOONRAY_PROBE_VERIFY'):
            QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_SETTLE_LAST', '0')) * 1000, lambda: verify(0))
        else:
            finish()
        return
    try:
        if step == 0:
            # The car turned, not the camera (which is aimed and parented): the root most of the meshes hang from.
            from collections import Counter
            roots = Counter()
            for mesh in modo.Scene().items('mesh'):
                item = mesh
                while item.parent is not None:
                    item = item.parent
                roots[item.id] += 1
            held['root'] = roots.most_common(1)[0][0]
            result['orbit_root'] = modo.Scene().item(held['root']).name
            result['orbit'] = []
        lx.eval('select.item {%s} set' % held['root'])
        lx.eval('transform.channel rot.Y %s' % (15.0 * (step + 1)))
        note('orbit %d' % step, 0.0)
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())

    def look():
        try:
            bright = picture_brightness()
            panel_widget().preview.image.save(str(out / ('orbit-%02d.png' % step)))
            result['orbit'].append((step, 15 * (step + 1), bright))
        except Exception:
            result.setdefault('errors', []).append(traceback.format_exc())
        save()
        orbit(step + 1)
    QtCore.QTimer.singleShot(6000, look)


def verify(step=0):
    """The picture the moves left, beside one of the same scene read whole (the cached reading dropped): where they
    differ, a partial reading put something elsewhere. Mean difference over a grid of pixels, 0-255, both kept."""
    try:
        panel = panel_widget()
        if step == 0:
            held['partial'] = panel.preview.image.copy()
            held['partial'].save(str(out / 'verify-partial.png'))
            panel._geometry_cache = None
            panel.changes.full = True
            note('verify read whole', 0.0)
            QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_VERIFY', '90')) * 1000, lambda: verify(1))
            return
        whole = panel.preview.image.copy()
        whole.save(str(out / 'verify-whole.png'))
        a, total, n = held['partial'], 0.0, 0
        for y in range(0, min(a.height(), whole.height()), max(1, a.height() // 36)):
            for x in range(0, min(a.width(), whole.width()), max(1, a.width() // 48)):
                p, q = QtGui.QColor(a.pixel(x, y)), QtGui.QColor(whole.pixel(x, y))
                total += (abs(p.red() - q.red()) + abs(p.green() - q.green()) + abs(p.blue() - q.blue())) / 3.0
                n += 1
        result['verify'] = {'mean_difference': round(total / max(n, 1), 2), 'pixels': n}
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    finish()


def skip_unknown(left=180):
    """Modo's question when a scene holds items of a plugin the test profile has not (the car's Octane meshes): skipped,
    "Yes to All", as a user without the plugin answers it. The answer the profile kept was lost with it, and every test
    after waited on the question. Looked for each second while the scene opens (a modal question runs Qt's loop)."""
    try:
        # The windows up, each second: what a scene that never opened waited on.
        shown = sorted({w.windowTitle() for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.windowTitle()})
        (out / 'windows.txt').write_text('%d s left: %s\n' % (left, shown), encoding='utf-8')
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if widget.isVisible() and widget.windowTitle().startswith('Load Error'):
                for button in widget.findChildren(QtWidgets.QAbstractButton):
                    if button.text().replace('&', '').startswith('Yes to All'):
                        result.setdefault('skipped', []).append(widget.windowTitle())
                        button.click()
                        break
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    if left > 0:
        QtCore.QTimer.singleShot(1000, lambda: skip_unknown(left - 1))


def finish():
    note('end', 0.0)
    try:
        # How many readings the live render cache served, and how many it could not (evaluated.LIVE).
        from moonray_modo import evaluated
        result['live'] = dict(getattr(evaluated, 'LIVE', {}))
    except Exception:
        pass
    try:
        panel = panel_widget()
        if hasattr(panel, 'rt') and panel.rt.isChecked():
            panel.rt.click()
        panel.stop()
    except Exception:
        pass
    save()
    lx.eval('!app.quit')


try:
    skip_unknown()
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    # The denoiser off, or OptiX's where the denoised pictures are what is looked at (MOONRAY_PROBE_KEEP_DENOISER).
    # MOONRAY_PROBE_UNTOUCHED: the scene as saved (no setting changed), so that a kept reading of it may be taken.
    if not os.environ.get('MOONRAY_PROBE_UNTOUCHED'):
        lx.eval('moonray.render.denoiser %d' % (1 if os.environ.get('MOONRAY_PROBE_KEEP_DENOISER') else 0))
    lx.eval('moonray.open')
except Exception:
    result['error_open'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
