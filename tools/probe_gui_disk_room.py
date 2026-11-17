# python
"""GUI: what the preview says of a drive nearly full while it renders (disk_room, panel._watch_room), without filling a
drive: every drive is taken to be nearly full (disk_room.LOW_BYTES raised), PROBE_SCENE opened (the 9 Spheres test
scene unless named), Start pressed on PROBE_ENGINE (moonray: XPU2 where chosen), and noted: the notices and their
button once the render is on; the status once it has shown nothing new for longer than disk_room.HELD_UP (the time of
its last picture set back); and a render failing with a full drive's error. Writes test-results/disk-room/report.json
and Modo quits."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\disk-room'))
out.mkdir(parents=True, exist_ok=True)
scene = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\9Spheres_test_16_1\9Spheres_test_16_1_bundled.lxo')
engine = os.environ.get('PROBE_ENGINE', 'moonray')
result = {'scene': scene, 'engine': engine, 'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(step):
    p = panel()
    result['steps'].append({'step': step, 'rendering': bool(getattr(p, '_rendering', False)), 'status': p.status.text(),
                            'notices': p.warnings.toPlainText(), 'button': p.notice_toggle.text(),
                            'button_tip': p.notice_toggle.toolTip(), 'button_style': p.notice_toggle.styleSheet()})
    save()


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(ms, run)


def start():
    from moonray_modo import disk_room
    held['low'], held['every'] = disk_room.LOW_BYTES, disk_room.EVERY
    disk_room.LOW_BYTES = 10 ** 18      # every drive nearly full
    disk_room.EVERY = 0.5               # looked at on every poll
    result['short'] = [[name, room] for name, room in disk_room.short()]
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
    p.start.click()
    later(3000, rendering)


def rendering():
    note('rendering')
    # Nothing new shown for a minute, as a render held up for room.
    panel()._shown_at = time.monotonic() - 60.0
    later(2500, held_up)


def held_up():
    note('held up')
    p = panel()
    if p._rendering:
        p.start.click()     # Stop
    later(4000, failing)


def failing():
    panel()._failed('Modo evaluated geometry: basic_ios::clear: iostream error')
    note('failed')
    from moonray_modo import disk_room
    disk_room.LOW_BYTES, disk_room.EVERY = held['low'], held['every']
    later(3000, restored)


def restored():
    note('room again, nothing rendering')
    finish()


def finish():
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))


held = {}
try:
    lx.eval('!scene.open {%s} normal' % scene)
    lx.eval('moonray.page preview')
    later(6000, start)
except Exception:
    result['errors'] = [traceback.format_exc()]
    finish()
save()
