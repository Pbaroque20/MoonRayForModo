"""Shader Tree Add Layer entries: the MoonShine material override, and MoonRay's own materials."""
import os
import sys
package_root=os.path.join(os.path.dirname(os.path.dirname(__file__)),"python")
if package_root not in sys.path: sys.path.insert(0,package_root)
import lx
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


# A fault here must not keep the rest of the kit from loading.
try:register()
except Exception as exc:
    try:lx.out('MoonRay Add Layer entries are unavailable: %s'%exc)
    except Exception:pass
