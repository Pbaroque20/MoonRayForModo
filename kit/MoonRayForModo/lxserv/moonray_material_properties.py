"""Native Modo material dropdown and schema-filtered property commands."""
import json
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command
from moonray_modo import properties,shader_library
from moonray_modo.materials import selected

TYPES=['']+sorted(shader_library.catalog())


class Observed(lxu.command.BasicCommand):
    def basic_Notifier(self,index):
        if index==0: return ('select.event','item +v')
        if index==1: return ('scene.edit','')


class MaterialType(Observed):
    def __init__(self):
        super().__init__()
        self.dyna_Add('type',lx.symbol.sTYPE_INTEGER)
        self.dyna_SetHint(0,tuple((i,name or 'Modo controls') for i,name in enumerate(TYPES)))
        self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg): return bool(selected())
    def cmd_Query(self,index,query):
        values=lx.object.ValueArray(query)
        for item in selected():
            shader=properties.read(item).get('native_shader','')
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
            settings['native_shader']=shader
            settings['native_parameters']=shader_library.validate(shader,presets.get(shader,{})) if shader else {}
            if shader: settings['shader']='DwaBaseMaterial'
            properties.write(item,settings)


def filter_command(shader):
    class Filter(Observed):
        def cmd_Flags(self): return lx.symbol.fCMD_UI
        def basic_Enable(self,msg):
            items=selected()
            return bool(items) and all(properties.read(item).get('native_shader','')==shader for item in items)
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
            return bool(items) and all(properties.read(item).get('native_shader')==shader for item in items)
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


class OpenNodes(Observed):
    def cmd_Flags(self): return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
    def basic_Enable(self,msg): return len(selected())==1
    def basic_Execute(self,msg,flags):
        from moonray_modo.node_editor import Editor
        items=selected()
        if len(items)!=1: raise ValueError('Select one Shader Tree material')
        Editor(items[0]).exec_()


class NodeOverride(OpenNodes):
    def basic_Enable(self,msg): return True
    def basic_Execute(self,msg,flags):
        import modo
        lx.eval('shader.create material.moonrayMaterialX')
        items=[item for item in modo.Scene().selected if item.type=='material.moonrayMaterialX']
        if len(items)!=1: raise ValueError('Could not identify the new MaterialX Override layer')
        properties.write(items[0],{'materialx_override':False})
        items[0].name='MaterialX Override'

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
            from moonray_modo.node_editor import Editor
            Editor(item,materialx_override=True).exec_()
        else:
            settings=properties.read(item);settings['materialx_override']=False;properties.write(item,settings)


class EditMaterialX(OpenNodes):
    def basic_Enable(self,msg): return len(selected())==1 and selected()[0].type=='material.moonrayMaterialX'
    def basic_Execute(self,msg,flags):
        from moonray_modo.node_editor import Editor
        items=selected()
        if len(items)!=1 or items[0].type!='material.moonrayMaterialX': raise ValueError('Select one MaterialX Override layer')
        Editor(items[0],materialx_override=True).exec_()

lx.bless(MaterialXOverride,'moonray.material.materialxOverride')
lx.bless(EditMaterialX,'moonray.material.editMaterialX')


class RegularMaterialFilter(Observed):
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self,msg):
        items=selected()
        return bool(items) and all(item.type=='advancedMaterial' for item in items)
    def basic_Execute(self,msg,flags): pass

lx.bless(RegularMaterialFilter,'moonray.material.regularFilter')
