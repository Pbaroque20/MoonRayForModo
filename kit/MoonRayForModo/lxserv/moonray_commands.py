"""Modo loads this module from the kit's lxserv directory."""
import os
import sys
import lx
import lxifc
import lxu.command

package_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'python')
if package_root not in sys.path:
    sys.path.insert(0, package_root)


class MoonRayView(lxifc.CustomView):
    def customview_Init(self, pane):
        from PySide2 import QtWidgets
        from moonray_modo.panel import Panel
        custom = lx.object.CustomPane(pane)
        if not custom.test():
            return False
        parent = lx.getQWidget(custom.GetParent())
        if parent is None:
            return False
        layout = parent.layout() or QtWidgets.QVBoxLayout(parent)
        layout.setContentsMargins(4, 4, 4, 4)
        self.panel = Panel(parent)
        layout.addWidget(self.panel)
        return True

    def customview_Cleanup(self, pane):
        if getattr(self, 'panel', None) is not None:
            self.panel.dispose()
            self.panel.deleteLater()
            self.panel = None


class OpenPreview(lxu.command.BasicCommand):
    def cmd_Flags(self):
        return lx.symbol.fCMD_UI

    def basic_Execute(self, msg, flags):
        if lx.service.Platform().IsHeadless():
            lx.throw(lx.symbol.e_CMD_DISABLED)
        lx.eval('layout.createOrClose MoonRayForModoWindow MoonRayForModoLayout true "MoonRay Preview" width:1000 height:720 persistent:true style:palette')


if not lx.service.Platform().IsHeadless():
    lx.bless(MoonRayView, 'MoonRayForModoPreview')
lx.bless(OpenPreview, 'moonray.open')
