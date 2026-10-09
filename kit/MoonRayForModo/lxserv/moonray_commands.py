"""Modo loads this module from the kit's lxserv directory."""
import os
import sys
import lx
import lxifc
import lxu.command
import modo

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
    # The name Modo shows for the view in its viewport list and titles a new one with; without
    # it the server's own name is used.
    lx.bless(MoonRayView, 'MoonRayForModoPreview', {lx.symbol.sSRV_USERNAME: 'MoonRay Preview'})
lx.bless(OpenPreview, 'moonray.open')


class PreviewPage(lxu.command.BasicCommand):
    def __init__(self):
        super().__init__()
        self.dyna_Add('page', lx.symbol.sTYPE_STRING)

    def cmd_Flags(self):
        return lx.symbol.fCMD_UI

    def basic_Execute(self, msg, flags):
        from PySide2 import QtWidgets
        from moonray_modo.panel import Panel
        from moonray_modo.panel_tools import WINDOW_PAGES
        if self.dyna_String(0) not in WINDOW_PAGES:
            # Render settings are the Render item's MoonRay properties; no window is needed.
            lx.eval('select.item {%s} set' % modo.Scene().renderItem.id)
            return
        widget = next((w for w in QtWidgets.QApplication.allWidgets()
                       if isinstance(w, Panel) and w.isVisible()), None)
        if widget is None:
            lx.eval('moonray.open')
            widget = next(w for w in QtWidgets.QApplication.allWidgets()
                          if isinstance(w, Panel) and w.isVisible())
        # The window does the rest: output renders, the scene dialogs, or selecting the Render
        # item, whose MoonRay properties hold the render settings.
        widget.run(self.dyna_String(0))


class SaveSceneSettings(lxu.command.BasicCommand):
    def __init__(self):
        super().__init__()
        self.dyna_Add('settings', lx.symbol.sTYPE_STRING)

    def cmd_Flags(self):
        return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

    def basic_Execute(self, msg, flags):
        from moonray_modo import properties, options
        values = properties.decode(self.dyna_String(0))
        values['render'] = options.render_values(values.get('render', {}))
        if any(key not in options.AOVS for key in values.get('aovs', [])):
            raise ValueError('Unknown AOV')
        properties.write(modo.Scene().renderItem, values)


class SaveObjectSettings(SaveSceneSettings):
    def basic_Enable(self, msg):
        from moonray_modo import properties
        return bool(properties.selected_geometry())

    def basic_Execute(self, msg, flags):
        from moonray_modo import properties, options
        values = options.object_values(properties.decode(self.dyna_String(0)))
        for item in properties.selected_geometry():
            properties.write(item, values)


class ObjectFilter(lxu.command.BasicCommand):
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):
        from moonray_modo import properties
        return bool(properties.selected_geometry())
    def basic_Execute(self,msg,flags): pass
    def basic_Notifier(self,index):
        if index==0: return ('select.event','item +v')
        if index==1: return ('scene.edit','')

lx.bless(ObjectFilter,'moonray.object.filter')


def object_command(key):
    from moonray_modo import options
    default = options.OBJECT[key][0]

    class ObjectSetting(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value', lx.symbol.sTYPE_BOOLEAN if type(default) is bool else (lx.symbol.sTYPE_FLOAT if type(default) is float else lx.symbol.sTYPE_INTEGER))
            self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)

        def cmd_Flags(self):
            return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

        def basic_Enable(self, msg):
            from moonray_modo import properties
            return bool(properties.selected_geometry())

        def basic_Execute(self, msg, flags):
            from moonray_modo import properties
            value = bool(self.dyna_Int(0)) if type(default) is bool else (self.dyna_Float(0) if type(default) is float else self.dyna_Int(0))
            for item in properties.selected_geometry():
                values = options.object_values(properties.read(item))
                values[key] = value
                properties.write(item, options.object_values(values))

        def cmd_Query(self, index, query):
            from moonray_modo import properties
            values = lx.object.ValueArray(query)
            for item in properties.selected_geometry():
                value=options.object_values(properties.read(item))[key]
                if type(default) is float: values.AddFloat(float(value))
                else: values.AddInt(int(value))

        def basic_Notifier(self, index):
            if index == 0:
                return ('select.event', 'item +v')
            if index == 1:
                return ('scene.edit', '')
    return ObjectSetting


class ObjectPopup(lxifc.UIValueHints):
    """The choices of an object setting that is one of a list."""
    def __init__(self, labels):
        self.labels = labels

    def uiv_Flags(self):
        return lx.symbol.fVALHINT_POPUPS

    def uiv_PopCount(self):
        return len(self.labels)

    def uiv_PopUserName(self, index):
        return self.labels[index]

    def uiv_PopInternalName(self, index):
        return 'choice%d' % index


def object_choice(key, choices):
    """A popup for an object setting. choices() gives (stored value, label) pairs, which may depend on the scene."""
    class ObjectChoice(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value', lx.symbol.sTYPE_INTEGER)
            self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)

        def cmd_Flags(self):
            return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

        def basic_Enable(self, msg):
            from moonray_modo import properties
            return bool(properties.selected_geometry())

        def arg_UIValueHints(self, index):
            return ObjectPopup([label for _, label in choices()])

        def cmd_Query(self, index, query):
            from moonray_modo import options, properties
            held = lx.object.ValueArray(query)
            stored = [value for value, _ in choices()]
            for item in properties.selected_geometry():
                value = options.object_values(properties.read(item))[key]
                held.AddInt(stored.index(value) if value in stored else 0)

        def basic_Execute(self, msg, flags):
            from moonray_modo import options, properties
            offered = choices()
            index = self.dyna_Int(0)
            if not 0 <= index < len(offered):
                raise ValueError('That choice is no longer offered')
            for item in properties.selected_geometry():
                values = options.object_values(properties.read(item))
                values[key] = offered[index][0]
                properties.write(item, options.object_values(values))

        def basic_Notifier(self, index):
            if index == 0:
                return ('select.event', 'item +v')
            if index == 1:
                return ('scene.edit', '')
    return ObjectChoice


def scalp_choices():
    """The meshes hair can grow on: every mesh but the ones selected, which hold the guides."""
    import modo
    scene = modo.Scene()
    chosen = {item.id for item in scene.selected}
    return [('', '(none)')] + sorted(((item.id, item.name) for item in scene.items('mesh', superType=False) if item.id not in chosen),
                                     key=lambda entry: entry[1].lower())


def hair_modes():
    from moonray_modo import options
    return [(value, label) for label, value in options.HAIR_MODES]


lx.bless(object_choice('hair_scalp', scalp_choices), 'moonray.object.hair_scalp')
lx.bless(object_choice('hair_mode', hair_modes), 'moonray.object.hair_mode')
lx.bless(PreviewPage, 'moonray.page')
lx.bless(SaveSceneSettings, 'moonray.sceneSettings')
lx.bless(SaveObjectSettings, 'moonray.objectSettings')
for _key in ('override', 'subdivision', 'level', 'smooth', 'normal_override', 'smoothing_angle', 'angular_tessellation', 'tessellation_angle', 'adaptive_error', 'share_instances', 'dynamic_tessellation',
             'curves', 'curve_root_width', 'curve_tip_width', 'curve_envelope', 'curve_samples', 'curve_uv',
             'hair', 'hair_count', 'hair_width', 'hair_clump', 'hair_length', 'hair_seed', 'hair_guides'):
    lx.bless(object_command(_key), 'moonray.object.' + _key)


class AssignMaterial(lxu.command.BasicCommand):
    def cmd_Flags(self):
        return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

    def basic_Enable(self, msg):
        from moonray_modo import properties
        return bool(properties.selected_meshes())

    def basic_Execute(self, msg, flags):
        from moonray_modo.materials import assign
        from moonray_modo.material_editor import choose
        shader=choose()
        if shader is not False: assign(shader)


def material_option(key):
    class MaterialOption(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value',lx.symbol.sTYPE_BOOLEAN)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)

        def cmd_Flags(self):
            return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

        def basic_Enable(self,msg):
            from moonray_modo.materials import selected
            return bool(selected())

        def basic_Execute(self,msg,flags):
            from moonray_modo import properties
            from moonray_modo.materials import selected
            for item in selected():
                values=properties.read(item)
                if key=='shader':
                    values['moonshine_override']=False
                    values.pop('native_shader',None)
                    values.pop('native_parameters',None)
                values[key]=('DwaBaseMaterial' if self.dyna_Int(0) else '') if key=='shader' else bool(self.dyna_Int(0))
                properties.write(item,values)

        def cmd_Query(self,index,query):
            from moonray_modo import properties
            from moonray_modo.materials import selected
            values=lx.object.ValueArray(query)
            for item in selected():
                value=properties.read(item).get(key)
                values.AddInt(int(value=='DwaBaseMaterial' if key=='shader' else bool(value)))

        def basic_Notifier(self,index):
            if index==0: return ('select.event','item +v')
            if index==1: return ('scene.edit','')
    return MaterialOption

lx.bless(AssignMaterial,'moonray.material.assign')


class ImportMaterialX(lxu.command.BasicCommand):
    """Put a MaterialX file's material on the selected meshes. The file is asked for unless it is given."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('file', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_OPTIONAL)

    def cmd_Flags(self):
        return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

    def basic_Enable(self, msg):
        from moonray_modo import properties
        return bool(properties.selected_meshes())

    def basic_Execute(self, msg, flags):
        import modo
        from moonray_modo import materials
        path = self.dyna_String(0) if self.dyna_IsSet(0) else None
        if not path:
            try:
                path = modo.dialogs.customFile('fileOpen', 'Import MaterialX Material', ('mtlx', 'all'), ('MaterialX files', 'All files'), ('*.mtlx', '*.*'))
            except RuntimeError:
                return
        if not path:
            return
        try:
            materials.import_materialx(str(path))
        except ValueError as exc:
            # What the file uses that cannot be followed, in the importer's own words.
            modo.dialogs.alert('Import MaterialX Material', 'This MaterialX file could not be imported.' + chr(10) * 2 + str(exc), dtype='warning')


lx.bless(ImportMaterialX, 'moonray.material.importMaterialX')


class LoadMaterialX(lxu.command.BasicCommand):
    """Give the selected MaterialX material the material of a file. The file is asked for unless it is given."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('file', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_OPTIONAL)

    def cmd_Flags(self):
        return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

    def chosen(self):
        from moonray_modo import properties
        return [item for item in modo.Scene().selected if item.type == properties.MATERIALX_TYPE]

    def basic_Enable(self, msg):
        return len(self.chosen()) == 1

    def basic_Execute(self, msg, flags):
        from moonray_modo import materials
        items = self.chosen()
        if len(items) != 1:
            return
        path = self.dyna_String(0) if self.dyna_IsSet(0) else None
        if not path:
            try:
                path = modo.dialogs.customFile('fileOpen', 'Load MaterialX File', ('mtlx', 'all'), ('MaterialX files', 'All files'), ('*.mtlx', '*.*'))
            except RuntimeError:
                return
        if not path:
            return
        try:
            materials.load_materialx(items[0], str(path))
        except ValueError as exc:
            modo.dialogs.alert('Load MaterialX File', 'This MaterialX file could not be loaded.' + chr(10) * 2 + str(exc), dtype='warning')

    def basic_Notifier(self, index):
        if index == 0:
            return ('select.event', 'item +v')


lx.bless(LoadMaterialX, 'moonray.material.loadMaterialX')
lx.bless(material_option('shader'),'moonray.material.enable')
lx.bless(material_option('thin_geometry'),'moonray.material.thin')


def material_control(key):
    from moonray_modo.material_settings import DEFAULTS, validate
    default = DEFAULTS[key]
    class MaterialControl(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            kind = lx.symbol.sTYPE_BOOLEAN if type(default) is bool else (
                lx.symbol.sTYPE_INTEGER if type(default) is int else lx.symbol.sTYPE_ANGLE)
            self.dyna_Add('value',kind)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
            if key=='subsurface_model':
                self.dyna_SetHint(0,((0,'normalized'),(1,'dipole'),(2,'randomWalk')))

        def cmd_Flags(self):
            return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

        def basic_Enable(self,msg):
            from moonray_modo.materials import selected
            return bool(selected())

        def basic_Execute(self,msg,flags):
            from moonray_modo import properties
            from moonray_modo.materials import selected
            value=validate(key,self.dyna_Float(0) if type(default) is float else self.dyna_Int(0))
            for item in selected():
                settings=properties.read(item)
                settings[key]=value
                properties.write(item,settings)

        def cmd_Query(self,index,query):
            from moonray_modo import properties
            from moonray_modo.materials import selected
            output=lx.object.ValueArray(query)
            for item in selected():
                value=validate(key,properties.read(item).get(key,default))
                if type(default) is float:
                    output.AddFloat(value)
                else:
                    output.AddInt(int(value))

        def basic_Notifier(self,index):
            if index==0: return ('select.event','item +v')
            if index==1: return ('scene.edit','')
    return MaterialControl


for _key in ('subsurface_model','anisotropy_angle','sss_input_normal','sss_resolve_self_intersections'):
    lx.bless(material_control(_key),'moonray.material.'+_key)


class DockPreview(lxu.command.BasicCommand):
    def cmd_Flags(self):
        return lx.symbol.fCMD_UI

    def basic_Execute(self,msg,flags):
        lx.eval('viewport.restore base.MoonRayForModoViewport false customview')

lx.bless(DockPreview,'moonray.dock')


# Compatibility aliases for saved menus/macros. They once belonged to an external-render
# PView route, which is gone: Modo cannot host an external renderer in its native PView.
class NativePreviewStartup(lxu.command.BasicCommand):
    def cmd_Flags(self):
        return lx.symbol.fCMD_UI

    def basic_Execute(self, msg, flags):
        pass


lx.bless(NativePreviewStartup, 'moonray.native.startup')
lx.bless(OpenPreview, 'moonray.native.open')
lx.bless(DockPreview, 'moonray.native.dock')


class AnimationFrame(lxu.command.BasicCommand):
    def cmd_Flags(self):
        return lx.symbol.fCMD_UI

    def basic_Execute(self,msg,flags):
        from moonray_modo.animation import active
        if active is not None and active.running:
            active.capture()

lx.bless(AnimationFrame,'moonray.animationFrame')


class EditNativeMaterial(lxu.command.BasicCommand):
    def cmd_Flags(self):
        return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg):
        from moonray_modo.materials import selected
        return len(selected())==1
    def basic_Execute(self,msg,flags):
        from moonray_modo.materials import selected
        from moonray_modo.material_editor import edit
        items=selected()
        if len(items)!=1: raise ValueError('Select one Shader Tree material')
        edit(items[0],modo.Scene())

lx.bless(EditNativeMaterial,'moonray.material.editNative')


class AboutMoonRay(lxu.command.BasicCommand):
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Execute(self,msg,flags):
        from moonray_modo.about import show
        show()

lx.bless(AboutMoonRay,'moonray.about')


class CaptureMotion(lxu.command.BasicCommand):
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Execute(self,msg,flags):
        from moonray_modo import animation
        if animation.single_request is not None:animation.single_result=animation.single_request()

lx.bless(CaptureMotion,'moonray.captureMotion')


class RelinkAssets(lxu.command.BasicCommand):
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO
    def basic_Execute(self,msg,flags):
        from moonray_modo.asset_relink import show
        show()
lx.bless(RelinkAssets,'moonray.assets.relink')


class AssetLibrary(lxu.command.BasicCommand):
    def basic_Execute(self,msg,flags):
        from moonray_modo.asset_browser import show
        show()

class AssignLibraryMaterial(lxu.command.BasicCommand):
    def __init__(self):
        super().__init__();self.dyna_Add('settings',lx.symbol.sTYPE_STRING)
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO
    def basic_Execute(self,msg,flags):
        from moonray_modo import properties,materials,shader_library
        values=properties.decode(self.dyna_String(0));shader=values['shader'];parameters=shader_library.validate(shader,values.get('parameters',{}))
        material=materials.assign(shader)
        settings=properties.read(material);settings['native_parameters']=parameters;properties.write(material,settings)

lx.bless(AssetLibrary,'moonray.library')
lx.bless(AssignLibraryMaterial,'moonray.library.assign')

class AssignMaterialBundle(lxu.command.BasicCommand):
    def __init__(self):
        super().__init__();self.dyna_Add('settings',lx.symbol.sTYPE_STRING)
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO
    def basic_Execute(self,msg,flags):
        from moonray_modo import properties,material_bundle
        material_bundle.assign(properties.decode(self.dyna_String(0))['path'])
lx.bless(AssignMaterialBundle,'moonray.library.bundle')


class ImportRdl(lxu.command.BasicCommand):
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Execute(self,msg,flags):
        from moonray_modo.rdl_import_dialog import show
        show()

class ApplyRdl(lxu.command.BasicCommand):
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO
    def basic_Execute(self,msg,flags):
        from moonray_modo import rdl_import
        if rdl_import.pending is None:raise ValueError('Choose an RDL scene in MoonRay > Import RDL scene first')
        rdl_import.result=rdl_import.apply(rdl_import.pending,rdl_import.pending.get('alone',True))

lx.bless(ImportRdl,'moonray.rdl.import')
lx.bless(ApplyRdl,'moonray.rdl.apply')


class ImportLibraryAsset(lxu.command.BasicCommand):
    def __init__(self):
        super().__init__();self.dyna_Add('settings',lx.symbol.sTYPE_STRING)
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO
    def basic_Execute(self,msg,flags):
        from moonray_modo import properties,asset_import
        values=properties.decode(self.dyna_String(0))
        asset_import.execute(values['path'],values.get('material_name'))
lx.bless(ImportLibraryAsset,'moonray.library.importAsset')
