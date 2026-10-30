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


def _same(kind, *args):
    """One popup description for each set of choices (moonray_modo.hint_cache); the kit is on the path only once commands run."""
    from moonray_modo.hint_cache import same
    return same(kind, *args)


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
    # MoonRay's sampling mode for adaptive sampling (options.ENUMS['sampling_mode']).
    ADAPTIVE=2
    # What only adaptive sampling uses.
    ADAPTIVE_ONLY=('min_adaptive_samples','max_adaptive_samples','target_adaptive_error')
    # MoonRay's light sampling mode for adaptive light sampling (options.ENUMS['light_sampling_mode']).
    ADAPTIVE_LIGHTS=1
    # The settings that only mean something with a denoiser chosen.
    NEEDS_DENOISER=('denoise_preview','denoise_final','denoise_detail','smart_render')
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
            def basic_Enable(self,msg):
                # XPU2 renders the preview: its sampling generations are on, their switch is
                # greyed, and so are MoonRay's own sampling settings, which show what XPU2 takes (xpu2_sampling), and
                # what XPU2 does not read at all (cpu_scene.h): MoonRay's buckets and their order, and two sampling
                # switches of MoonRay's own. Final renders, MoonRay's, still use them all.
                if entry['key'] in ('xpu2_generations','sampling_mode','samples','min_adaptive_samples','max_adaptive_samples','target_adaptive_error',
                                    'bucket_size','batch_tile_order','important_first','volume_indirect_samples','disable_optimized_hair_sampling'):
                    from moonray_modo import xpu2_sampling
                    if xpu2_sampling.active():return False
                # Pixel Samples is uniform sampling's: under adaptive sampling MoonRay does not use it, so it is greyed.
                if entry['key']=='samples':
                    try:return scene_settings.complete(properties.scene_settings())['render'].get('sampling_mode')!=ADAPTIVE
                    except Exception:return True
                # And adaptive sampling's own settings under uniform sampling.
                if entry['key'] in ADAPTIVE_ONLY:
                    try:return scene_settings.complete(properties.scene_settings())['render'].get('sampling_mode')==ADAPTIVE
                    except Exception:return True
                # Light Quality is adaptive light sampling's: under uniform light sampling every light is sampled.
                # (Light Samples counts in both.)
                if entry['key']=='light_sampling_quality':
                    try:return scene_settings.complete(properties.scene_settings())['render'].get('light_sampling_mode')==ADAPTIVE_LIGHTS
                    except Exception:return True
                # What a denoiser does is greyed while the Denoiser is Off: it is off everywhere then.
                # XPU2's sampling generations' own settings, greyed with generations off.
                if entry['key'] in ('xpu2_samples', 'xpu2_spend', 'xpu2_noise', 'xpu2_seed', 'xpu2_most', 'xpu2_cpu', 'xpu2_realtime'):
                    return True
                # Smart Render and Safe Denoising are MoonRay's: greyed while XPU2 renders the preview, which is quick
                # enough to need neither.
                if entry['key'] in ('smart_render','denoise_safe'):
                    try:
                        from moonray_modo import native
                        if native.xpu2():return False
                    except Exception:pass
                if entry['key'] in NEEDS_DENOISER:
                    try:
                        denoising=scene_settings.complete(properties.scene_settings())['denoising']
                        if denoising.get('engine','off')=='off':return False
                        # Smart Render and Safe Denoising are one or the other: each is greyed while the other is on.
                        if entry['key']=='smart_render':return not denoising.get('safe')
                    except Exception:return True
                if entry['key']=='denoise_safe':
                    try:return scene_settings.complete(properties.scene_settings())['denoising'].get('smart','off')=='off'
                    except Exception:return True
                return True
            def arg_UIValueHints(self,index):return _same(Hints,WATCHED,labels)
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                value=scene_settings.get(scene_settings.complete(properties.scene_settings()),entry)
                # Generation Samples left at 0: what XPU2 takes then, a uniform scene's Pixel Samples
                # squared, Pixel Samples itself being greyed while generations are on.
                if entry['key']=='xpu2_samples' and not value:
                    try:
                        held=scene_settings.complete(properties.scene_settings())
                        value=int(held.get('samples',0))**2
                    except Exception:pass
                # XPU2 renders the preview: the generations on, MoonRay's sampling fields showing what XPU2 takes.
                from moonray_modo import xpu2_sampling
                if xpu2_sampling.active():
                    try:value=xpu2_sampling.shown(scene_settings.complete(properties.scene_settings()),entry['key'],value)
                    except Exception:pass
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
