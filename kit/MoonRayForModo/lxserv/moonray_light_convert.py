"""moonray.light.convert: the selected Modo area lights made into MoonRay RectLight items in their place, lighting the
scene as they did (moonray_modo/light_convert.py). Offered on the Item List's right-click menu of an area light and in
the MoonRay menu."""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command


def register():
    class Convert(lxu.command.BasicCommand):
        """The selected area lights made MoonRay RectLights, each keeping its name, place, parent, children and its
        Lighting controls, with its size, colour and strength as MoonRay renders the area light."""
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def basic_Enable(self,msg):
            from moonray_modo.light_convert import selected_area_lights
            try:return bool(selected_area_lights())
            except Exception:return False
        def basic_Execute(self,msg,flags):
            import modo
            from moonray_modo.light_convert import convert,convertible,selected_area_lights
            made,said=[],[]
            for light in selected_area_lights():
                reason=convertible(light)
                if reason:said.append(reason);continue
                try:
                    item,failed=convert(light)
                    made.append(item)
                    if failed:said.append('%s: could not set %s'%(item.name,', '.join(failed)))
                except (ValueError,RuntimeError,LookupError) as exc:
                    said.append(str(exc))
            if made:modo.Scene().select(made)
            for words in said:lx.out('MoonRay: '+words)
            if said:
                try:modo.dialogs.alert('Convert to MoonRay Rect Light','\n'.join(said),'warning')
                except Exception:pass
            try:
                from moonray_modo import property_notifications
                property_notifications.notify()
            except Exception:pass

    lx.bless(Convert,'moonray.light.convert')


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay light conversion is unavailable: %s'%exc)
    except Exception:pass
