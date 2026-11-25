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
                # Automatic Presence Shadows (Preferences) decides this one, by whether a material is cut out by a map.
                if entry['key']=='enable_presence_shadows':
                    try:
                        from moonray_modo.presence_shadows import automatic
                        return not automatic()
                    except Exception:return True
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
                # XPU2's own sampling settings: greyed while MoonRay XPU renders the preview, which never reads them, the
                # engine chosen or a fall-back (xpu2_sampling.FALLEN) alike, as MoonRay's own come back then: the
                # settings in use are the engine's in use (a tester's report). They keep their values for XPU2's next go.
                if entry['key'] in ('xpu2_samples', 'xpu2_spend', 'xpu2_noise', 'xpu2_seed', 'xpu2_most', 'xpu2_cpu', 'xpu2_realtime'):
                    try:
                        from moonray_modo import xpu2_sampling
                        return xpu2_sampling.active()
                    except Exception:return True
                # Smart Render is MoonRay's: greyed while XPU2 renders the preview, which is quick enough to need it no more.
                # Safe Denoising is XPU2's too: its renders save as they go and can be continued.
                if entry['key'] in ('smart_render',):
                    try:
                        from moonray_modo import native
                        mode=scene_settings.complete(properties.scene_settings()).get('execution_mode','auto')
                        if native.xpu2_renders(mode):return False
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
    channels()


def channels():
    """The render settings as channels of the Render item (moonray_modo/render_channels.py): the package that holds
    them, the command that gives a scene's Render item the package with its tag's values, and the listeners that do it
    as a scene is opened or made and that have the form look again as a channel changes."""
    import lxu.package
    from moonray_modo import properties,render_channels
    plan=[(entry['key'],render_channels.channel(entry),render_channels.kind(entry),entry) for entry in render_channels.entries()]
    marks=render_channels.defaults()
    limits={name:(entry['low'] if entry['kind']!='float' else None if entry['low'] is None else entry['low']*entry['scale'],
                  entry['high'] if entry['kind']!='float' else None if entry['high'] is None else entry['high']*entry['scale'],kind)
            for key,name,kind,entry in plan if entry['kind'] in ('int','float')}
    # A choice is its number in the Channels viewport (Modo took no popup from a Python package's ChannelUI there, and
    # crashed on text hints given in pkg_SetupChannels: lxserv/moonray_entities.py); its tooltip lists the numbers.

    class Package(lxu.package.BasicPackage,lxifc.ChannelUI):
        def pkg_SetupChannels(self,addChan):
            add=lx.object.AddChannel(addChan)
            for key,name,kind,entry in plan:
                default=marks.get(key)
                if kind=='boolean':
                    add.NewChannel(name,lx.symbol.sTYPE_BOOLEAN);add.SetDefault(0.0,int(bool(default)))
                elif kind=='integer':
                    add.NewChannel(name,lx.symbol.sTYPE_INTEGER);add.SetDefault(0.0,int(default or 0))
                elif kind=='float':
                    add.NewChannel(name,lx.symbol.sTYPE_FLOAT);add.SetDefault(float(default or 0.0),0)
                elif kind=='color':
                    add.NewChannel(name,lx.symbol.sTYPE_COLOR1);add.SetVector(lx.symbol.sCHANVEC_RGB)
                    try:
                        values=lx.object.storage('d',3);values.set(tuple(float(v) for v in default));add.SetDefaultVec(values)
                    except Exception:pass
                else:
                    # Text starts empty, whatever the setting's default: empty reads as not set (render_channels.overlay).
                    add.NewChannel(name,lx.symbol.sTYPE_STRING)
        def pkg_TestInterface(self,guid):return guid==lx.symbol.u_PACKAGEINSTANCE
        def cui_UIHints(self,channelName,hints):
            held=limits.get(channelName)
            if held:
                low,high,kind=held;hints=lx.object.UIHints(hints)
                try:
                    if kind=='float':
                        if low is not None:hints.MinFloat(float(low))
                        if high is not None:hints.MaxFloat(float(high))
                    else:
                        if low is not None:hints.MinInt(int(low))
                        if high is not None:hints.MaxInt(int(high))
                except Exception:pass
            return lx.result.OK
    lx.bless(Package,render_channels.PACKAGE,{lx.symbol.sSRV_USERNAME:'MoonRay Render Settings'})

    class ToChannels(lxu.command.BasicCommand):
        """The Render item given the render settings channels, holding what its tag has set. Not undone, and so it
        clears Modo's undo history: only for a scene just opened or made, which has none (opened, below)."""
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL
        def basic_Enable(self,msg):return True
        def basic_Execute(self,msg,flags):
            import modo
            render=modo.Scene().renderItem
            if render is None:return
            properties.write_render_channels(render,properties.read(render))
    lx.bless(ToChannels,'moonray.render.toChannels')

    def opened():
        """A scene just opened or made: its Render item given the channels where it has none."""
        try:
            import modo
            render=modo.Scene().renderItem
            if render is not None and not properties.has_render_channels(render):lx.eval('!moonray.render.toChannels')
        except Exception as exc:
            try:lx.out('MoonRay: the render settings could not be made channels: %s'%exc)
            except Exception:pass

    state={'told':False,'type':None}
    def tell():
        state['told']=False
        from moonray_modo import property_notifications
        property_notifications.notify()

    class Watcher(lxifc.SceneItemListener):
        def sil_SceneDestroy(self,scene):properties.CHANGED[0]+=1
        def sil_SceneCurrent(self,scene):properties.CHANGED[0]+=1
        def sil_SceneCreate(self,scene):
            properties.CHANGED[0]+=1
            try:
                from PySide2 import QtCore
                QtCore.QTimer.singleShot(0,opened)
            except Exception:pass
        def sil_ChannelValue(self,action,item,index):
            # A render settings channel changed (in the Channels viewport, by a key, an undo): the form looks again,
            # once for all the changes of a moment.
            try:
                if state['type'] is None:state['type']=lx.service.Scene().ItemTypeLookup('polyRender')
                held=lx.object.Item(item)
                if held.Type()!=state['type']:return
                if not held.ChannelName(index).startswith(render_channels.PREFIX):return
                # The settings are read again from the channels (properties.scene_settings).
                properties.CHANGED[0]+=1
                if state['told']:return
                state['told']=True
                from PySide2 import QtCore
                QtCore.QTimer.singleShot(0,tell)
            except Exception:pass
    def moved():
        """The timeline moved: the form looks again where a keyed setting now has another value."""
        state['timed']=False
        try:
            import modo
            values=properties.read_render_channels(modo.Scene().renderItem)
        except Exception:values=None
        if values and state.get('last') is not None and values!=state['last']:tell()
        state['last']=values

    class Timeline(lxifc.SelectionListener):
        def selevent_Time(self,time):
            try:
                if state.get('timed'):return
                state['timed']=True
                from PySide2 import QtCore
                QtCore.QTimer.singleShot(0,moved)
            except Exception:pass
    channels.watcher=Watcher()
    channels.timeline=Timeline()
    from moonray_modo import quit_release
    quit_release.listen(channels.watcher)
    quit_release.listen(channels.timeline)


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay render settings are unavailable: %s'%exc)
    except Exception:pass
