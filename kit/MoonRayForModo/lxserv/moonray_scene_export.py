"""moonray.scene.export, once Export as MoonRay Scene: opens Convert LXO to RDL, which took its place (a keymap or a
script that names it still comes to the converter). The open scene is added there with Add Open Scene, and converted
in the background with the others; Export as MoonRay Scene wrote it on Modo's own thread, minutes on a heavy scene."""
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
        from moonray_modo.lxo_convert_window import show
        show()


lx.bless(Export,'moonray.scene.export')
