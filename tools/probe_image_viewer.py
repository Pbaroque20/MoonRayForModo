# python
"""Isolated GUI test: the asset library's image viewer, and what the library offers for a texture.

The asset library is opened and, once it has looked through its folders, a texture is chosen: the buttons offered for
it are noted and the library pictured. The texture is opened in the viewer, as Open does; the viewer is pictured, its
next picture shown, and what it says of each noted."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/image-viewer'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def open_library():
    from moonray_modo import asset_browser
    asset_browser.show(None)
    browser = next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, asset_browser.Browser))
    held['browser'] = browser
    # A folder of pictures, for this window only: the library's folders are kept in settings Modo shares with the user's
    # own, and are not written.
    browser.roots = browser.roots + [str(root / 'test-results/export-types')]
    browser.refresh()


def choose():
    from moonray_modo import asset_browser
    browser = held['browser'] if isinstance(held['browser'], asset_browser.Browser) else next(
        w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, asset_browser.Browser))
    held['browser'] = browser
    rows = [browser.list.item(i) for i in range(browser.list.count())]
    result['listed'] = len(rows)
    picture = next((item for item in rows if browser.is_picture(item.data(QtCore.Qt.UserRole))), None)
    if picture is None:
        result['no_picture'] = True
        return
    browser.list.setCurrentItem(picture)
    QtWidgets.QApplication.processEvents()
    row = picture.data(QtCore.Qt.UserRole)
    result['texture'] = {'path': row.get('path'), 'category': row.get('category')}
    result['buttons'] = [(button.text(), button.isEnabled()) for button in browser.findChildren(QtWidgets.QPushButton) if button.isVisible()]
    result['details'] = browser.details.text()
    browser.grab().save(str(out / 'library.png'))
    browser.view_image()
    QtWidgets.QApplication.processEvents()


def look():
    viewer = held['browser']._viewer
    result['viewer'] = {'title': viewer.windowTitle(), 'about': viewer.about.text(), 'where': viewer.where.text(),
                        'picture': [viewer.view.image.width(), viewer.view.image.height()]}
    viewer.grab().save(str(out / 'viewer.png'))
    viewer.step(1)
    QtWidgets.QApplication.processEvents()
    result['viewer_next'] = {'title': viewer.windowTitle(), 'about': viewer.about.text(), 'where': viewer.where.text()}
    viewer.close()
    held['browser'].close()


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


save()
QtCore.QTimer.singleShot(6000, lambda: run([(open_library, 15000), (choose, 3000), (look, 1000)]))
