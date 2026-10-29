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
def _same(kind, *args):
    """One popup description for each set of choices (moonray_modo.hint_cache); the kit is on the path only once commands run."""
    from moonray_modo.hint_cache import same
    return same(kind, *args)


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
        def arg_UIValueHints(self,index):return _same(Listed,self.listed())
        def cmd_Query(self,index,query):
            values=[value for value,_ in self.listed()];now=held().get(key)
            lx.object.ValueArray(query).AddInt(values.index(now) if now in values else 0)
        def basic_Execute(self,msg,flags):
            values=[value for value,_ in self.listed()];index=self.dyna_Int(0)
            if 0<=index<len(values):held().set(key,values[index])
    return Choice


def draft_widths():
    from moonray_modo.preferences import DRAFT_WIDTHS
    return [(float(width),'%d'%width) for width in DRAFT_WIDTHS]


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


lx.bless(choice('open_engine',(('moonray','MoonRay'),('moonray_ls','MoonRay LS'),('moonlightipr','MoonLightIPR'))),'moonray.pref.engine')
lx.bless(choice('environment_lighting',(('moonray','MoonRay: always'),('modo','Follow Modo: with Global Illumination on'))),'moonray.pref.environmentLighting')
lx.bless(switch('ipr'),'moonray.pref.live')
lx.bless(switch('render_on_open'),'moonray.pref.renderOnOpen')
lx.bless(switch('notices_open'),'moonray.pref.noticesOpen')
lx.bless(switch('toon_terminator'),'moonray.pref.toonTerminator')
lx.bless(switch('toon_albedo'),'moonray.pref.toonAlbedo')
lx.bless(switch('denoise_clean_guides'),'moonray.pref.denoiseCleanGuides')
lx.bless(switch('light_motion'),'moonray.pref.lightMotion')
lx.bless(switch('crypto_volumes'),'moonray.pref.cryptoVolumes')
lx.bless(switch('fog_alpha'),'moonray.pref.fogAlpha')
lx.bless(switch('toon_lines_apart'),'moonray.pref.toonLinesApart')
lx.bless(switch('filter_inputs'),'moonray.pref.filterInputs')
lx.bless(switch('crypto_once'),'moonray.pref.cryptoOnce')
lx.bless(switch('drain_tiles'),'moonray.pref.drainTiles')
lx.bless(switch('binary_geometry'),'moonray.pref.binaryGeometry')
lx.bless(switch('low_latency'),'moonray.pref.lowLatency')
lx.bless(switch('usd_specular'),'moonray.pref.usdSpecular')
lx.bless(switch('opaque_alpha'),'moonray.pref.opaqueAlpha')
lx.bless(switch('transmission_roughness'),'moonray.pref.transmissionRoughness')
lx.bless(switch('auto_xpu'),'moonray.pref.autoXpu')
lx.bless(switch('ngon_ears'),'moonray.pref.ngonEars')
lx.bless(choice('assign/shader',shaders),'moonray.pref.assignType')
lx.bless(switch('assign/smooth'),'moonray.pref.assignSmooth')
lx.bless(number('assign/angle',0.0,180.0),'moonray.pref.assignAngle')
lx.bless(choice('draft/ink',(('tan','Tan'),('purple','Pastel purple'),('grey','Grey'))),'moonray.pref.draftInk')
lx.bless(choice('draft/width',draft_widths),'moonray.pref.draftWidth')
lx.bless(number('light_intensity',0.0,1e9),'moonray.pref.lightIntensity')
lx.bless(choice('working_space',(('rec709','Linear Rec.709'),('acescg','ACEScg (AP1, D60)'))),'moonray.pref.workingSpace')
lx.bless(RuntimeFolder,'moonray.pref.runtime')
lx.bless(RuntimeBrowse,'moonray.pref.runtimeBrowse')


class ReleaseIdleRenderers(lxu.command.BasicCommand):
    """Free completed sessions only; never interrupt sampling or queued work."""
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def basic_Execute(self, msg, flags):
        from PySide2 import QtWidgets
        from moonray_modo.render import Renderer
        released = 0
        seen = set()
        for widget in QtWidgets.QApplication.allWidgets():
            renderer = getattr(widget, 'renderer', None)
            if not isinstance(renderer, Renderer) or id(renderer) in seen: continue
            seen.add(id(renderer))
            for session in (renderer.session, renderer.moonlightipr):
                released += int(session.idle.release_now())
        lx.out('MoonRay: released %d idle renderer session(s); active renders were left running.' % released)

lx.bless(choice('idle_release_minutes', ((0,'Never'),(1,'After 1 minute'),(5,'After 5 minutes'),(15,'After 15 minutes'),(30,'After 30 minutes'))),'moonray.pref.idleRelease')
lx.bless(ReleaseIdleRenderers,'moonray.releaseIdle')
