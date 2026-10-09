"""The camera the scene renders through, as one popup: Modo's render camera or a MoonRay camera item.

moonray_modo/camera_choice.py keeps the choice, in the MoonRay cameras' own "render through
this camera" channels. The Render item's MoonRay form and the preview window both show this
command's popup.
"""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxifc
import lxu.command


class Hints(lxifc.UIValueHints):
    """The events the popup follows and its (internal name, label) entries."""
    def __init__(self,notifiers,entries):self._notifiers,self._entries=notifiers,entries
    def uiv_Flags(self):return lx.symbol.fVALHINT_POPUPS
    def uiv_PopCount(self):return len(self._entries)
    def uiv_PopUserName(self,index):return self._entries[index][1]
    def uiv_PopInternalName(self,index):return self._entries[index][0]
    def uiv_NotifierCount(self):return len(self._notifiers)
    def uiv_NotifierByIndex(self,index):return self._notifiers[index]


def register():
    from moonray_modo import camera_choice,property_notifications
    WATCHED=(('select.event','item +v'),(property_notifications.NAME,''))

    class Camera(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('camera',lx.symbol.sTYPE_INTEGER)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def arg_UIValueHints(self,index):
            return Hints(WATCHED,[('camera%d'%i,label) for i,(label,_) in enumerate(camera_choice.choices())])
        def cmd_Query(self,index,query):
            identities=[identity for _,identity in camera_choice.choices()]
            current=camera_choice.current()
            lx.object.ValueArray(query).AddInt(identities.index(current) if current in identities else 0)
        def basic_Execute(self,msg,flags):
            entries=camera_choice.choices();index=self.dyna_Int(0)
            if not 0<=index<len(entries):raise ValueError('No such camera')
            camera_choice.choose(entries[index][1])
            property_notifications.notify()

    lx.bless(Camera,'moonray.camera')


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('The MoonRay camera chooser is unavailable: %s'%exc)
    except Exception:pass
