"""Native Shader Tree Add Layer entry for a MoonShine material override."""
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
