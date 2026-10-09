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


class Surroundings(unittest.TestCase):
    def scene(self,direction=(0,1,0),turn=0.0,lamp=1.0):
        return {'environments':[{'kind':'stack','layers':[{'kind':'physical','sun_identity':'sun','sun_direction':list(direction)}]}],
                'entities':[{'class':'EnvLight','matrix':[turn]*16},{'class':'RectLight','matrix':[lamp]*16}],
                'lights':[{'identity':'lamp','intensity':lamp}]}

    def test_a_sun_moved_or_an_environment_light_turned_changes_them(self):
        base=incremental.surroundings(self.scene())
        self.assertNotEqual(base,incremental.surroundings(self.scene(direction=(1,0,0))))
        self.assertNotEqual(base,incremental.surroundings(self.scene(turn=.5)))

    def test_another_light_does_not(self):
        self.assertEqual(incremental.surroundings(self.scene()),incremental.surroundings(self.scene(lamp=3.0)))
        self.assertEqual(incremental.surroundings({}),incremental.surroundings({'lights':[1]}))


if __name__=='__main__':unittest.main()
