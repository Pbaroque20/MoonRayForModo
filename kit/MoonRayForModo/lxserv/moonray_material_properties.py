"""Native Modo material dropdown and schema-filtered property commands."""
import json
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxifc
import lxu.command
from moonray_modo import properties,shader_library,material_override,property_notifications
from moonray_modo.materials import selected

TYPES=['']+sorted(shader_library.catalog())


lx.bless(property_notifications.Notifier,property_notifications.NAME)

class Observed(lxu.command.BasicCommand):
    def cmd_NotifyAddClient(self,argidx,client):
        if not getattr(self,'_notifications',None):
            self._notifications=lxu.command.NotifierHost()
            self._notifications.add('select.event','item +v')
            self._notifications.add(property_notifications.NAME,'')
        self._notifications.add_client(client)
    def cmd_NotifyRemoveClient(self,client):
        if getattr(self,'_notifications',None):self._notifications.rem_client(client)


class MaterialType(Observed):
    def __init__(self):
        super().__init__()
        self.dyna_Add('type',lx.symbol.sTYPE_INTEGER)
        self.dyna_SetHint(0,tuple((i,(name+' (override)') if name else 'Modo controls (no native override)') for i,name in enumerate(TYPES)))
        self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg): return bool(selected()) and all(material_override.enabled(properties.read(i)) for i in selected())
    def cmd_Query(self,index,query):
        values=lx.object.ValueArray(query)
        for item in selected():
            shader=material_override.effective(properties.read(item)).get('native_shader','')
            values.AddInt(TYPES.index(shader) if shader in TYPES else 0)
    def basic_Execute(self,msg,flags):
        index=self.dyna_Int(0)
        if not 0<=index<len(TYPES): raise ValueError('Unknown material type')
        shader=TYPES[index]
        for item in selected():
            settings=properties.read(item)
            old=settings.get('native_shader','')
            if old==shader: continue
            presets=settings.setdefault('native_type_presets',{})
            if old: presets[old]=settings.get('native_parameters',{})
            settings.pop('node_graph',None)
            settings['moonshine_override']=bool(shader)
            settings['node_override']=False
            settings['native_shader']=shader
            settings['native_parameters']=shader_library.validate(shader,presets.get(shader,{})) if shader else {}
            if shader: settings['shader']='DwaBaseMaterial'
            properties.write(item,settings)


def filter_command(shader):
    class Filter(Observed):
        def cmd_Flags(self): return lx.symbol.fCMD_UI
        def basic_Enable(self,msg):
            items=selected()
            return bool(items) and all(material_override.effective(properties.read(item)).get('native_shader','')==shader for item in items)
        def basic_Execute(self,msg,flags): pass
    return Filter


def parameter_command(shader,key,spec):
    enum=spec.get('enum')
    choices=[None,False,True] if spec['type']=='Bool' else [None]+[int(v) for v in enum.values()] if enum else None
    labels=['Default','Off','On'] if spec['type']=='Bool' else ['Default']+list(enum) if enum else None
    class Parameter(Observed):
        def __init__(self):
            super().__init__()
            self.dyna_Add('value',lx.symbol.sTYPE_INTEGER if choices else lx.symbol.sTYPE_STRING)
            if choices: self.dyna_SetHint(0,tuple(enumerate(labels)))
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def basic_Enable(self,msg):
            items=selected()
            return bool(items) and all(material_override.enabled(properties.read(item)) and material_override.effective(properties.read(item)).get('native_shader')==shader for item in items)
        def cmd_Query(self,index,query):
            values=lx.object.ValueArray(query)
            for item in selected():
                value=properties.read(item).get('native_parameters',{}).get(key)
                if choices: values.AddInt(choices.index(value) if value in choices else 0)
                else: values.AddString('' if value is None else value if spec['type']=='String' else json.dumps(value))
        def basic_Execute(self,msg,flags):
            if not self.basic_Enable(msg): raise ValueError('Select matching native material')
            if choices:
                index=self.dyna_Int(0)
                if not 0<=index<len(choices): raise ValueError('Invalid parameter selection')
                value=choices[index]
            else:
                text=self.dyna_String(0).strip()
                value=None if not text else text if spec['type']=='String' else json.loads(text)
            if value is not None: value=shader_library.typed(value,spec)
            updates=[]
            for item in selected():
                settings=properties.read(item);params=settings.setdefault('native_parameters',{})
                if value is None: params.pop(key,None)
                else: params[key]=value
                graph=settings.get('node_graph')
                if graph:
                    root=graph['nodes'][graph['root']]
                    if value is None: root.setdefault('parameters',{}).pop(key,None)
                    else: root.setdefault('parameters',{})[key]=value
                    root.setdefault('inputs',{}).pop(key,None)
                updates.append((item,settings))
            for item,settings in updates: properties.write(item,settings)
    return Parameter

lx.bless(MaterialType,'moonray.material.type')
for i,shader in enumerate(TYPES):
    lx.bless(filter_command(shader),'moonray.material.filter'+str(i))
    if not shader: continue
    for j,(key,spec) in enumerate(sorted(shader_library.catalog()[shader]['attributes'].items())):
        # Material connections retain the named-input editor instead of raw IDs.
        if spec['type']=='SceneObject*': continue
        lx.bless(parameter_command(shader,key,spec),'moonray.material.param%d_%d'%(i,j))


class MoonShineOverride(Observed):
    def __init__(self):
        super().__init__();self.dyna_Add('enabled',lx.symbol.sTYPE_BOOLEAN)
        self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg):return bool(selected()) and all(i.type in ('advancedMaterial','material.moonrayMoonShine',properties.MATERIALX_TYPE) or properties.layer_shader(i) for i in selected())
    def cmd_Query(self,index,query):
        values=lx.object.ValueArray(query)
        for item in selected():values.AddInt(int(material_override.enabled(properties.read(item))))
    def basic_Execute(self,msg,flags):
        if not self.basic_Enable(msg):raise ValueError('Select a MoonShine material')
        from moonray_modo import nodes
        updates=[]
        for item in selected():
            settings=properties.read(item)
            if self.dyna_Int(0):
                settings=material_override.synchronize(settings,settings.get('node_graph') or nodes.from_material(item))
            else:settings['moonshine_override']=False
            updates.append((item,settings))
        for item,settings in updates:properties.write(item,settings)

lx.bless(MoonShineOverride,'moonray.material.moonshineOverride')

class OpenNodes(Observed):
    def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg):
        items=selected()
        return len(items)==1 and (items[0].type in ('advancedMaterial','material.moonrayMoonShine',properties.MATERIALX_TYPE) or properties.layer_shader(items[0])) and material_override.enabled(properties.read(items[0]))
    def basic_Execute(self,msg,flags):
        from moonray_modo.node_editor import open_editor
        if not self.basic_Enable(msg):raise ValueError('Enable MoonShine Material Override to open its node editor')
        open_editor(selected()[0])


class NodeOverride(OpenNodes):
    def basic_Enable(self,msg): return True
    def basic_Execute(self,msg,flags):
        import modo
        lx.eval('shader.create material.moonrayMaterialX')
        items=[item for item in modo.Scene().selected if item.type=='material.moonrayMaterialX']
        if len(items)!=1: raise ValueError('Could not identify the new MaterialX Override layer')
        properties.write(items[0],{'materialx_override':False})
        items[0].name='MaterialX Override'

class ApplyGraph(lxu.command.BasicCommand):
    """Write a material's settings from the graph editor, which is not inside a command of its own."""
    def __init__(self):
        super().__init__()
        self.dyna_Add('item',lx.symbol.sTYPE_STRING);self.dyna_Add('settings',lx.symbol.sTYPE_STRING)
    def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Execute(self,msg,flags):
        import modo
        try:item=modo.Scene().item(self.dyna_String(0))
        except LookupError:raise ValueError('The material this graph belongs to is no longer in the scene')
        properties.write(item,properties.decode(self.dyna_String(1)))

lx.bless(ApplyGraph,'moonray.material.applyGraph')
lx.bless(OpenNodes,'moonray.material.nodes')
lx.bless(NodeOverride,'moonray.material.nodeOverride')


class MaterialXOverride(Observed):
    def __init__(self):
        super().__init__()
        self.dyna_Add('enabled',lx.symbol.sTYPE_BOOLEAN)
        self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg): return len(selected())==1 and selected()[0].type=='material.moonrayMaterialX'
    def cmd_Query(self,index,query):
        values=lx.object.ValueArray(query)
        for item in selected(): values.AddInt(int(bool(properties.read(item).get('materialx_override',False))))
    def basic_Execute(self,msg,flags):
        items=selected()
        if len(items)!=1 or items[0].type!='material.moonrayMaterialX': raise ValueError('Select one MaterialX Override layer')
        item=items[0]
        if self.dyna_Int(0):
            from moonray_modo.node_editor import open_editor
            open_editor(item,materialx_override=True)
        else:
            settings=properties.read(item);settings['materialx_override']=False;properties.write(item,settings)


class EditMaterialX(OpenNodes):
    def basic_Enable(self,msg): return len(selected())==1 and selected()[0].type=='material.moonrayMaterialX'
    def basic_Execute(self,msg,flags):
        from moonray_modo.node_editor import open_editor
        items=selected()
        if len(items)!=1 or items[0].type!='material.moonrayMaterialX': raise ValueError('Select one MaterialX Override layer')
        open_editor(items[0],materialx_override=True)

lx.bless(MaterialXOverride,'moonray.material.materialxOverride')
lx.bless(EditMaterialX,'moonray.material.editMaterialX')


class RegularMaterialFilter(Observed):
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):
        items=selected()
        return bool(items) and all(item.type=='advancedMaterial' for item in items)
    def basic_Execute(self,msg,flags): pass

lx.bless(RegularMaterialFilter,'moonray.material.regularFilter')


class CryptomatteFilter(Observed):
    """The Cryptomatte tab, for any material."""
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self,msg): return bool(selected())
    def basic_Execute(self,msg,flags): pass


class Watched(lxifc.UIValueHints):
    """The events a Cryptomatte field follows: the selection, and a material setting written. Without them listed here a
    field kept the first material's value."""
    def __init__(self,notifiers):self._notifiers=notifiers
    def uiv_Flags(self):return 0
    def uiv_NotifierCount(self):return len(self._notifiers)
    def uiv_NotifierByIndex(self,index):return self._notifiers[index]


def crypto_setting(key,text):
    """A material's Cryptomatte name (text) or ID (a whole number), kept with its other MoonRay settings."""
    from moonray_modo.options import CRYPTO_ID_MAX
    class CryptoSetting(Observed):
        def __init__(self):
            super().__init__();self.dyna_Add('value',lx.symbol.sTYPE_STRING if text else lx.symbol.sTYPE_INTEGER)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def basic_Enable(self,msg): return bool(selected())
        def arg_UIValueHints(self,index):
            from moonray_modo.hint_cache import same
            return same(Watched,(('select.event','item +v'),(property_notifications.NAME,'')))
        def cmd_Query(self,index,query):
            values=lx.object.ValueArray(query)
            for item in selected():
                held=properties.read(item).get(key)
                if text: values.AddString(str(held or ''))
                else: values.AddInt(int(held or 0))
        def basic_Execute(self,msg,flags):
            value=(self.dyna_String(0) or '').strip() if text else min(CRYPTO_ID_MAX,max(0,self.dyna_Int(0)))
            for item in selected():
                settings=properties.read(item);settings[key]=value;properties.write(item,settings)
    return CryptoSetting


lx.bless(CryptomatteFilter,'moonray.material.cryptoFilter')
lx.bless(crypto_setting('crypto_name',True),'moonray.material.crypto_name')
lx.bless(crypto_setting('crypto_id',False),'moonray.material.crypto_id')


class AddMoonShineOverride(OpenNodes):
    def basic_Enable(self,msg):return True
    def basic_Execute(self,msg,flags):
        import modo
        from moonray_modo import nodes
        if len(selected())==1 and selected()[0].type=='advancedMaterial':
            AddOverrideAbove().basic_Execute(msg,flags);return
        lx.eval('shader.create material.moonrayMoonShine')
        items=[item for item in modo.Scene().selected if item.type=='material.moonrayMoonShine']
        if len(items)!=1:raise ValueError('Could not identify the new MoonShine Material Override layer')
        item=items[0]
        item.name='MoonShine Material Override'
        properties.write(item,material_override.synchronize({},nodes.from_material(item)))

class MoonShineLayerFilter(Observed):
    def cmd_Flags(self):return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):
        items=selected()
        return bool(items) and all(item.type=='material.moonrayMoonShine' for item in items)
    def basic_Execute(self,msg,flags):pass

lx.bless(AddMoonShineOverride,'moonray.material.addMoonShineOverride')
lx.bless(MoonShineLayerFilter,'moonray.material.layerFilter')


class AddOverrideAbove(OpenNodes):
    def basic_Enable(self,msg):
        items=selected()
        return len(items)==1 and items[0].type=='advancedMaterial'
    def basic_Execute(self,msg,flags):
        import modo
        import copy
        from moonray_modo import nodes
        if not self.basic_Enable(msg):raise ValueError('Select one Modo material')
        source=selected()[0];parent=source.parent;index=source.parentIndex
        if parent is None:raise ValueError('The material must belong to the Shader Tree')
        settings=properties.read(source)
        graph=copy.deepcopy(settings.get('node_graph')) if material_override.enabled(settings) and settings.get('node_graph') else nodes.from_material(source)
        settings=material_override.synchronize({},graph)
        scene=modo.Scene()
        item=scene.addItem('material.moonrayMoonShine',name='MoonShine Material Override - '+source.name)
        item.setParent(parent,index+1)
        properties.write(item,settings)
        scene.select(item)

lx.bless(AddOverrideAbove,'moonray.material.addOverrideAbove')


# A diffuse edited in Modo: a linked material has it already (material_diffuse), and what shows it is told. One of a scene
# saved before the link takes it as its colour once the edit has stopped, which links it: a scene may not be changed from
# inside a listener, and a colour picker's drag sends many values.
_DIFFUSE_EDITED=set()


class DiffuseToColour(lxu.command.BasicCommand):
    def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg):return True
    def basic_Execute(self,msg,flags):
        import modo
        from moonray_modo.material_diffuse import from_diffuse
        held=list(_DIFFUSE_EDITED);_DIFFUSE_EDITED.clear()
        for identity in held:
            try:from_diffuse(modo.Scene().item(identity))
            except LookupError:pass

lx.bless(DiffuseToColour,'moonray.material.diffuseToColour')


def _diffuse_settled():
    try:
        from PySide2 import QtCore,QtWidgets
        import modo
        from moonray_modo.material_diffuse import differs
        if QtWidgets.QApplication.mouseButtons()!=QtCore.Qt.NoButton:
            _diffuse_settled.timer.start();return
        # Only a real difference makes a step: an undo leaves the two the same, and must keep what can be redone.
        scene=modo.Scene();found=False
        for identity in _DIFFUSE_EDITED:
            try:found=differs(scene.item(identity)) or found
            except LookupError:pass
        if found:lx.eval('moonray.material.diffuseToColour')
        else:
            _DIFFUSE_EDITED.clear()
            property_notifications.notify()
    except Exception as exc:
        _DIFFUSE_EDITED.clear()
        lx.out('A MoonRay material did not follow its diffuse: %s'%exc)


class _DiffuseWatcher(lxifc.SceneItemListener):
    def sil_ChannelValue(self,action,item,index):
        try:
            made=lx.object.Item(item)
            if not made.TestType(_DiffuseWatcher.material_type):return
            if not made.ChannelName(index).startswith('diffCol'):return
            _DIFFUSE_EDITED.add(made.Ident())
            if getattr(_diffuse_settled,'timer',None) is None:
                from PySide2 import QtCore
                _diffuse_settled.timer=QtCore.QTimer();_diffuse_settled.timer.setSingleShot(True);_diffuse_settled.timer.setInterval(200)
                _diffuse_settled.timer.timeout.connect(_diffuse_settled)
            _diffuse_settled.timer.start()
        except Exception:pass


try:
    _DiffuseWatcher.material_type=lx.service.Scene().ItemTypeLookup('advancedMaterial')
    _diffuse_watcher=_DiffuseWatcher()
    lx.service.Listener().AddListener(_diffuse_watcher)
except Exception as exc:
    lx.out('MoonRay materials will not follow their diffuse: %s'%exc)
