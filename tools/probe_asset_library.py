# python
"""Isolated GUI test: the asset library as a grid of pictures, each asset with the one thing it is for."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/asset-library'
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('moonray.library')
except Exception:
    result['error'] = traceback.format_exc()


def look():
    try:
        from moonray_modo import asset_browser
        window = asset_browser._dialog
        result['status'] = window.status.text()
        result['kinds'] = [window.category.item(i).text() for i in range(window.category.count())]
        result['count'] = window.list.count()
        named = {window.list.item(i).text(): window.list.item(i) for i in range(window.list.count())}
        result['with_pictures'] = sum(1 for item in named.values() if not item.icon().isNull())
        gold = named.get('Polished gold')
        if gold is not None:
            window.list.setCurrentItem(gold)
            QtWidgets.QApplication.processEvents()
            result['gold'] = [window.title.text(), window.use.text(), window.details.text()[:160]]
        window.grab().save(str(out / 'library.png'))
        for kind in ('Models', 'Example scenes'):
            found = window.category.findItems(kind, QtCore.Qt.MatchExactly)
            if found:
                window.category.setCurrentItem(found[0])
                QtWidgets.QApplication.processEvents()
                shown = [window.list.item(i) for i in range(window.list.count()) if not window.list.item(i).isHidden()]
                if shown:
                    window.list.setCurrentItem(shown[0])
                    QtWidgets.QApplication.processEvents()
                    result[kind] = [len(shown), window.title.text(), window.use.text()]
                window.grab().save(str(out / ('library_%s.png' % kind.split()[0].lower())))
    except Exception:
        result['look_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(7000, look)
