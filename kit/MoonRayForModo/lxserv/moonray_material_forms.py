"""Typed property commands for native MoonRay materials, one per attribute of each shader.

A material's native values live in its MoonRay tag, where the graph editor also keeps them, so
these commands edit that one record. Each takes the kind of argument its attribute is, which is
what lets Modo draw a checkbox, a popup, a number field or a colour swatch for it.
tools/generate_material_item_forms.py writes the forms into material_forms.cfg, numbering the
commands as here and as moonray_material_properties.py does: shader i among the sorted names
after a blank first entry, attribute j in sorted order.
"""
import json
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxifc
import lxu.command
import lxu.package


class Hints(lxifc.UIValueHints):
    """What Modo needs to draw a control and keep it current: the events that mean its value
    may have changed, and for a popup its (internal name, label) entries, the argument's value
    being the entry's index. Modo only listens for events named here; a control with none kept
    showing the value it was first drawn with."""
    def __init__(self,notifiers,entries=()):self._notifiers,self._entries=notifiers,entries
    def uiv_Flags(self):return lx.symbol.fVALHINT_POPUPS if self._entries else 0
    def uiv_NotifierCount(self):return len(self._notifiers)
    def uiv_NotifierByIndex(self,index):return self._notifiers[index]
    def uiv_PopCount(self):return len(self._entries)
    def uiv_PopUserName(self,index):return self._entries[index][1]
    def uiv_PopInternalName(self,index):return self._entries[index][0]


def register():
    from moonray_modo import properties,shader_library,material_override,property_notifications,node_defaults
    from moonray_modo.materials import selected
    TYPES=['']+sorted(shader_library.catalog())

    def matching(shader):
        items=selected()
        if items and all(material_override.enabled(properties.read(item)) and
                         material_override.effective(properties.read(item)).get('native_shader')==shader for item in items):
            return items
        return []

    WATCHED=(('select.event','item +v'),(property_notifications.NAME,''))

    def command(shader,key,spec):
        kind=spec['type']
        try:default=node_defaults.value(spec)
        except ValueError:default=None
        enum=spec.get('enum')
        if enum:
            ordered=sorted(((int(v),str(k)) for k,v in enum.items()))
            numbers=[number for number,_ in ordered]
            labels=[(('choice%d'%number),' '.join(word.capitalize() for word in label.replace('_',' ').split())) for number,label in ordered]
        if kind=='Bool':how,argument='boolean',lx.symbol.sTYPE_BOOLEAN
        elif enum:how,argument='choice',lx.symbol.sTYPE_INTEGER
        elif kind in ('Int','Long'):how,argument='integer',lx.symbol.sTYPE_INTEGER
        elif kind in ('Float','Double'):how,argument='float',lx.symbol.sTYPE_FLOAT
        elif kind=='Rgb':how,argument='color',lx.symbol.sTYPE_COLOR
        else:how,argument='text',lx.symbol.sTYPE_STRING

        class Attribute(lxu.command.BasicCommand):
            def __init__(self):
                super().__init__()
                self.dyna_Add('value',argument)
                self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def basic_Enable(self,msg):return bool(matching(shader))
            def arg_UIValueHints(self,index):
                return Hints(WATCHED,labels if how=='choice' else ())
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                for item in matching(shader):
                    value=properties.read(item).get('native_parameters',{}).get(key,default)
                    if how=='boolean':values.AddInt(int(bool(value)))
                    elif how=='choice':values.AddInt(numbers.index(int(value)) if value is not None and int(value) in numbers else 0)
                    elif how=='integer':values.AddInt(int(value or 0))
                    elif how=='float':values.AddFloat(float(value or 0.0))
                    elif how=='color':
                        # The form Modo's own commands hand a colour over in.
                        held=lx.object.Value(values.AddEmptyValue())
                        held.SetString(' '.join('%.9g'%float(v) for v in (value or [0.0,0.0,0.0])))
                    elif value is None:values.AddString('')
                    else:values.AddString(value if kind=='String' else json.dumps(value))
            def basic_Execute(self,msg,flags):
                items=matching(shader)
                if not items:raise ValueError('Select a '+shader+' material')
                if how=='boolean':value=bool(self.dyna_Int(0))
                elif how=='choice':
                    index=self.dyna_Int(0)
                    if not 0<=index<len(numbers):raise ValueError('Invalid choice')
                    value=numbers[index]
                elif how=='integer':value=int(self.dyna_Int(0))
                elif how=='float':value=float(self.dyna_Float(0))
                elif how=='color':
                    value=[float(part) for part in self.dyna_String(0).replace(',',' ').split()[:3]]
                    if len(value)!=3:raise ValueError('Expected a colour')
                else:
                    text=self.dyna_String(0).strip()
                    value=None if not text else text if kind=='String' else json.loads(text)
                if value is not None:value=shader_library.typed(value,spec)
                # A value back at MoonRay's own default is not kept.
                if value is not None and default is not None and value==default:value=None
                updates=[]
                for item in items:
                    settings=properties.read(item);parameters=settings.setdefault('native_parameters',{})
                    if value is None:parameters.pop(key,None)
                    else:parameters[key]=value
                    graph=settings.get('node_graph')
                    if graph:
                        # The graph editor shows the same material; keep its output node in step.
                        root=graph['nodes'][graph['root']]
                        if value is None:root.setdefault('parameters',{}).pop(key,None)
                        else:root.setdefault('parameters',{})[key]=value
                        root.setdefault('inputs',{}).pop(key,None)
                    updates.append((item,settings))
                for item,settings in updates:properties.write(item,settings)
        return Attribute

    class Marker(lxu.package.BasicPackage):
        """Carries nothing; a material holds the one named for its shader, which is what the
        shader's form looks for."""
    for i,shader in enumerate(TYPES):
        if not shader:continue
        lx.bless(type('Marker'+shader,(Marker,),{}),properties.SHADER_PACKAGE+shader)
        for j,(key,spec) in enumerate(sorted(shader_library.catalog()[shader]['attributes'].items())):
            # Connections to other materials keep the graph editor's named inputs.
            if spec['type']=='SceneObject*':continue
            lx.bless(command(shader,key,spec),'moonray.material.attr%d_%d'%(i,j))


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay material forms are unavailable: %s'%exc)
    except Exception:pass
