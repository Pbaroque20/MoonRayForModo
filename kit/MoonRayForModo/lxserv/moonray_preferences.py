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


# The rest of the page: what the plugin remembers on this machine, kept where the preview window keeps its own.
import lxifc


class Listed(lxifc.UIValueHints):
    """A popup's entries: (what is stored, what is shown)."""
    def __init__(self,entries):self._entries=entries
    def uiv_Flags(self):return lx.symbol.fVALHINT_POPUPS
    def uiv_PopCount(self):return len(self._entries)
    def uiv_PopUserName(self,index):return self._entries[index][1]
    def uiv_PopInternalName(self,index):return str(self._entries[index][0])


def held():
    from moonray_modo.preferences import Preferences
    return Preferences()


def switch(key):
    class Switch(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value',lx.symbol.sTYPE_BOOLEAN)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self):return lx.symbol.fCMD_UI
        def basic_Enable(self,msg):return True
        def cmd_Query(self,index,query):lx.object.ValueArray(query).AddInt(1 if held().get(key) else 0)
        def basic_Execute(self,msg,flags):held().set(key,bool(self.dyna_Int(0)))
    return Switch


def number(key,least,most):
    class Number(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value',lx.symbol.sTYPE_FLOAT)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self):return lx.symbol.fCMD_UI
        def basic_Enable(self,msg):return True
        def cmd_Query(self,index,query):lx.object.ValueArray(query).AddFloat(float(held().get(key)))
        def basic_Execute(self,msg,flags):held().set(key,max(least,min(most,float(self.dyna_Float(0)))))
    return Number


def choice(key,entries):
    """entries are (what is stored, what is shown), or a function giving them."""
    class Choice(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value',lx.symbol.sTYPE_INTEGER)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self):return lx.symbol.fCMD_UI
        def basic_Enable(self,msg):return True
        def listed(self):return entries() if callable(entries) else entries
        def arg_UIValueHints(self,index):return Listed(self.listed())
        def cmd_Query(self,index,query):
            values=[value for value,_ in self.listed()];now=held().get(key)
            lx.object.ValueArray(query).AddInt(values.index(now) if now in values else 0)
        def basic_Execute(self,msg,flags):
            values=[value for value,_ in self.listed()];index=self.dyna_Int(0)
            if 0<=index<len(values):held().set(key,values[index])
    return Choice


def shaders():
    from moonray_modo import shader_library
    return [(name,name) for name in sorted(shader_library.catalog())]


class RuntimeFolder(lxu.command.BasicCommand):
    """Where the MoonRay runtime is: typed, or left empty for the one that came with the kit."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('value',lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):return True
    def cmd_Query(self,index,query):lx.object.ValueArray(query).AddString(str(held().get('runtime')))
    def basic_Execute(self,msg,flags):held().set('runtime',self.dyna_String(0).strip())


class RuntimeBrowse(lxu.command.BasicCommand):
    """Choose the MoonRay runtime's folder from a dialog."""
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):return True
    def basic_Execute(self,msg,flags):
        import modo
        try:path=modo.dialogs.dirBrowse('Folder of the MoonRay runtime',str(held().get('runtime')))
        except RuntimeError:return
        if path:held().set('runtime',path)


lx.bless(choice('preview_engine',(('moonray','MoonRay'),('moonlightipr','MoonLightIPR'))),'moonray.pref.engine')
lx.bless(switch('ipr'),'moonray.pref.live')
lx.bless(switch('render_on_open'),'moonray.pref.renderOnOpen')
lx.bless(switch('notices_open'),'moonray.pref.noticesOpen')
lx.bless(choice('assign/shader',shaders),'moonray.pref.assignType')
lx.bless(switch('assign/smooth'),'moonray.pref.assignSmooth')
lx.bless(number('assign/angle',0.0,180.0),'moonray.pref.assignAngle')
lx.bless(choice('draft/ink',(('tan','Tan'),('purple','Pastel purple'),('grey','Grey'))),'moonray.pref.draftInk')
lx.bless(number('light_intensity',0.0,1e9),'moonray.pref.lightIntensity')
lx.bless(RuntimeFolder,'moonray.pref.runtime')
lx.bless(RuntimeBrowse,'moonray.pref.runtimeBrowse')
