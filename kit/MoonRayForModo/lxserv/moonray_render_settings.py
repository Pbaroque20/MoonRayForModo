"""Typed commands for the render settings kept on the Render item, one per setting.

moonray_modo/scene_settings.py lists the settings; each command here takes the kind of argument
its setting is, so the Render item's MoonRay form draws a checkbox, popup, number or swatch for
it. tools/generate_render_forms.py writes that form into render_settings.cfg.
"""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxifc
import lxu.command


class Hints(lxifc.UIValueHints):
    """The events a control follows and, for a popup, its (internal name, label) entries."""
    def __init__(self,notifiers,entries=()):self._notifiers,self._entries=notifiers,entries
    def uiv_Flags(self):return lx.symbol.fVALHINT_POPUPS if self._entries else 0
    def uiv_PopCount(self):return len(self._entries)
    def uiv_PopUserName(self,index):return self._entries[index][1]
    def uiv_PopInternalName(self,index):return self._entries[index][0]
    def uiv_NotifierCount(self):return len(self._notifiers)
    def uiv_NotifierByIndex(self,index):return self._notifiers[index]


def register():
    import modo
    from moonray_modo import properties,scene_settings,property_notifications
    WATCHED=(('select.event','item +v'),(property_notifications.NAME,''))
    TYPES={'bool':lx.symbol.sTYPE_BOOLEAN,'member':lx.symbol.sTYPE_BOOLEAN,'int':lx.symbol.sTYPE_INTEGER,
           'choice':lx.symbol.sTYPE_INTEGER,'float':lx.symbol.sTYPE_FLOAT,'hex':lx.symbol.sTYPE_COLOR}

    def command(entry):
        kind=entry['kind']
        labels=[('choice%d'%i,label) for i,(label,_) in enumerate(entry['choices'] or ())]
        class Setting(lxu.command.BasicCommand):
            def __init__(self):
                super().__init__()
                self.dyna_Add('value',TYPES.get(kind,lx.symbol.sTYPE_STRING))
                self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def arg_UIValueHints(self,index):return Hints(WATCHED,labels)
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                value=scene_settings.get(scene_settings.complete(properties.scene_settings()),entry)
                if kind in ('bool','member','int','choice'):values.AddInt(int(value))
                elif kind=='float':values.AddFloat(float(value))
                elif kind=='hex':lx.object.Value(values.AddEmptyValue()).SetString(' '.join('%.9g'%v for v in value))
                else:values.AddString(value)
            def basic_Execute(self,msg,flags):
                if kind in ('bool','member','int','choice'):value=self.dyna_Int(0)
                elif kind=='float':value=self.dyna_Float(0)
                elif kind=='hex':
                    value=[float(part) for part in self.dyna_String(0).replace(',',' ').split()[:3]]
                    if len(value)!=3:raise ValueError('Expected a colour')
                else:value=self.dyna_String(0)
                stored=properties.scene_settings()
                scene_settings.put(stored,entry,value)
                properties.write(modo.Scene().renderItem,stored)
        return Setting

    def browse(entry):
        class Browse(lxu.command.BasicCommand):
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def basic_Execute(self,msg,flags):
                wanted={'lut':('luts','LUT files','*.cube;*.spi1d;*.spi3d;*.3dl;*.clf;*.ctf'),
                        'ocio_config':('ocio','OCIO configs','*.ocio')}.get(entry['key'],
                        ('images','Images','*.exr;*.hdr;*.tx;*.tif;*.tiff;*.png;*.jpg;*.jpeg'))
                try:path=modo.dialogs.customFile('fileOpen','Choose '+entry['label'],(wanted[0],'all'),(wanted[1],'All files'),(wanted[2],'*.*'))
                except RuntimeError:return
                if not path:return
                stored=properties.scene_settings()
                scene_settings.put(stored,entry,str(path).replace('\\','/'))
                if entry['key']=='background_image':stored['background']['mode']='image'
                properties.write(modo.Scene().renderItem,stored)
        return Browse

    for entry in scene_settings.FIELDS:
        if entry['kind'] in ('button','command'):continue
        lx.bless(command(entry),'moonray.render.'+entry['key'])
        if entry['kind']=='file':lx.bless(browse(entry),'moonray.render.browse_'+entry['key'])


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay render settings are unavailable: %s'%exc)
    except Exception:pass
