"""Which edits turn the sun of a physically based sky, and so wait for the mouse button before they are shown."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import incremental


class Item:
    def __init__(self,identity,kind,owners=()):
        self.id=identity;self.type=kind;self.owners=list(owners)
    def itemGraph(self,name):
        owners=self.owners
        class Graph:
            def forward(self):return owners
        return Graph()


class Scene:
    def __init__(self,*items):self.items={item.id:item for item in items}
    def item(self,identity):return self.items[identity]


class SkySun(unittest.TestCase):
    def setUp(self):
        self.sun=Item('sun','sunLight');self.lamp=Item('lamp','sunLight')
        self.scene=Scene(self.sun,self.lamp,Item('turn','rotation',[self.sun]),Item('other','rotation',[self.lamp]))
        self.sky={'environments':[{'layers':[{'kind':'physical','sun_identity':'sun'}]}]}

    def test_the_sun_of_the_sky_and_its_rotation_wait(self):
        self.assertTrue(incremental.moves_sky(self.scene,{'sun'},self.sky))
        self.assertTrue(incremental.moves_sky(self.scene,{'turn'},self.sky))

    def test_another_light_is_followed(self):
        self.assertFalse(incremental.moves_sky(self.scene,{'lamp'},self.sky))
        self.assertFalse(incremental.moves_sky(self.scene,{'other'},self.sky))

    def test_a_sky_that_is_not_physical_is_followed(self):
        plain={'environments':[{'layers':[{'kind':'grad4'}]}]}
        self.assertFalse(incremental.moves_sky(self.scene,{'sun','turn'},plain))
        self.assertFalse(incremental.moves_sky(self.scene,{'sun'},None))


if __name__=='__main__':unittest.main()
