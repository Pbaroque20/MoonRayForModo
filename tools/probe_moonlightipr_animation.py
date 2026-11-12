# python
"""GUI: two MoonLightIPR reports. (1) Render Animation with MoonLightIPR as the engine: three frames of a test scene at
32 samples a pixel, as EXRs and PNGs beside them; the files written and their sizes. (2) A MoonLightIPR Render, then
Denoised Beauty chosen: the picture is denoised as it stands, with no new render (the session's generation and samples
unchanged, nothing rendering), and differs from the beauty. Writes test-results/moonlightipr-animation/report.json."""
import json
import pathlib
import shutil
import struct
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-animation')
shutil.rmtree(str(out), ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def begin():
    try:
        p = panel()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        from moonray_modo.playblast import MoonLightIPRAnimation
        import modo
        widest = int(modo.Scene().renderItem.channel('resX').get())
        sequence = MoonLightIPRAnimation(p, str(out / 'frames'), 1, 3, 24.0, prefix='frame', width=widest, samples=32,
                                         digits=4, export_as={'type': 'png8', 'quality': 92, 'only': False})
        if p.ipr_mode.isChecked():
            p.ipr_mode.setChecked(False)
        p.stop()
        p.sequence = sequence
        state['began'] = time.monotonic()
        sequence.start()
        QtCore.QTimer.singleShot(1000, wait_animation)
    except Exception:
        result['animation_error'] = traceback.format_exc(); render_denoise()


def wait_animation():
    try:
        p = panel()
        if p.sequence is not None and p.sequence.running and time.monotonic() - state['began'] < 300:
            QtCore.QTimer.singleShot(500, wait_animation); return
        result['animation'] = {'seconds': round(time.monotonic() - state['began'], 1), 'status': p.status.text(),
                               'files': sorted((f.name, f.stat().st_size) for f in (out / 'frames').glob('*'))}
        save()
    except Exception:
        result['animation_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(1500, render_denoise)


def mean(linear):
    width, height, pixels = linear
    values = struct.unpack('<%df' % (width * height * 3), pixels)
    return sum(values) / len(values), values


def render_denoise():
    try:
        p = panel()
        p.preferences.set('moonlightipr/render_samples', 16)
        # The scene's Denoiser on, for Denoised Beauty to be in MoonLightIPR's list.
        p._store(denoising=dict(p._settings_values()['denoising'], engine='optix'))
        p._limit_buffers()
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        state['began'] = time.monotonic()
        p.start.click()
        QtCore.QTimer.singleShot(1000, wait_render)
    except Exception:
        result['denoise_error'] = traceback.format_exc(); finish()


def wait_render():
    try:
        p = panel()
        r = p.renderer
        if (getattr(p, '_rendering', False) or r.buffers.busy()) and time.monotonic() - state['began'] < 120:
            QtCore.QTimer.singleShot(300, wait_render); return
        frame = r.buffers.progressive_frames.get('beauty') or {}
        state['beauty'] = frame.get('linear', {}).get('beauty')
        state['said'] = getattr(r.moonlightipr, 'samples_now', None)
        state['serial'] = getattr(r, 'moonlightipr_serial', None)
        p.preview.image.save(str(out / 'render-beauty.png'))
        p.buffer.setCurrentIndex(p.buffer.findData('denoised_beauty'))
        state['switched'] = time.monotonic()
        QtCore.QTimer.singleShot(3000, check_denoised)
    except Exception:
        result['denoise_error'] = traceback.format_exc(); finish()


def check_denoised():
    try:
        p = panel()
        r = p.renderer
        frame = r.buffers.progressive_frames.get('beauty') or {}
        denoised = frame.get('linear', {}).get('beauty')
        entry = {'listed': not p.buffer.view().isRowHidden(p.buffer.findData('denoised_beauty')),
                 'rendering_after': getattr(p, '_rendering', False),
                 'serial_before': state.get('serial'), 'serial_after': getattr(r, 'moonlightipr_serial', None),
                 'samples_before': state.get('said'), 'samples_after': getattr(r.moonlightipr, 'samples_now', None),
                 'status': p.status.text()}
        if state.get('beauty') and denoised:
            a, va = mean(state['beauty'])
            b, vb = mean(denoised)
            entry['mean_beauty'] = round(a, 5)
            entry['mean_denoised'] = round(b, 5)
            entry['differs'] = any(abs(x - y) > 1e-4 for x, y in zip(va[::997], vb[::997]))
        p.preview.image.save(str(out / 'render-denoised.png'))
        result['denoise'] = entry
    except Exception:
        result['denoise_error'] = traceback.format_exc()
    finish()


def finish():
    try:
        panel().preferences.set('moonlightipr/render_samples', 500)
    except Exception:
        pass
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\src.lxo')
    import modo
    for name, value in (('resX', 480), ('resY', 270)):
        modo.Scene().renderItem.channel(name).set(value)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
