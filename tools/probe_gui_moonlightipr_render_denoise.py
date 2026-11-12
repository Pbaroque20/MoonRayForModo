# python
"""GUI: MoonLightIPR's Denoised Beauty after a Render (RT off), as a user meets it. The dragon scene (PROBE_SCENE), the
engine MoonLightIPR, the buffer Beauty. (a) Render to the end, then Denoised Beauty chosen; (b) Render stopped partway
with the Render/Stop button, then Denoised Beauty chosen. Each time: whether a new picture came after the choice, how
noisy it is beside the beauty (mean difference of neighbouring pixels), the status line, the session's state.
Writes test-results/moonlightipr-render-denoise-gui/report.json."""
import array
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-render-denoise-gui')
out.mkdir(parents=True, exist_ok=True)
report = {}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def picture():
    frame = panel().renderer.buffers.progressive_frames.get('beauty') or {}
    return frame.get('linear', {}).get('beauty')


def roughness(held):
    if not held:
        return None
    width, height, pixels = held
    values = array.array('f')
    values.frombytes(bytes(pixels)[:width * height * 12])
    total, count = 0.0, 0
    for y in range(0, height, 3):
        row = values[y * width * 3:(y + 1) * width * 3]
        total += sum(abs(row[i] - row[i + 3]) for i in range(0, (width - 1) * 3, 3))
        count += width - 1
    return round(total / max(1, count), 5)


def pick(p, key):
    """A buffer chosen as a click chooses it: the list's activated signal says it was picked by hand."""
    index = p.buffer.findData(key)
    p.buffer.setCurrentIndex(index)
    p.buffer.activated.emit(index)


def later(fn, wait):
    def run():
        try:
            fn()
        except Exception:
            report.setdefault('errors', []).append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(wait, run)


def session_state():
    r = panel().renderer
    s = r.moonlightipr
    return {'running': bool(s.running()), 'stopping': getattr(s, 'stopping', None), 'canceled': getattr(r, 'canceled', None),
            'using_moonlightipr': getattr(r, 'using_moonlightipr', None), 'denoised_view': getattr(s, 'denoised_view', None),
            'moonlightipr_denoises': getattr(r, 'moonlightipr_denoises', None), 'rendering': getattr(panel(), '_rendering', None),
            'buffer': panel().buffer.currentData(), 'denoiser_on': panel()._denoiser_on()}


def instrument():
    """Each view and aov the kit asks of the MoonLightIPR session, with whether it was running then."""
    session = panel().renderer.moonlightipr
    calls = report.setdefault('calls', [])
    for name in ('view', 'aov', 'stop', 'finish', 'release'):
        real = getattr(session, name)

        def logged(*args, real=real, name=name):
            import traceback as tb
            calls.append([round(time.monotonic() - state.get('t0', 0), 2), state.get('case'), name, [str(a) for a in args],
                          bool(session.running()), getattr(session, 'stopping', None),
                          [line.strip().splitlines()[0] for line in tb.format_stack()[-7:-1]]])
            return real(*args)
        setattr(session, name, logged)


def begin():
    state['t0'] = time.monotonic()
    instrument()
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    if p.ipr_mode.isChecked():
        p.ipr_mode.setChecked(False)
    pick(p, 'beauty')
    report['listed'] = [p.buffer.itemData(i) for i in range(p.buffer.count())]
    report['start'] = session_state()
    save()
    state['case'] = 'finished'
    state['began'] = time.monotonic()
    p.start.click()
    later(wait_done, 2000)


def wait_done():
    p = panel()
    if getattr(p, '_rendering', False) and time.monotonic() - state['began'] < 240:
        later(wait_done, 500)
        return
    entry = report.setdefault(state['case'], {})
    entry['render_seconds'] = round(time.monotonic() - state['began'], 1)
    entry['status_after_render'] = p.status.text()
    entry['state_after_render'] = session_state()
    entry['beauty_noise'] = roughness(picture())
    save()
    later(choose_denoised, 1500)


def choose_denoised():
    p = panel()
    state['before'] = picture()
    state['asked'] = time.monotonic()
    index = p.buffer.findData('denoised_beauty')
    report[state['case']]['denoised_listed'] = index >= 0
    if index < 0:
        later(next_case, 500)
        return
    pick(p, 'denoised_beauty')
    later(wait_denoised, 300)


def wait_denoised():
    p = panel()
    now = picture()
    if (now is None or now is state['before']) and time.monotonic() - state['asked'] < 15:
        later(wait_denoised, 250)
        return
    entry = report[state['case']]
    entry['new_picture_after_choice'] = now is not None and now is not state['before']
    entry['seconds_to_picture'] = round(time.monotonic() - state['asked'], 2)
    entry['denoised_noise'] = roughness(now)
    entry['status_after_choice'] = p.status.text()
    entry['state_after_choice'] = session_state()
    p.preview.image.save(str(out / ('%s_denoised.png' % state['case'])))
    save()
    later(next_case, 1000)


def next_case():
    p = panel()
    if state['case'] == 'finished':
        pick(p, 'beauty')
        state['case'] = 'stopped'
        state['began'] = time.monotonic()
        later(lambda: (p.start.click(), later(stop_partway, 2500)), 1500)
        return
    if state['case'] in ('stopped', 'chosen_first'):
        # Denoised Beauty chosen before the Render: (c) to the end, (d) stopped partway. What is shown when it ends,
        # then the beauty asked for beside it.
        stopping = state['case'] == 'chosen_first'
        state['case'] = 'chosen_first_stopped' if stopping else 'chosen_first'
        pick(p, 'denoised_beauty')
        state['began'] = time.monotonic()
        later(lambda: (p.start.click(), later(stop_partway if stopping else wait_shown, 2500)), 1500)
        return
    finish()


def wait_shown():
    p = panel()
    if getattr(p, '_rendering', False) and time.monotonic() - state['began'] < 240:
        later(wait_shown, 500)
        return
    later(compare_with_beauty, 1500)


def compare_with_beauty():
    p = panel()
    entry = report.setdefault(state['case'], {})
    entry['render_seconds'] = round(time.monotonic() - state['began'], 1)
    entry['status_at_end'] = p.status.text()
    entry['state_at_end'] = session_state()
    entry['shown_noise'] = roughness(picture())
    p.preview.image.save(str(out / ('%s_shown.png' % state['case'])))
    state['before'] = picture()
    state['asked'] = time.monotonic()
    pick(p, 'beauty')
    later(wait_beauty, 300)


def wait_beauty():
    now = picture()
    if (now is None or now is state['before']) and time.monotonic() - state['asked'] < 15:
        later(wait_beauty, 250)
        return
    report[state['case']]['beauty_noise'] = roughness(now)
    report[state['case']]['new_beauty_picture'] = now is not None and now is not state['before']
    report[state['case']]['state_after_beauty'] = session_state()
    save()
    later(next_case, 1000)


def stop_partway():
    p = panel()
    report[state['case']] = {'rendering_when_stopped': getattr(p, '_rendering', None),
                         'samples_when_stopped': getattr(p.renderer.moonlightipr, 'samples_now', None)}
    p.start.click()     # the Render button is Stop while rendering
    state['began'] = time.monotonic()
    later(wait_shown if state['case'] == 'chosen_first_stopped' else wait_done, 1500)


def finish():
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo'))
    lx.eval('moonray.open')
except Exception:
    report['error'] = traceback.format_exc()
save()
later(begin, 8000)
