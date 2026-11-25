# python
"""Isolated GUI test (run with --show): the render settings as channels of the Render item in Modo's window.

An old scene (test-results/render-settings-channels/old-scene.lxo, saved by probe_cl_render_settings_channels.py: the
tag alone) is opened: its Render item gets the channels by itself as the scene opens, with no step left to undo. The
Render item is selected, a Channels palette opened beside its Properties, and on timers (Modo refuses undo inside a
script): a setting set by the form's command, one by item.channel (as the Channels viewport sets it), each undone and
redone, a picture of the screen after each. Then the probe waits, so the Channels viewport's filter can be typed in,
until a file named quit appears in the output folder (or 10 minutes pass). Writes test-results/render-settings-channels/
gui-report.json and PNGs."""
import json
import pathlib
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\sweet-wilbur-4f4598\test-results\render-settings-channels')
out.mkdir(parents=True, exist_ok=True)
(out / 'quit').unlink(missing_ok=True)
result = {}


def save():
    (out / 'gui-report.json').write_text(json.dumps(result, indent=1, default=str))


def state():
    from moonray_modo import properties, scene_settings
    render = modo.Scene().renderItem
    held = scene_settings.complete(properties.scene_settings())
    values = properties.read_render_channels(render) or {}
    return {'has_channels': properties.has_render_channels(render), 'samples': held['samples'],
            'max_depth': held['render']['max_depth'], 'clamp': held['render']['sample_clamping_value'],
            'moonlightipr_clamp': held['moonlightipr']['sample_clamp'],
            'channel_samples': values.get('samples'), 'channel_max_depth': values.get('max_depth'),
            'channel_clamp': values.get('sample_clamping_value'), 'form_samples': lx.eval('moonray.render.samples ?'),
            'form_clamp': lx.eval('moonray.render.sample_clamping_value ?'),
            'tag_samples': json.loads(render.readTag('MRAY')).get('samples')}


def render_id():
    return modo.Scene().renderItem.id


STEPS = [
    ('opened', lambda: None),
    # Nothing to undo after the scene opened: the channels came with no step of their own.
    ('undo-after-open', lambda: lx.eval('app.undo')),
    ('select-render', lambda: lx.eval('select.item {%s} set' % render_id())),
    ('channels-palette', lambda: lx.eval('layout.createOrClose RenderSettingsChannels "Channels Palette" title:Channels width:520 height:900 persistent:false style:palette')),
    ('form-sets-samples', lambda: lx.eval('moonray.render.samples 10')),
    ('form-undo', lambda: lx.eval('app.undo')),
    ('form-redo', lambda: lx.eval('app.redo')),
    ('channel-sets-clamp', lambda: lx.eval('item.channel mr_sample_clamping_value 3.5 item:{%s}' % render_id())),
    ('channel-undo', lambda: lx.eval('app.undo')),
    ('channel-redo', lambda: lx.eval('app.redo')),
    ('channel-sets-depth', lambda: lx.eval('item.channel mr_max_depth 12 item:{%s}' % render_id())),
    # A new scene gets the channels too (its tab's name shows whether Modo counts it as changed).
    ('new-scene', lambda: lx.eval('scene.new')),
    ('new-scene-select-render', lambda: lx.eval('select.item {%s} set' % render_id())),
    ('back-to-old-scene', lambda: lx.eval('scene.set {old-scene}')),
    ('back-select-render', lambda: lx.eval('select.item {%s} set' % render_id())),
]


def run(index=0):
    if index == len(STEPS):
        result['steps_done'] = True
        save()
        QtCore.QTimer.singleShot(1000, wait)
        return
    name, action = STEPS[index]
    try:
        action()
    except Exception:
        result[name + '-error'] = traceback.format_exc()

    def record():
        try:
            result[name] = state()
        except Exception:
            result[name + '-state-error'] = traceback.format_exc()
        QtWidgets.QApplication.primaryScreen().grabWindow(0).save(str(out / ('gui-%02d-%s.png' % (index, name))))
        save()
        QtCore.QTimer.singleShot(50, lambda: run(index + 1))
    QtCore.QTimer.singleShot(1500, record)


waited = [0]


def wait():
    """Held open for typing into the Channels viewport's filter; a file named quit in the output folder ends it."""
    waited[0] += 1
    if (out / 'quit').exists() or waited[0] > 600:
        try:
            result['at_quit'] = state()
        except Exception:
            result['at_quit-error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(1000, wait)


try:
    lx.eval('!scene.open {%s} normal' % (out / 'old-scene.lxo'))
except Exception:
    result['open-error'] = traceback.format_exc()
sys._probe_run = run
# The scene opened tells the kit (sil_SceneCreate), which gives it the channels once Modo is idle.
QtCore.QTimer.singleShot(4000, run)
