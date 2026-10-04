"""Native Shader Tree Add Layer entry for a MoonShine material override."""
import lx
import lxu.package

class MoonShineLayer(lxu.package.DefaultPackage):
    pass

lx.bless(MoonShineLayer,'material.moonrayMoonShine',{
    lx.symbol.sPKG_SUPERTYPE:'advancedMaterial',
    lx.symbol.sSRV_USERNAME:'MoonShine Material Override',
    lx.symbol.sPKG_SHADER_NODE:'1'})
