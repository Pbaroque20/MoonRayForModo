"""MoonRay's own scene objects as Modo items: the item type, the Add command and their properties.

Each class in entity_catalog.json gets a filter command, which shows its form for a selected
item of that class, and one command per attribute. tools/generate_entity_forms.py writes the
menu and the forms that call them into entities.cfg.
"""
import json
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command
import lxu.package


def register():
    from moonray_modo import entities,properties,property_notifications
    CLASSES=entities.classes()

    class Entity(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors):
        def test_parent(self,item,parent):return True

    lx.bless(Entity,entities.ITEM_TYPE,{lx.symbol.sPKG_SUPERTYPE:'locator',lx.symbol.sSRV_USERNAME:'MoonRay Item'})

    def selected():
        import modo
        return [item for item in modo.Scene().selected if entities.is_entity(item)]

    def kind(item):
        return properties.read(item).get(entities.CLASS_KEY,'')

    class Observed(lxu.command.BasicCommand):
        def cmd_NotifyAddClient(self,argidx,client):
            if not getattr(self,'_notifications',None):
                self._notifications=lxu.command.NotifierHost()
                self._notifications.add('select.event','item +v')
                self._notifications.add(property_notifications.NAME,'')
            self._notifications.add_client(client)
        def cmd_NotifyRemoveClient(self,client):
            if getattr(self,'_notifications',None):self._notifications.rem_client(client)

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
            try:item=scene.addItem(entities.ITEM_TYPE,name=name)
            except (LookupError,RuntimeError,TypeError):
                # A plain locator carries the same settings if the item type did not register.
                item=scene.addItem('locator',name=name)
            properties.write(item,{entities.CLASS_KEY:name,entities.PARAMETERS_KEY:{}})
            scene.select(item)

    lx.bless(Add,'moonray.entity.add')

    def filter_command(name):
        class Filter(Observed):
            def cmd_Flags(self):return lx.symbol.fCMD_UI
            def basic_Enable(self,msg):
                items=selected()
                return bool(items) and all(kind(item)==name for item in items)
            def basic_Execute(self,msg,flags):pass
        return Filter

    def parameter_command(name,key,spec):
        enum=spec.get('enum')
        if spec['type']=='Bool':choices,labels=[None,False,True],['Default','Off','On']
        elif enum:
            ordered=sorted(enum.items(),key=lambda entry:entry[1])
            choices,labels=[None]+[int(v) for _,v in ordered],['Default']+[k for k,_ in ordered]
        else:choices=labels=None
        names=spec['type'] in ('SceneObject*','SceneObjectVector','SceneObjectIndexable')
        class Parameter(Observed):
            def __init__(self):
                super().__init__()
                self.dyna_Add('value',lx.symbol.sTYPE_INTEGER if choices else lx.symbol.sTYPE_STRING)
                if choices:self.dyna_SetHint(0,tuple(enumerate(labels)))
                self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def basic_Enable(self,msg):
                items=selected()
                return bool(items) and all(kind(item)==name for item in items)
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                for item in selected():
                    value=properties.read(item).get(entities.PARAMETERS_KEY,{}).get(key)
                    if choices:values.AddInt(choices.index(value) if value in choices else 0)
                    elif value is None:values.AddString('')
                    elif spec['type']=='String' or spec['type']=='SceneObject*':values.AddString(value)
                    elif names:values.AddString(', '.join(value))
                    else:values.AddString(json.dumps(value))
            def basic_Execute(self,msg,flags):
                if not self.basic_Enable(msg):raise ValueError('Select a MoonRay '+name+' item')
                if choices:
                    index=self.dyna_Int(0)
                    if not 0<=index<len(choices):raise ValueError('Invalid choice')
                    value=choices[index]
                else:
                    text=self.dyna_String(0).strip()
                    if not text:value=None
                    elif spec['type'] in ('String','SceneObject*'):value=text
                    elif names:value=[part.strip() for part in text.split(',') if part.strip()]
                    else:value=json.loads(text)
                if value is not None:value=entities.typed(value,spec)
                updates=[]
                for item in selected():
                    settings=properties.read(item);parameters=settings.setdefault(entities.PARAMETERS_KEY,{})
                    if value is None:parameters.pop(key,None)
                    else:parameters[key]=value
                    updates.append((item,settings))
                for item,settings in updates:properties.write(item,settings)
        return Parameter

    for i,name in enumerate(CLASSES):
        lx.bless(filter_command(name),'moonray.entity.filter%d'%i)
        for j,(key,spec) in enumerate(sorted(entities.catalog()[name]['attributes'].items())):
            lx.bless(parameter_command(name,key,spec),'moonray.entity.param%d_%d'%(i,j))


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay items are unavailable: %s'%exc)
    except Exception:pass
