# python
"""Isolated GUI test of changes made without one at the time.

1. A new DwaBaseMaterial starts with glitter in object space (4).
2. The graph editor, on a kind of material never folded or unfolded, shows only its Diffuse and Specular groups open.
   The graph editor's folding is kept in settings the user's Modo shares: the one value is put aside and put back.
3. The MoonRay Widget in the graph editor says "Rendered." with a picture in its view once its render is done.
4. Pixel Samples is greyed (its command disabled) under adaptive sampling, and not under uniform.
5. With the Denoiser Off, Denoise Preview, Save Denoised EXR, Keep Fine Detail and Smart Render are greyed, and the
   preview's denoiser is off even with the denoised beauty chosen; with a denoiser chosen they are not.
Written to test-results/deferred-checks/report.json as each is reached."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/deferred-checks'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {}
held = {}
FOLD_KEY = 'folded/DwaBaseMaterial'


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def enabled(command):
    """Whether a command is enabled, as Modo greys its control: the command asked through the command service."""
    name = command.split()[0]
    try:
        spawned = lx.object.Command(lx.service.Command().Spawn(lx.symbol.iCTAG_NULL, name))
    except Exception as exc:
        return 'error: %s' % exc
    try:
        spawned.Enable(lx.service.Message().Allocate())
        return True
    except Exception:
        return False


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def settings_checks():
    # 4: Pixel Samples under each sampling mode.
    # The choice's place in its list: Uniform 0, Adaptive 1.
    lx.eval('moonray.render.sampling_mode 1')
    adaptive = enabled('moonray.render.samples 4')
    lx.eval('moonray.render.sampling_mode 0')
    result['pixel_samples_enabled'] = {'adaptive': adaptive, 'uniform': enabled('moonray.render.samples 4')}
    # 5: the denoiser's settings with it Off and with OptiX.
    keys = ('denoise_preview', 'denoise_final', 'denoise_detail', 'smart_render')
    lx.eval('moonray.render.denoiser 0')
    off = {key: enabled('moonray.render.%s ?' % key) for key in keys}
    lx.eval('moonray.render.denoiser 1')
    chosen = {key: enabled('moonray.render.%s ?' % key) for key in keys}
    lx.eval('moonray.render.denoiser 0')
    result['denoiser_settings_enabled'] = {'off': off, 'optix': chosen}
    save()


def preview_denoiser():
    panel = panel_widget()
    index = panel.buffer.findData('denoised_beauty')
    if index >= 0:
        panel.buffer.setCurrentIndex(index)
    result['preview_denoiser_with_denoiser_off'] = {'denoised_beauty_listed': index >= 0, 'denoiser': panel._preview_denoiser()}
    save()


def open_graph_editor():
    settings = QtCore.QSettings('MoonRayForModo', 'GraphEditor')
    held['fold'] = settings.value(FOLD_KEY) if settings.contains(FOLD_KEY) else None
    held['fold_present'] = settings.contains(FOLD_KEY)
    settings.remove(FOLD_KEY)
    from moonray_modo.node_editor import open_editor
    editor = held['editor'] = open_editor(modo.Scene().item(held['material']))
    # Every signal of the widget's renderer, as it comes.
    import time
    began = time.monotonic()
    events = result.setdefault('widget_events', [])
    renderer = editor.material_preview.renderer
    for name in ('status', 'failed', 'finished', 'stopped', 'image_ready', 'image_object'):
        signal = getattr(renderer, name, None)
        if signal is not None:
            signal.connect(lambda *args, name=name: events.append('%.1f %s %s' % (time.monotonic() - began, name, str(args[0])[:160] if args else '')))
    root_id = editor.graph['root']
    editor.canvas.clearSelection()
    editor.items[root_id].setSelected(True)
    QtWidgets.QApplication.processEvents()
    rows = getattr(editor, 'group_rows', {})
    shown = {group: editor.table.item(row, 0).text()[:1] for row, group in rows.items()}
    result['graph_editor_groups'] = {'open': sorted(g for g, mark in shown.items() if mark == '\u25be'),
                                     'folded': sorted(g for g, mark in shown.items() if mark == '\u25b8')}
    editor.grab().save(str(out / 'graph_editor.png'))
    save()


def widget_after():
    editor = held['editor']
    preview = editor.material_preview
    image = getattr(preview.viewer, 'image', None)
    result['widget_log'] = (getattr(preview.renderer, 'backend_log', '') or '')[-1500:]
    result['widget'] = {'status': preview.status.text(), 'button': preview.button.text(),
                        'picture_shown': bool(image is not None and not image.isNull()) if image is not None else 'unknown'}
    editor.grab().save(str(out / 'graph_editor_rendered.png'))
    save()


def restore():
    settings = QtCore.QSettings('MoonRayForModo', 'GraphEditor')
    if held.get('fold_present'):
        settings.setValue(FOLD_KEY, held['fold'])
    else:
        settings.remove(FOLD_KEY)
    result['fold_setting_put_back'] = settings.contains(FOLD_KEY) == bool(held.get('fold_present'))
    try:
        held['editor'].close()
    except Exception:
        pass
    try:
        panel = panel_widget()
        if held.get('runtime') is None:
            panel.preferences.store.remove('runtime')
        else:
            panel.preferences.store.setValue('runtime', held['runtime'])
    except Exception:
        pass


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    result.setdefault('steps_begun', []).append(function.__name__)
    save()
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    material = modo.Scene().selected[0]
    held['material'] = material.id
    # 1: glitter's starting space on a new material.
    result['new_material_glitter_space'] = properties.read(material).get('native_parameters', {}).get('glitter_space')
    result['setup'] = 'material made'
    save()
    lx.eval('moonray.open')
    result['setup'] = 'preview opened'
except Exception:
    result['error'] = traceback.format_exc()
save()


def runtime_set():
    panel = panel_widget()
    held['runtime'] = panel.preferences.store.value('runtime')
    panel.preferences.set('runtime', str(runtime))


QtCore.QTimer.singleShot(6000, lambda: run([(runtime_set, 200), (settings_checks, 500), (preview_denoiser, 500),
                                            (open_graph_editor, 30000), (widget_after, 500), (restore, 500)]))
