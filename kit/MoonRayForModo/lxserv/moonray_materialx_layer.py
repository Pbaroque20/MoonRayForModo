"""Dedicated Shader Tree layer, automatically listed by shader.create/Add Layer."""
import lx
import lxu.package

class MaterialXLayer(lxu.package.DefaultPackage):
    pass

lx.bless(MaterialXLayer,'material.moonrayMaterialX',{
    lx.symbol.sPKG_SUPERTYPE:'advancedMaterial',
    lx.symbol.sSRV_USERNAME:'MaterialX Override',
    lx.symbol.sPKG_SHADER_NODE:'1'})
