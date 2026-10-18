# python
"""Isolated GUI test: Cryptomatte names and IDs given in the Cryptomatte tab, and picking from the Cryptomatte buffer.

Two balls are given the Cryptomatte name "pair" and a box the ID 77, through the tab's commands. The object
Cryptomatte is chosen in the preview, which adds it to the outputs and renders. The mattes found over the picture are
noted with their names; then a ball is clicked (selected alone in Modo, and picked), the box Shift-clicked (picked as
well), and the ball Ctrl-clicked (no longer picked), with what is selected in Modo, the status and whether the picked
mattes are laid over the picture noted each time. The name said by the pointer over the box is noted too."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cryptomatte-pick'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def mesh(tool, x, name):
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.%s on' % tool)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.%s off' % tool)
    item = modo.Scene().selected[-1]
    item.name = name
    item.position.x.set(x)
    return item


def render():
    panel = panel_widget()
    held['runtime'] = panel.preferences.store.value('runtime')
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    # Choosing the object Cryptomatte adds it to the outputs; then the scene is rendered.
    panel.buffer.setCurrentIndex(panel.buffer.findData('crypto_object'))
    QtWidgets.QApplication.processEvents()
    result['rendering_after_choice'] = panel._rendering
    if not panel._rendering:
        panel.start.click()


def ready():
    panel = panel_widget()
    result['rendering_still'] = panel._rendering
    panel.buffer.setCurrentIndex(panel.buffer.findData('crypto_object'))
    frame = panel.renderer.buffers.displayed or panel.renderer.buffers.frame or {}
    result['shown'] = {'buffer': panel.buffer.currentData(), 'outputs': [(v.get('name'), v.get('kind')) for v in panel._settings_values().get('custom_aovs') or []],
                       'files': sorted((frame.get('files') or {}).keys()), 'status': panel.status.text()}
    panel._crypto_ready()


def survey():
    from moonray_modo import cryptomatte_pick
    panel = panel_widget()
    key, category, frame = panel._crypto_buffer()
    ids, owners = cryptomatte_pick.names(frame, category)
    width, height = panel.preview.image.width(), panel.preview.image.height()
    seen = {}
    for y in range(0, height, max(1, height // 24)):
        for x in range(0, width, max(1, width // 40)):
            value = cryptomatte_pick.at(frame, key, x, y)
            if value is not None:
                label = ids.get(value, '%08x' % value)
                seen.setdefault(label, (x, y))
    held['seen'] = seen
    result['mattes'] = {label: {'pixel': pixel, 'id': '%08x' % next((v for v, l in ids.items() if l == label), 0),
                                'of': owners.get(label)} for label, pixel in seen.items()}
    result['manifest_names'] = sorted(ids.values())


def click(wanted, modifiers, step):
    def go():
        panel = panel_widget()
        label = next((label for label in held['seen'] if wanted in label), None)
        pixel = held['seen'].get(label)
        if pixel is None:
            result['steps'].append({'step': step, 'missing': wanted})
            return
        panel._crypto_clicked(pixel[0], pixel[1], int(modifiers))
        QtWidgets.QApplication.processEvents()
        result['steps'].append({'step': step, 'selected': [item.name for item in modo.Scene().selected], 'status': panel.status.text(),
                                'picked': sorted(panel._crypto_picked.get('crypto_object', set())),
                                'overlay': panel.preview.overlay is not None})
        if step == 'shift-click box':
            panel.preview.grab().save(str(out / 'picked.png'))
    return go


def hover():
    panel = panel_widget()
    box = next((label for label in held['seen'] if 'Box' in label), None)
    if box is None:
        return
    panel._crypto_hovered(*held['seen'][box])
    panel._crypto_hover()
    result['hover_box'] = QtWidgets.QToolTip.text()


def parts():
    """The click's parts one at a time, each noted before the next: the picture of the picked, then selecting in Modo."""
    panel = panel_widget()
    key, category, frame = panel._crypto_buffer()
    panel._crypto_picked['crypto_object'] = {'pair'}
    result['part'] = 'overlay'; save()
    panel._crypto_overlay()
    result['part'] = 'overlay done %s' % (panel.preview.overlay is not None); save()
    from moonray_modo import cryptomatte_pick
    owners = cryptomatte_pick.names(frame, category)[1].get('pair', [])
    panel._crypto_select(category, frame, owners)
    result['part'] = 'select done: ' + ', '.join(item.name for item in modo.Scene().selected); save()


def compose():
    """A Cryptomatte node of the matte 'pair', alone into the Composite."""
    from moonray_modo import compositor_editor
    panel = panel_widget()
    panel.open_compositor()
    editor = compositor_editor._open.get('editor')
    held['editor'] = editor
    result['matte_choices'] = {'object': editor.matte_choices('object'), 'material': editor.matte_choices('material')}
    editor.add('cryptomatte', QtCore.QPointF(0, 120), (editor.graph['root'], 'image'), {'category': 'object', 'matte': 'pair'})
    editor.changed()


def composite():
    from moonray_modo import compositor_probe
    panel = panel_widget()
    editor = held['editor']
    editor.write()
    frame = panel.renderer.buffers.frame or {}
    result['composite_made'] = 'composite' in (frame.get('files') or {})
    ball, box = next(p for l, p in held['seen'].items() if l == 'pair'), next(p for l, p in held['seen'].items() if 'Box' in l)
    result['composite_at'] = {'ball': compositor_probe.value(frame, 'composite', *ball), 'box': compositor_probe.value(frame, 'composite', *box)}
    editor.frame(everything=True)
    QtWidgets.QApplication.processEvents()
    editor.grab().save(str(out / 'compositor.png'))
    editor.close()


def put_back():
    panel = panel_widget()
    if held.get('runtime') is None:
        panel.preferences.store.remove('runtime')
    else:
        panel.preferences.store.setValue('runtime', held['runtime'])


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    left, right = mesh('sphere', -0.6, 'Ball Left'), mesh('sphere', 0.6, 'Ball Right')
    box = mesh('cube', 0.0, 'Box')
    box.position.y.set(-0.9)
    modo.Scene().select([left, right])
    lx.eval('moonray.object.crypto_name pair')
    modo.Scene().select([box])
    lx.eval('moonray.object.crypto_id 77')
    from moonray_modo import properties
    result['stored'] = {item.name: {k: v for k, v in properties.read(item).items() if k.startswith('crypto')} for item in (left, right, box)}
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([
    (render, 60000), (ready, 8000), (survey, 500), (parts, 1000),
    (click('pair', 0, 'click ball'), 1000), (click('Box', QtCore.Qt.ShiftModifier, 'shift-click box'), 1000),
    (click('pair', QtCore.Qt.ControlModifier, 'ctrl-click ball'), 1000), (hover, 500), (compose, 15000), (composite, 500), (put_back, 100)]))
