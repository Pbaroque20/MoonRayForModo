"""File > Export as MoonRay Scene: moonray_modo/scene_export.py's window, then the export, without the preview window."""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command


class Export(lxu.command.BasicCommand):
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):return True
    def basic_Execute(self,msg,flags):
        from moonray_modo.scene_export import run
        try:run()
        except Exception as exc:
            from PySide2 import QtWidgets
            QtWidgets.QMessageBox.warning(None,'Export as MoonRay Scene','The scene was not exported: %s'%exc)


lx.bless(Export,'moonray.scene.export')
