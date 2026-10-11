"""What MoonRay adds to Modo's own Preferences: whether the M key assigns a MoonRay material."""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command

# The key map the option writes beside the kit's other configuration, which Modo reads when it starts. While the
# option is off there is no such file, and the key is Modo's own as it always was. (Modo's command for mapping a key
# from a script brought Modo down when it was tried, so the key map is written rather than asked for.)
KEYS=os.path.join(os.path.dirname(os.path.dirname(__file__)),'moonray_keys.cfg')
MAPPED='''<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <!-- Written by MoonRay's preference "M assigns a MoonRay material". Switch that off to remove this file. -->
  <atom type="InputRemapping">
    <hash type="Region" key=".global+(stateless)+.anywhere@m">moonray.material.assign</hash>
  </atom>
</configuration>
'''


class AssignKey(lxu.command.BasicCommand):
    """Give the M key to MoonRay's Assign Material from the next time Modo starts, or back to Modo's."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('value',lx.symbol.sTYPE_BOOLEAN)
        self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):return True
    def cmd_Query(self,index,query):
        lx.object.ValueArray(query).AddInt(1 if os.path.isfile(KEYS) else 0)
    def basic_Execute(self,msg,flags):
        if self.dyna_Int(0):
            with open(KEYS,'w',encoding='utf-8') as held:held.write(MAPPED)
        elif os.path.isfile(KEYS):
            os.remove(KEYS)


lx.bless(AssignKey,'moonray.pref.assignKey')
