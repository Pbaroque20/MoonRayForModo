"""MoonRay's own scene objects as Modo items: one item type per class, and the Add command.

Each class in entity_catalog.json becomes a locator-based item type, moonray.<Class>, whose
channels are that class's attributes, so Modo draws its own controls for them: swatches for
colours, checkboxes, popups and number fields. tools/generate_entity_forms.py writes the menu
and the forms that show those channels into entities.cfg.
"""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command
import lxu.package


def register():
    from moonray_modo import entities

    def vector(add,default):
        # One number serves when every component starts the same, which is nearly always.
        if len(set(default))==1:add.SetDefault(float(default[0]),0)
        else:
            try:
                values=lx.object.storage('d',len(default));values.set(tuple(float(v) for v in default))
                add.SetDefaultVec(values)
            except Exception:pass

    def package(name):
        plan=entities.channels(name)
        class Typed(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors):
            def test_parent(self,item,parent):return True
            def pkg_SetupChannels(self,addChan):
                add=lx.object.AddChannel(addChan)
                for key,channel,kind,default,choices in plan:
                    if kind=='boolean':
                        add.NewChannel(channel,lx.symbol.sTYPE_BOOLEAN)
                        add.SetDefault(0.0,int(default))
                    elif kind=='integer':
                        add.NewChannel(channel,lx.symbol.sTYPE_INTEGER)
                        add.SetDefault(0.0,int(default))
                        # No popup names are attached here: Modo keeps the address it is given
                        # and crashed when it later drew the form. choice_command draws the popup.
                    elif kind=='float':
                        add.NewChannel(channel,lx.symbol.sTYPE_FLOAT)
                        add.SetDefault(float(default),0)
                    elif kind=='color':
                        add.NewChannel(channel,lx.symbol.sTYPE_COLOR1)
                        add.SetVector(lx.symbol.sCHANVEC_RGB)
                        vector(add,default)
                    elif kind in ('xy','xyz'):
                        add.NewChannel(channel,lx.symbol.sTYPE_FLOAT)
                        add.SetVector(lx.symbol.sCHANVEC_XY if kind=='xy' else lx.symbol.sCHANVEC_XYZ)
                        vector(add,default)
                    else:
                        add.NewChannel(channel,lx.symbol.sTYPE_STRING)
        return Typed

    def choice_command(name,channel,choices):
        """A popup for an attribute with named values, set on the selected items of one type."""
        numbers=[number for number,_ in choices]
        def chosen():
            import modo
            return [item for item in modo.Scene().selected if item.type==entities.item_type(name)]
        class Choice(lxu.command.BasicCommand):
            def __init__(self):
                super().__init__()
                self.dyna_Add('value',lx.symbol.sTYPE_INTEGER)
                self.dyna_SetHint(0,tuple(choices))
                self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def basic_Enable(self,msg):return bool(chosen())
            def cmd_NotifyAddClient(self,argidx,client):
                if not getattr(self,'_notifications',None):
                    self._notifications=lxu.command.NotifierHost()
                    self._notifications.add('select.event','item +v')
                self._notifications.add_client(client)
            def cmd_NotifyRemoveClient(self,client):
                if getattr(self,'_notifications',None):self._notifications.rem_client(client)
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                for item in chosen():
                    try:value=int(item.channel(channel).get())
                    except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):value=numbers[0]
                    values.AddInt(value if value in numbers else numbers[0])
            def basic_Execute(self,msg,flags):
                value=self.dyna_Int(0)
                if value not in numbers:raise ValueError('Invalid choice')
                for item in chosen():item.channel(channel).set(value)
        return Choice

    for i,name in enumerate(entities.classes()):
        for j,(key,channel,kind,default,choices) in enumerate(entities.channels(name)):
            if choices:lx.bless(choice_command(name,channel,choices),'moonray.entity.choice%d_%d'%(i,j))

    for name in entities.classes():
        lx.bless(package(name),entities.item_type(name),{lx.symbol.sPKG_SUPERTYPE:'locator',lx.symbol.sSRV_USERNAME:'MoonRay '+name})

    # The first, generic item kept its class and values in a tag. It stays registered so that
    # scenes holding one still load and render; new items use the types above.
    class Entity(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors):
        def test_parent(self,item,parent):return True

    lx.bless(Entity,entities.ITEM_TYPE,{lx.symbol.sPKG_SUPERTYPE:'locator',lx.symbol.sSRV_USERNAME:'MoonRay Item'})

    class Add(lxu.command.BasicCommand):
        def __init__(self):
            super().__init__()
            self.dyna_Add('class',lx.symbol.sTYPE_STRING)
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def basic_Enable(self,msg):return True
        def basic_Execute(self,msg,flags):
            import modo
            name=self.dyna_String(0)
            if name not in entities.catalog():raise ValueError('Unknown MoonRay class: '+name)
            scene=modo.Scene()
            scene.select(scene.addItem(entities.item_type(name),name=name))

    lx.bless(Add,'moonray.entity.add')


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay items are unavailable: %s'%exc)
    except Exception:pass
