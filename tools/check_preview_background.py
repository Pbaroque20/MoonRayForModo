"""Deferred Qt regression. Run with Modo's PySide2 environment, not at startup."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import tempfile
from pathlib import Path
from PySide2 import QtGui,QtWidgets
from moonray_modo.viewer import Preview


def main():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with tempfile.TemporaryDirectory(prefix='MoonRay-background-check-') as folder:
        path=Path(folder)/'background.png'
        original=QtGui.QImage(2,1,QtGui.QImage.Format_ARGB32)
        original.setPixelColor(0,0,QtGui.QColor(40,90,180,0))
        original.setPixelColor(1,0,QtGui.QColor(100,80,60,128))
        assert original.save(str(path))
        before=path.read_bytes()
        view=Preview()
        try:
            view.load(path)
            assert view.image.pixelColor(0,0).getRgb()==(40,90,180,255)
            assert view.image.pixelColor(1,0).getRgb()==(100,80,60,255)
            assert path.read_bytes()==before
            assert QtGui.QImage(str(path)).pixelColor(0,0).alpha()==0
        finally: view.deleteLater()
    print('Beauty background displayed; saved alpha preserved')

if __name__=='__main__': main()
