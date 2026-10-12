# python
"""Isolated GUI test: in Draft, the paper fills the frame the camera renders and the rest of the view is black."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft-frame'
out.mkdir(parents=True, exist_ok=True)
result = {}


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.draft.click()
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(12000, finish)


def finish():
    try:
        panel = panel_widget()
        view = panel.preview
        image = view.grab().toImage()
        image.save(str(out / 'draft.png'))
        frame = view.image_rect()
        colour = lambda x, y: list(image.pixelColor(int(x), int(y)).getRgb()[:3])
        result.update(status=panel.status.text(), view=[view.width(), view.height()], frame=[round(v) for v in (frame.left(), frame.top(), frame.right(), frame.bottom())],
                      outside_top=colour(view.width() / 2, max(1, frame.top() / 2)), outside_bottom=colour(view.width() / 2, min(view.height() - 2, (frame.bottom() + view.height()) / 2)),
                      inside_top=colour(frame.left() + 6, frame.top() + 6), inside_bottom=colour(frame.left() + 6, frame.bottom() - 6))
        panel.draft.click()
        panel.stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
