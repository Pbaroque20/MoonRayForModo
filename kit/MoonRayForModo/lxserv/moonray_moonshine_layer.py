"""Shader Tree Add Layer entries: the MoonShine material override, and MoonRay's own materials."""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
import lxu.command
import lxu.package

class MoonShineLayer(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors):
    def test_parent(self,item,parent):return True
    def synth_name(self,item):
        return 'MoonShine Material Override'


lx.bless(MoonShineLayer,'material.moonrayMoonShine',{
    lx.symbol.sPKG_SUPERTYPE:'advancedMaterial',
    lx.symbol.sSRV_USERNAME:'MoonShine Material Override',
    lx.symbol.sPKG_SHADER_NODE:'1'})


# One entry per native MoonRay material, for the Shader Tree's Add Layer list. An item of one
# of these types is that material: its type names its shader, and it has the same form and
# graph as a material assigned to a mesh.
def register():
    from moonray_modo import properties,shader_library

    def layer(shader):
        class Layer(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors):
            def test_parent(self,item,parent):return True
            def synth_name(self,item):return shader
        return Layer

    class MaterialXMaterial(lxu.package.BasicPackage, lxu.package.BasicItemBehaviors):
        """A material brought in from a MaterialX file, under a type of its own so that it can be told from the rest."""
        def test_parent(self,item,parent):return True
        def synth_name(self,item):return 'MaterialX Material'
    lx.bless(MaterialXMaterial,properties.MATERIALX_TYPE,{
        lx.symbol.sPKG_SUPERTYPE:'advancedMaterial',
        lx.symbol.sSRV_USERNAME:'MaterialX Material',
        lx.symbol.sPKG_SHADER_NODE:'1'})

    for shader in sorted(shader_library.catalog()):
        lx.bless(layer(shader),properties.LAYER_PREFIX+shader,{
            lx.symbol.sPKG_SUPERTYPE:'advancedMaterial',
            lx.symbol.sSRV_USERNAME:shader,
            lx.symbol.sPKG_SHADER_NODE:'1'})

    # The Shader Tree's Add Layer list holds what Modo's shading knows how to make: its own layers, and the custom
    # materials and textures that plug-ins serve. A MoonRay material is an item type of the kit's, a kind of Modo's
    # material, and is never listed. So each has an entry that is listed, under Custom Materials: a custom material
    # server that does nothing but stand there. Choosing it makes an item of the entry, which at once gives its place
    # to the MoonRay material it stands for.
    class FromEntry(lxu.command.BasicCommand):
        """Put a MoonRay material where an Add Layer entry for it was made, and take the entry away."""
        def __init__(self):
            super().__init__()
            self.dyna_Add('entry',lx.symbol.sTYPE_STRING)
            self.dyna_Add('type',lx.symbol.sTYPE_STRING)
        def cmd_Flags(self):return lx.symbol.fCMD_MODEL|lx.symbol.fCMD_UNDO
        def basic_Enable(self,msg):return True
        def basic_Execute(self,msg,flags):
            import modo
            scene=modo.Scene()
            try:made=scene.item(self.dyna_String(0))
            except LookupError:return
            parent,place=made.parent,made.parentIndex
            material=scene.addItem(self.dyna_String(1))
            if parent is not None:material.setParent(parent,place if place is not None else 0)
            scene.removeItems(made)
            # It starts on Modo's diffuse, as an assigned material does (material_diffuse).
            from moonray_modo.material_diffuse import colour_key,diffuse,with_colour
            settings=properties.read(material);key=colour_key(settings.get('native_shader') or '')
            if key:properties.write(material,with_colour(settings,key,diffuse(material)))
            scene.select(material)
    lx.bless(FromEntry,'moonray.material.fromEntry')

    import lxifc
    class Entry(lxifc.CustomMaterial):
        """An entry in Add Layer. It has no channels and shades nothing: it is replaced as soon as it is made."""
        def cmt_SetupChannels(self,addChan):pass
        def cmt_LinkChannels(self,eval,item):pass
        def cmt_ReadChannels(self,attr,data):pass

    stands_for={properties.ENTRY_PREFIX+shader:properties.LAYER_PREFIX+shader for shader in sorted(shader_library.catalog())}
    stands_for[properties.ENTRY_PREFIX+'MaterialX']=properties.MATERIALX_TYPE
    for kind in stands_for:
        # Modo names the item type of a custom material after its server, with material. before it.
        lx.bless(type('Entry_'+kind.rsplit('.',1)[-1],(Entry,),{}),kind[len('material.'):],{lx.symbol.sSRV_USERNAME:kind[len(properties.ENTRY_PREFIX):]})

    def swap(identity,real):
        try:lx.eval('moonray.material.fromEntry {%s} {%s}'%(identity,real))
        except RuntimeError:pass

    class Watcher(lxifc.SceneItemListener):
        """Sees an entry made, and has the material put in its place once Modo has finished making it: a scene may
        not be changed from inside the making of an item."""
        def sil_ItemAdd(self,item):
            try:
                made=lx.object.Item(item)
                real=stands_for.get(lx.service.Scene().ItemTypeName(made.Type()))
                if real:
                    from PySide2 import QtCore
                    identity=made.Ident()
                    QtCore.QTimer.singleShot(0,lambda:swap(identity,real))
            except Exception:pass
    # Kept, or the listener is let go of as soon as this function returns.
    register.watcher=Watcher()
    lx.service.Listener().AddListener(register.watcher)


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay Add Layer entries are unavailable: %s'%exc)
    except Exception:pass
