# python
"""Isolated GUI test: a scene someone sent in is opened and rendered, and what the plugin makes of it is written down.

MOONRAY_PROBE_LXO names the scene. What it holds (its items by type, its Fur materials, the meshes with curves), what
reading it for a render says (its notices, or the error), and what each engine in MOONRAY_PROBE_ENGINES (moonray and
moonlightipr unless named) then shows are written to test-results/user-scene/<scene name>.json, with a picture of the
window for each engine."""
import collections
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
source = pathlib.Path(os.environ['MOONRAY_PROBE_LXO'])
ENGINES = os.environ.get('MOONRAY_PROBE_ENGINES', 'moonray,moonlightipr').split(',')
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '120'))
out = root / 'test-results/user-scene'
out.mkdir(parents=True, exist_ok=True)
tag = source.stem + os.environ.get('MOONRAY_PROBE_TAG', '')
result = {'scene': str(source), 'engines': {}}
held = {'engines': list(ENGINES)}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def look():
    scene = modo.Scene()
    result['items'] = dict(collections.Counter(item.type for item in scene.items()))
    result['fur'] = [[item.name, item.parent.name if item.parent else None] for item in scene.items('furMaterial')]
    curves = []
    for mesh in scene.items('mesh'):
        try:
            kinds = collections.Counter(polygon.accessor.Type() for polygon in mesh.geometry.polygons)
        except Exception as exc:
            kinds = {'error': str(exc)}
        curves.append([mesh.name, len(mesh.geometry.vertices), {str(lx.symbol.iPTYP_FACE if k == lx.symbol.iPTYP_FACE else k): v for k, v in kinds.items()}])
    result['meshes'] = curves
    from moonray_modo import host as host_
    result['shown'] = [[mesh.name, host_.channel(mesh, 'visible'), host_.channel(mesh, 'render'), host_.render_visible(mesh), mesh.parent.name if mesh.parent else None] for mesh in scene.items('mesh')]
    tree = []
    for layer in scene.items('textureLayer'):
        if layer.type in ('shaderFolder', 'renderOutput'):
            continue
        row = [layer.name, layer.type, layer.parent.name if layer.parent else None]
        for name in ('effect', 'enable', 'opacity', 'blend', 'ptag', 'ptyp'):
            try:
                row.append('%s=%s' % (name, host_.channel(layer, name)))
            except Exception:
                pass
        tree.append(row)
    result['tree'] = tree
    furs = {}
    for layer in scene.items('furMaterial'):
        held_ = {}
        for index in range(layer.ChannelCount()):
            name = layer.ChannelName(index)
            try:
                value = host_.channel(layer, name)
                if isinstance(value, (str, int, float, bool)):
                    held_[name] = value
            except Exception:
                pass
        furs[layer.name] = held_
    result['fur_channels'] = furs
    result['mask_meshes'] = [[mask.name, [i.name for i in mask.itemGraph('shadeLoc').forward()]] for mask in scene.items('mask')]
    from moonray_modo import host
    for evaluated in (False, True):
        key = 'snapshot_evaluated' if evaluated else 'snapshot'
        try:
            began = time.monotonic()
            scene_read = host.snapshot(evaluated_geometry=evaluated, refresh_materials=True)
            fibres = scene_read.get('extra_geometry') or []
            if not evaluated and os.environ.get('MOONRAY_PROBE_TEXT') == '1':
                # The scene as MoonRay is given it, without its geometry's numbers.
                from moonray_modo import rdla
                text = rdla.scene_text(scene_read, 640, 360, 2, 0.0)
                (out / (tag + '.rdla.txt')).write_text(chr(10).join(line[:600] for line in text.splitlines()), encoding='utf-8')
            result[key] = {'fibres': [[e.get('name'), e.get('kind'), len(e.get('counts') or e.get('curve_counts') or []), e.get('fur_fibres'), e.get('fur_points'), e.get('radius'), e.get('material')] for e in fibres][:10], 'seconds': round(time.monotonic() - began, 1), 'warnings': scene_read['warnings'],
                           'meshes': [[m.get('name'), m.get('material'), len(m.get('faces') or m.get('face_counts') or [])] for m in scene_read['meshes']][:40],
                           'curves': [[c.get('name'), len(c.get('counts') or c.get('strands') or [])] for c in scene_read.get('curves', [])][:40],
                           'keys': sorted(scene_read)[:80],
                           'extra': [[e.get('name'), e.get('kind') or e.get('type'), sorted(e)[:12]] for e in (scene_read.get('extra_geometry') or scene_read.get('extras') or [])][:20],
                           'native': sorted(scene_read.get('native_materials') or {}),
                           'full_materials': {name: {k: v for k, v in material.items() if k != 'layers'} for name, material in scene_read['materials'].items() if isinstance(material, dict)},
                           'materials': {name: [[layer.get('kind'), layer.get('effect'), pathlib.Path(layer.get('path', '')).name] for layer in (material.get('layers') or [])]
                                         for name, material in scene_read['materials'].items() if isinstance(material, dict)}}
        except Exception:
            result[key] = {'error': traceback.format_exc()}
        save()


def next_engine():
    if not held['engines'] or held['engines'] == ['none']:
        save()
        QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
        return
    engine = held['engines'].pop(0)
    held['engine'] = engine
    try:
        panel = panel_widget()
        if panel._rendering or panel._following:
            panel.stop()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
        QtWidgets.QApplication.processEvents()
        held['began'] = time.monotonic()
        result['engines'][engine] = {'seen': []}
        panel.start.click()
    except Exception:
        result['engines'][engine] = {'error': traceback.format_exc()}
        save()
        QtCore.QTimer.singleShot(500, next_engine)
        return
    QtCore.QTimer.singleShot(3000, watch)


def watch():
    panel = panel_widget()
    engine = held['engine']
    now = time.monotonic() - held['began']
    entry = result['engines'][engine]
    status = panel.status.text()
    entry['seen'].append([round(now, 1), panel.render_timing.text(), status[:200]])
    done = (engine == 'moonray' and not panel._rendering and now > 8) or (engine != 'moonray' and now > float(os.environ.get('MOONRAY_PROBE_IPR_WAIT', '70'))) or now > LIMIT
    # MOONRAY_PROBE_BUFFER: once the render is done, that buffer is chosen and given a while to be made and shown.
    wanted = os.environ.get('MOONRAY_PROBE_BUFFER')
    if done and wanted and 'picked' not in held:
        held['picked'] = now
        entry['buffer_found'] = panel.buffer.findData(wanted)
        panel.buffer.setCurrentIndex(panel.buffer.findData(wanted))
        panel._buffer_picked = wanted
    if done and wanted and now - held['picked'] < 30:
        QtCore.QTimer.singleShot(3000, watch)
        return
    if done:
        entry['status'] = status
        entry['buffer'] = panel.buffer.currentData()
        entry['picture'] = not panel.preview.image.isNull()
        snapshot = (panel.renderer.active or {}).get('snapshot', {})
        entry['warnings'] = snapshot.get('warnings')
        log = str(getattr(panel.renderer, 'log', '') or '')
        entry['log'] = sorted({line.strip()[:260] for line in log.splitlines() if any(word in line.lower() for word in ('warn', 'error', 'unavailable', 'fail', 'missing'))})[:40]
        try:
            entry['notices'] = panel.notices.text() if hasattr(panel, 'notices') else None
        except Exception:
            pass
        panel.window().grab().save(str(out / ('%s_%s.png' % (tag, engine))))
        panel.preview.image.save(str(out / ('%s_%s_picture.png' % (tag, engine))))
        if os.environ.get('MOONRAY_PROBE_KEEP') == '1':
            # The render's own files, for trying things on them afterwards: its beauty and the denoiser's guides.
            import shutil
            frame = panel.renderer.buffers.frame or {}
            entry['kept'] = {}
            for key in ('beauty', 'denoise_albedo', 'denoise_normal', 'denoise_fine', 'denoised_beauty'):
                source = (frame.get('files') or {}).get(key)
                if source and pathlib.Path(str(source)).is_file():
                    held_ = out / ('%s_%s%s' % (tag, key, pathlib.Path(str(source)).suffix))
                    shutil.copyfile(str(source), str(held_))
                    entry['kept'][key] = str(held_)
            entry['frame_keys'] = sorted((frame.get('files') or {}))[:40]
        save()
        QtCore.QTimer.singleShot(1000, next_engine)
        return
    QtCore.QTimer.singleShot(3000, watch)


def begin():
    try:
        # MOONRAY_PROBE_COMMANDS: commands to run on the scene first, a semicolon between them. MOONRAY_PROBE_WIDTH
        # renders it that wide, and MOONRAY_PROBE_QUICK=1 at few uniform samples, to see it sooner.
        for command in filter(None, (c.strip() for c in os.environ.get('MOONRAY_PROBE_COMMANDS', '').split(';'))):
            lx.eval(command)
        if os.environ.get('MOONRAY_PROBE_WIDTH'):
            item = modo.Scene().renderItem
            was = (item.channel('resX').get(), item.channel('resY').get())
            width = int(os.environ['MOONRAY_PROBE_WIDTH'])
            lx.eval('render.res 0 %d' % width)
            lx.eval('render.res 1 %d' % max(16, round(width * was[1] / max(1, was[0]))))
        if os.environ.get('MOONRAY_PROBE_QUICK') == '1':
            lx.eval('moonray.render.sampling_mode 0')
            lx.eval('moonray.render.samples 3')
        look()
        lx.eval('moonray.open')
        QtWidgets.QApplication.processEvents()
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(4000, next_engine)


try:
    # Asked nothing: a scene with parts this Modo cannot load, or an OCIO config it cannot find, opens with the defaults.
    lx.eval('!!scene.open {%s} normal' % str(source).replace('\\', '/'))
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(10000, begin)
