# python
"""Isolated GUI test: the outlines of MoonRay's tiles fade out when it leaves them.

The preview window is given outlines as MoonRay sends them, then told they are gone. The view is pictured while they
stand, part way through the fade and after it, and the strength of the outline colour is measured each time."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/bucket-fade'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def preview():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel)).preview


def outline(name):
    """How yellow the strongest outline pixel is (red less blue), and how many pixels are at all yellow."""
    image = preview().grab().toImage()
    image.save(str(out / (name + '.png')))
    strongest = count = 0
    for y in range(0, image.height(), 1):
        for x in range(0, image.width(), 3):
            c = image.pixelColor(x, y)
            yellow = c.blue() - c.red()   # the outline's blue: more blue than red
            if yellow > 12:
                count += 1
                strongest = max(strongest, yellow)
    result[name] = {'strongest': strongest, 'pixels': count}
    save()


def begin():
    try:
        view = preview()
        result['show'] = [view.show_buckets, view.show_workers]
        view.set_buckets((1, 640, 360, [(64, 64, 128, 128), (256, 96, 320, 160), (400, 200, 464, 264)]))
        QtWidgets.QApplication.processEvents()
        outline('standing')
        # One tile is left while two stay, then all are gone.
        view.set_buckets((1, 640, 360, [(64, 64, 128, 128), (256, 96, 320, 160)]))
        QtCore.QTimer.singleShot(150, part)
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')


def part():
    outline('one_fading')
    result['fading_then'] = len(preview()._fading)
    preview().set_buckets(None)
    QtCore.QTimer.singleShot(350, held)


def held():
    # Left, but not yet long enough to be done with: still at full strength.
    outline('held')
    QtCore.QTimer.singleShot(600, half)


def half():
    outline('all_fading')
    QtCore.QTimer.singleShot(700, gone)


def gone():
    outline('gone')
    result['timer_stopped'] = not preview()._fade_timer.isActive()
    save()
    lx.eval('!app.quit')


try:
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
