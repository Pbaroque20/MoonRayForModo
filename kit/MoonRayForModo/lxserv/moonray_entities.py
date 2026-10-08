"""MoonRay's own scene objects as Modo items: one item type per class, and their commands.

Each class in entity_catalog.json becomes a locator-based item type, moonray.<Class>, whose
channels are that class's attributes, so Modo draws its own controls for them: swatches for
colours, checkboxes and number fields. Commands add what a channel alone cannot: popups with
named choices, pickers for the other MoonRay items an attribute refers to, and file browsers.
tools/generate_entity_forms.py writes the menu and the forms into entities.cfg, numbering the
commands as here: class i in sorted order, attribute j in the order of entities.channels.
"""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxifc
import lxu.command
import lxu.package


class Popup(lxifc.UIValueHints):
    """A popup of (internal name, label) entries; the argument's value is the entry's index."""
    def __init__(self,entries):self._entries=entries
    def uiv_Flags(self):return lx.symbol.fVALHINT_POPUPS
    def uiv_PopCount(self):return len(self._entries)
    def uiv_PopUserName(self,index):return self._entries[index][1]
    def uiv_PopInternalName(self,index):return self._entries[index][0]


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

    def instance(name):
        """The item in the viewport: a wireframe that follows the attributes giving its size."""
        inputs=entities.proxy_inputs(name)
        def point3(values):
            # The form Modo's own drawing example hands to Vertex.
            import modo
            return modo.Vector3(float(values[0]),float(values[1]),float(values[2]))
        defaults={key:(value if not isinstance(value,list) else None) for key,_,_,value,_ in entities.channels(name)}
        class Drawn(lxu.package.BasicPackageInstance, lxifc.ViewItem3D):
            def vitm_WorldSpace(self):
                # Drawn in the item's own space, so the shape moves, turns and scales with it.
                return False
            def vitm_Draw(self,chanRead,strokeDraw,selectionFlags,itemColor):
                # Nothing here may raise: a fault while drawing would repeat on every redraw.
                try:
                    read=lx.object.ChannelRead(chanRead);stroke=lx.object.StrokeDraw(strokeDraw)
                    values={}
                    for key,channel in inputs:
                        try:values[key]=float(read.Double(self.item,self.item.ChannelLookup(channel)))
                        except Exception:values[key]=float(defaults.get(key.split('.')[0]) or 1.0)
                    for kind,data in entities.proxy(name,lambda key:values.get(key,1.0)):
                        if kind=='circles':
                            stroke.Begin(lx.symbol.iSTROKE_CIRCLES,itemColor,1.0)
                            for centre,normal in data:
                                stroke.Vertex(point3(centre),lx.symbol.iSTROKE_ABSOLUTE)
                                stroke.Vertex(point3(normal),lx.symbol.iSTROKE_ABSOLUTE)
                        elif kind=='boxes':
                            stroke.Begin(lx.symbol.iSTROKE_BOXES,itemColor,1.0)
                            for low,high in data:
                                stroke.Vertex(point3(low),lx.symbol.iSTROKE_ABSOLUTE)
                                stroke.Vertex(point3(high),lx.symbol.iSTROKE_ABSOLUTE)
                        else:
                            stroke.Begin(lx.symbol.iSTROKE_LINES if kind=='lines' else lx.symbol.iSTROKE_LINE_STRIP,itemColor,1.0)
                            for point in data:stroke.Vertex(point3(point),lx.symbol.iSTROKE_ABSOLUTE)
                except Exception:pass
        return Drawn

    def package(name):
        plan=entities.channels(name)
        Drawn=instance(name)
        floors={channel:entities.limits(name,key) for key,channel,kind,default,choices in plan if entities.limits(name,key) is not None}
        class Typed(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors, lxifc.ChannelUI):
            def test_parent(self,item,parent):return True
            def pkg_Attach(self):return Drawn(self.acts)
            def pkg_TestInterface(self,guid):return guid==lx.symbol.u_PACKAGEINSTANCE or guid==lx.symbol.u_VIEWITEM3D
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
            def cui_UIHints(self,channelName,hints):
                # Lengths, sizes and angles stop at zero in the form.
                if channelName in floors:
                    try:lx.object.UIHints(hints).MinFloat(float(floors[channelName]))
                    except Exception:pass
                return lx.result.OK
        return Typed

    def chosen(name):
        import modo
        return [item for item in modo.Scene().selected if item.type==entities.item_type(name)]

    def kinds(category):
        """The classes of a kind: a category by name, or the classes themselves."""
        return entities.classes(category) if isinstance(category,str) else list(category)

    def candidates(category,excluding=()):
        """The names of the scene's MoonRay items of one kind, for a picker."""
        import modo
        scene=modo.Scene();names=[]
        if category=='mesh':
            # A mesh light emits from a real mesh, so these are the scene's Modo meshes.
            return sorted({item.name for item in scene.items('mesh',superType=False)})
        for name in kinds(category):
            try:names+=[item.name for item in scene.items(entities.item_type(name),superType=False) if item.id not in excluding]
            except (LookupError,RuntimeError,TypeError):pass
        return sorted(set(names))

    class Listed(lxu.command.BasicCommand):
        """A command with one queried popup argument that follows the selection."""
        def __init__(self):
            super().__init__()
            self.dyna_Add('value',lx.symbol.sTYPE_INTEGER)
            self.basic_SetFlags(0,lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def cmd_NotifyAddClient(self,argidx,client):
            if not getattr(self,'_notifications',None):
                self._notifications=lxu.command.NotifierHost()
                self._notifications.add('select.event','item +v')
            self._notifications.add_client(client)
        def cmd_NotifyRemoveClient(self,client):
            if getattr(self,'_notifications',None):self._notifications.rem_client(client)

    def text(item,channel):
        try:return str(item.channel(channel).get() or '').strip()
        except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):return ''

    def choice_command(name,key,channel):
        """A popup for an attribute with named values."""
        labels=entities.choice_labels(name,key)
        numbers=[number for number,_,_ in labels]
        class Choice(Listed):
            def arg_UIValueHints(self,index):return Popup([(internal,label) for _,internal,label in labels])
            def basic_Enable(self,msg):return bool(chosen(name))
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                for item in chosen(name):
                    try:value=int(item.channel(channel).get())
                    except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):value=numbers[0]
                    values.AddInt(numbers.index(value) if value in numbers else 0)
            def basic_Execute(self,msg,flags):
                index=self.dyna_Int(0)
                if not 0<=index<len(numbers):raise ValueError('Invalid choice')
                for item in chosen(name):item.channel(channel).set(numbers[index])
        return Choice

    def spaced(name):
        """EnvLight -> Env Light, for a popup entry."""
        words=''
        for c in name.replace('_',' '):
            if c.isupper() and words and words[-1].islower():words+=' '
            words+=c
        return words

    def create(category,index):
        """Add a new MoonRay item of the index-th class of a kind, under a name no other item has."""
        import modo
        scene=modo.Scene();name=kinds(category)[index]
        taken={item.name for item in scene.items()}
        label,count=entities.display(name),1
        while label in taken:
            count+=1;label='%s %d'%(entities.display(name),count)
        item=scene.addItem(entities.item_type(name),name=label)
        for key,value in entities.STARTING.get(name,{}).items():
            try:item.channel(entities.CHANNEL_PREFIX+key).set(value)
            except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):pass
        return item.name

    def offered(category,held=()):
        """What a picker lists: the scene's items of the kind, then one entry per class to make a new one."""
        existing=[n for n in candidates(category,{item.id for owner in entities.classes() for item in chosen(owner)}) if n not in held]
        return existing,([] if category=='mesh' else ['New '+entities.display(n) for n in kinds(category)])

    def pick_command(name,channel,category):
        """A popup of the MoonRay items an attribute can point at: none, those in the scene, or a new one."""
        class Pick(Listed):
            def arg_UIValueHints(self,index):
                existing,fresh=offered(category)
                return Popup([('none','(none)')]+[('item%d'%i,label) for i,label in enumerate(existing)]
                             +[('new%d'%i,label) for i,label in enumerate(fresh)])
            def basic_Enable(self,msg):return bool(chosen(name))
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query);existing,_=offered(category)
                for item in chosen(name):
                    current=text(item,channel)
                    values.AddInt(existing.index(current)+1 if current in existing else 0)
            def basic_Execute(self,msg,flags):
                existing,fresh=offered(category);index=self.dyna_Int(0)
                if not 0<=index<=len(existing)+len(fresh):raise ValueError('That item is no longer in the scene')
                items=chosen(name)
                value='' if index==0 else existing[index-1] if index<=len(existing) else create(category,index-1-len(existing))
                for item in items:item.channel(channel).set(value)
        return Pick

    def held_names(item,channel):
        return [part.strip() for part in text(item,channel).split(',') if part.strip()]

    def append_command(name,channel,category):
        """A popup that attaches one more MoonRay item, from the scene or newly made, to an
        attribute that holds several."""
        class Append(Listed):
            def lists(self):
                items=chosen(name)
                return offered(category,held_names(items[0],channel) if len(items)==1 else ())
            def arg_UIValueHints(self,index):
                existing,fresh=self.lists()
                return Popup([('choose','(choose)')]+[('item%d'%i,label) for i,label in enumerate(existing)]
                             +[('new%d'%i,label) for i,label in enumerate(fresh)])
            def basic_Enable(self,msg):return bool(chosen(name))
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                for item in chosen(name):values.AddInt(0)
            def basic_Execute(self,msg,flags):
                existing,fresh=self.lists();index=self.dyna_Int(0)-1
                if index<0:return
                if index>=len(existing)+len(fresh):raise ValueError('That item is no longer in the scene')
                items=chosen(name)
                added=existing[index] if index<len(existing) else create(category,index-len(existing))
                for item in items:
                    held=held_names(item,channel)
                    if added not in held:item.channel(channel).set(', '.join(held+[added]))
        return Append

    def remove_command(name,channel):
        """A popup that detaches one of the items an attribute holds; the item itself stays in the scene."""
        class Remove(Listed):
            def held(self):
                names=[]
                for item in chosen(name):names+=[n for n in held_names(item,channel) if n not in names]
                return names
            def arg_UIValueHints(self,index):
                return Popup([('choose','(choose)')]+[('item%d'%i,label) for i,label in enumerate(self.held())])
            def basic_Enable(self,msg):return bool(self.held())
            def cmd_Query(self,index,query):
                values=lx.object.ValueArray(query)
                for item in chosen(name):values.AddInt(0)
            def basic_Execute(self,msg,flags):
                names=self.held();index=self.dyna_Int(0)-1
                if index<0:return
                if index>=len(names):raise ValueError('That item is no longer attached')
                for item in chosen(name):
                    item.channel(channel).set(', '.join(n for n in held_names(item,channel) if n!=names[index]))
        return Remove

    def browse_command(name,channel,label):
        """A file dialog whose answer goes into a path attribute."""
        class Browse(lxu.command.BasicCommand):
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def basic_Enable(self,msg):return bool(chosen(name))
            def basic_Execute(self,msg,flags):
                import modo
                items=chosen(name)
                if not items:return
                # Images or volume files by what the attribute is for, with every file as the other choice.
                wanted=(('vdb','OpenVDB files','*.vdb') if 'vdb' in channel or channel.endswith('model') else
                        ('images','Images','*.exr;*.hdr;*.tx;*.tif;*.tiff;*.png;*.jpg;*.jpeg;*.tga'))
                try:path=modo.dialogs.customFile('fileOpen','Choose '+label,(wanted[0],'all'),(wanted[1],'All files'),(wanted[2],'*.*'))
                except RuntimeError:return
                if not path:return
                for item in items:item.channel(channel).set(str(path).replace('\\','/'))
        return Browse

    def load_vdb(item,path):
        """Give a VDB shape its file, and what it needs to show as one: the file's first grid as its density, and
        a VDB volume inside it. Without the volume the shape renders as nothing, or as the box it sits in."""
        import modo
        prefix=entities.CHANNEL_PREFIX;scene=modo.Scene()
        item.channel(prefix+'model').set(str(path).replace(chr(92),'/'))
        grids=entities.vdb_grids(str(path))
        if grids and text(item,prefix+'density_grid') not in grids:
            item.channel(prefix+'density_grid').set('density' if 'density' in grids else grids[0])
        for other in ('emission_grid','velocity_grid'):
            if text(item,prefix+other) and text(item,prefix+other) not in grids:item.channel(prefix+other).set('')
        if not text(item,prefix+'modo_volume'):
            taken={other.name for other in scene.items()}
            label,count='VDB Volume',1
            while label in taken:
                count+=1;label='VDB Volume %d'%count
            volume=scene.addItem(entities.item_type('VdbVolume'),name=label)
            item.channel(prefix+'modo_volume').set(volume.name)

    def scene_names(mode,item,channel):
        """What there is to choose from for an attribute that used to be typed."""
        import modo
        scene=modo.Scene()
        if mode=='grid':
            # The grids of the item's own volume file; the usual names until it has one that can be read.
            source=text(item,entities.CHANNEL_PREFIX+('model' if item.type==entities.item_type('VdbGeometry') else 'vdb_map'))
            return entities.vdb_grids(source) or ['density','temperature','flame','vel']
        if mode=='label':
            found=set()
            for owner in entities.classes():
                if channel[len(entities.CHANNEL_PREFIX):] not in entities.catalog()[owner]['attributes']:continue
                try:found.update(text(other,channel) for other in scene.items(entities.item_type(owner),superType=False))
                except (LookupError,RuntimeError,TypeError):pass
            return sorted(found-{''})
        if mode=='material':
            found=set()
            for mask in scene.items('mask'):
                try:found.add(str(mask.channel('ptag').get() or ''))
                except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):pass
            return sorted(found-{''})
        if mode=='uv':
            found=set()
            for mesh in scene.items('mesh',superType=False):
                try:found.update(vmap.name for vmap in mesh.geometry.vmaps.uvMaps)
                except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):pass
            return sorted(found)
        return []

    def option_command(name,channel,mode,label):
        """A popup in place of a box to type in: a file from a dialog, a grid of the volume file, a name
        already in use (or a new one), a material or a UV map of the scene."""
        action={'file':'Choose file...','label':'New label...'}.get(mode)
        class Option(Listed):
            def values(self):
                items=chosen(name)
                if not items:return []
                current=text(items[0],channel)
                found=[] if mode=='file' else scene_names(mode,items[0],channel)
                return found+([current] if current and current not in found else [])
            def shown(self,value):
                return value.replace('\\','/').rsplit('/',1)[-1] if mode=='file' else value
            def arg_UIValueHints(self,index):
                values=self.values()
                return Popup([('none','(none)')]+[('value%d'%i,self.shown(v)) for i,v in enumerate(values)]+([('action',action)] if action else []))
            def basic_Enable(self,msg):return bool(chosen(name))
            def cmd_Query(self,index,query):
                held=lx.object.ValueArray(query);values=self.values()
                for item in chosen(name):
                    current=text(item,channel)
                    held.AddInt(values.index(current)+1 if current in values else 0)
            def basic_Execute(self,msg,flags):
                values=self.values();index=self.dyna_Int(0);items=chosen(name)
                if not items or index<0:return
                if index==0:value=''
                elif index<=len(values):value=values[index-1]
                elif mode=='file':
                    import modo
                    # Images or volume files by what the attribute is for, with every file as the other choice.
                    wanted=(('vdb','OpenVDB files','*.vdb') if 'vdb' in channel or channel.endswith('model') else
                            ('images','Images','*.exr;*.hdr;*.tx;*.tif;*.tiff;*.png;*.jpg;*.jpeg;*.tga'))
                    try:path=modo.dialogs.customFile('fileOpen','Choose '+label,(wanted[0],'all'),(wanted[1],'All files'),(wanted[2],'*.*'))
                    except RuntimeError:return
                    if not path:return
                    value=str(path).replace('\\','/')
                    if name=='VdbGeometry' and channel==entities.CHANNEL_PREFIX+'model':
                        for item in items:load_vdb(item,value)
                        return
                else:
                    from PySide2 import QtWidgets
                    typed,accepted=QtWidgets.QInputDialog.getText(None,'New '+label,'Letters, numbers and underscores:')
                    value=''.join(c for c in str(typed).strip().replace(' ','_') if c.isalnum() or c=='_')
                    if not accepted or not value:return
                for item in items:item.channel(channel).set(value)
        return Option

    def ramp_command(name,label,keys):
        """Opens the ramp editor on the three lists that make one ramp."""
        attributes=entities.catalog()[name]['attributes']
        kinds=[attributes[key]['type'] for key in keys]
        channels=[entities.CHANNEL_PREFIX+key for key in keys]
        class Ramp(lxu.command.BasicCommand):
            def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
            def basic_Enable(self,msg):return len(chosen(name))==1
            def basic_Execute(self,msg,flags):
                items=chosen(name)
                if len(items)!=1:return
                from moonray_modo import ramp_editor
                texts=ramp_editor.edit(label,kinds,[text(items[0],channel) for channel in channels])
                if texts is None:return
                for channel,value in zip(channels,texts):items[0].channel(channel).set(value)
        return Ramp

    for i,name in enumerate(entities.classes()):
        for k,(label,positions,values,interpolations) in enumerate(entities.RAMPS.get(name,[])):
            lx.bless(ramp_command(name,label,(positions,values,interpolations)),'moonray.entity.ramp%d_%d'%(i,k))

    for i,name in enumerate(entities.classes()):
        attributes=entities.catalog()[name]['attributes']
        for j,(key,channel,kind,default,choices) in enumerate(entities.channels(name)):
            spec=attributes[key];category=entities.reference_category(spec);shown=entities.presentation(name,key)
            if shown in ('file','grid','label','material','uv'):
                lx.bless(option_command(name,channel,shown,spec.get('label',key.replace('_',' '))),'moonray.entity.option%d_%d'%(i,j))
            elif shown in ('hidden','ramp'):pass
            elif choices:lx.bless(choice_command(name,key,channel),'moonray.entity.choice%d_%d'%(i,j))
            elif category and spec['type']=='SceneObject*':
                # A portal shows an environment or a distant light, not any light.
                if (name,key)==('PortalLight','light'):category=('EnvLight','DistantLight')
                # And only a real mesh can be a mesh light's surface, or a bake camera's subject.
                if key=='geometry':category="mesh"
                lx.bless(pick_command(name,channel,category),'moonray.entity.pick%d_%d'%(i,j))
            elif category:
                lx.bless(append_command(name,channel,category),'moonray.entity.append%d_%d'%(i,j))
                lx.bless(remove_command(name,channel),'moonray.entity.remove%d_%d'%(i,j))

    for name in entities.classes():
        lx.bless(package(name),entities.item_type(name),{lx.symbol.sPKG_SUPERTYPE:'locator',lx.symbol.sSRV_USERNAME:entities.display(name)})

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
            item=scene.addItem(entities.item_type(name),name=entities.display(name))
            # MoonRay's own starting values make some items do nothing visible; begin with ones that show.
            for key,value in entities.STARTING.get(name,{}).items():
                try:item.channel(entities.CHANNEL_PREFIX+key).set(value)
                except (TypeError,ValueError,AttributeError,LookupError,RuntimeError):pass
            if name=='VdbGeometry':
                # A VDB shape is nothing without its file: ask for it now, and set up what shows it.
                try:path=modo.dialogs.customFile('fileOpen','Choose a VDB file',('vdb','all'),('OpenVDB files','All files'),('*.vdb','*.*'))
                except RuntimeError:path=None
                if path:load_vdb(item,path)
            scene.select(item)

    lx.bless(Add,'moonray.entity.add')

    class LoadVdb(lxu.command.BasicCommand):
        """Give the selected VDB shapes a file, by path: what choosing one in the properties does, for scripts."""
        def __init__(self):
            super().__init__()
            self.dyna_Add('file',lx.symbol.sTYPE_STRING)
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def basic_Enable(self,msg):return bool(chosen('VdbGeometry'))
        def basic_Execute(self,msg,flags):
            for item in chosen('VdbGeometry'):load_vdb(item,self.dyna_String(0))

    lx.bless(LoadVdb,'moonray.entity.loadVdb')


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay items are unavailable: %s'%exc)
    except Exception:pass
