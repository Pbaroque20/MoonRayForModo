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
    lx.bless(MoonRayView, 'MoonRayForModoPreview')
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
        widget = next((w for w in QtWidgets.QApplication.allWidgets()
                       if isinstance(w, Panel) and w.isVisible()), None)
        if widget is None:
            lx.eval('moonray.open')
            widget = next(w for w in QtWidgets.QApplication.allWidgets()
                          if isinstance(w, Panel) and w.isVisible())
        page = self.dyna_String(0)
        if page == 'preview':
            widget.live.setChecked(True)
        elif page == 'final':
            widget.render_final()
        elif page == 'export':
            widget.export()
        elif page == 'stop':
            widget.stop()
        elif page == 'log':
            widget.show_log()
        else:
            widget.show_page(page)


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


lx.bless(PreviewPage, 'moonray.page')
lx.bless(SaveSceneSettings, 'moonray.sceneSettings')
lx.bless(SaveObjectSettings, 'moonray.objectSettings')
for _key in ('override', 'subdivision', 'level', 'smooth', 'normal_override', 'smoothing_angle', 'angular_tessellation', 'tessellation_angle', 'adaptive_error', 'share_instances', 'dynamic_tessellation'):
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


# Compatibility aliases for saved menus/macros. The old external-render
# PView route remains experimental and is never started automatically.
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
