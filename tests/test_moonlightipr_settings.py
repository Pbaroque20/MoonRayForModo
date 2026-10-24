"""What of the scene's render settings and of a material's kind reaches MoonLightIPR; run outside Modo, no GPU needed."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials,moonlightipr_scene


def scene(**settings):
    return {'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,1,5,1],'focal_mm':50.0,'film_mm':36.0},
            'materials':{'':{'color':[.5,.5,.5],'roughness':.6}},
            'meshes':[{'name':'Quad','identity':'quad','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],'faces':[[0,3,2,1]]}],
            'lights':[],'environments':[],'render_settings':settings}


def header(packed):
    """The scene's flags, then its sample clamp and the bounce the clamp holds from."""
    flags=struct.unpack_from('<I',packed,4+7*4)[0]
    clamp,depth=struct.unpack_from('<fI',packed,4+8*4)
    return flags,clamp,depth


class SceneSettings(unittest.TestCase):
    def test_presence_shadows_are_off_unless_the_scene_asks(self):
        # MoonRay has a see-through surface cast a whole shadow unless enable_presence_shadows is set.
        flags,_,_=header(moonlightipr_scene.pack(scene(),320,180)[0])
        self.assertFalse(flags&moonlightipr_scene.SCENE_PRESENCE_SHADOWS)
        flags,_,_=header(moonlightipr_scene.pack(scene(enable_presence_shadows=1),320,180)[0])
        self.assertTrue(flags&moonlightipr_scene.SCENE_PRESENCE_SHADOWS)

    def test_the_sample_clamp_is_the_scenes(self):
        _,clamp,depth=header(moonlightipr_scene.pack(scene(),320,180)[0])
        self.assertEqual((clamp,depth),(10.0,1))    # MoonRay's own, where the scene says nothing
        _,clamp,depth=header(moonlightipr_scene.pack(scene(sample_clamping_value=0.0,sample_clamping_depth=2),320,180)[0])
        self.assertEqual((clamp,depth),(0.0,2))


class MaterialKinds(unittest.TestCase):
    """A material that goes to MoonRay as a Dwa material is plain diffuse by bounced light, as DwaBaseMaterial is
    unless told to cast caustics; one that goes as UsdPreviewSurface is not."""
    def flags(self,material):
        compiler=moonlightipr_materials.Compiler()
        record=compiler.material(material,'tested')
        # The flags come after the material's 46 numbers (the clearcoat bump strength the last of them).
        return struct.unpack_from('<I',record,46*4)[0]

    def test_a_stack_is_a_dwa_material(self):
        row={'color':[.8,.2,.1],'roughness':.3,'standard_material':True,'layers':[],'material_groups':[]}
        self.assertTrue(self.flags({'material_stack':[row]})&moonlightipr_materials.MATERIAL_NO_CAUSTICS)

    def test_a_plain_material_is_not(self):
        self.assertFalse(self.flags({'color':[.8,.2,.1],'roughness':.3})&moonlightipr_materials.MATERIAL_NO_CAUSTICS)


if __name__=='__main__':unittest.main()
