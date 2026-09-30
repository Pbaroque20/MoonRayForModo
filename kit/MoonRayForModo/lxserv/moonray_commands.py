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
        return bool(properties.selected_meshes())

    def basic_Execute(self, msg, flags):
        from moonray_modo import properties, options
        values = options.object_values(properties.decode(self.dyna_String(0)))
        for item in properties.selected_meshes():
            properties.write(item, values)


def object_command(key):
    from moonray_modo import options
    default = options.OBJECT[key][0]

    class ObjectSetting(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value', lx.symbol.sTYPE_BOOLEAN if type(default) is bool else lx.symbol.sTYPE_INTEGER)
            self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)

        def cmd_Flags(self):
            return lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO

        def basic_Enable(self, msg):
            from moonray_modo import properties
            return bool(properties.selected_meshes())

        def basic_Execute(self, msg, flags):
            from moonray_modo import properties
            value = bool(self.dyna_Int(0)) if type(default) is bool else self.dyna_Int(0)
            for item in properties.selected_meshes():
                values = options.object_values(properties.read(item))
                values[key] = value
                properties.write(item, options.object_values(values))

        def cmd_Query(self, index, query):
            from moonray_modo import properties
            values = lx.object.ValueArray(query)
            for item in properties.selected_meshes():
                values.AddInt(int(options.object_values(properties.read(item))[key]))

        def basic_Notifier(self, index):
            if index == 0:
                return ('select.event', 'item +v')
            if index == 1:
                return ('scene.edit', '')
    return ObjectSetting


lx.bless(PreviewPage, 'moonray.page')
lx.bless(SaveSceneSettings, 'moonray.sceneSettings')
lx.bless(SaveObjectSettings, 'moonray.objectSettings')
for _key in ('override', 'subdivision', 'level', 'smooth'):
    lx.bless(object_command(_key), 'moonray.object.' + _key)
