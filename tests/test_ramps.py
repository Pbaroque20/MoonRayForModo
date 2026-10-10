"""Ramps found among a shader's attributes, and transforms taken apart and put together."""
import json,sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import ramps


class Ramps(unittest.TestCase):
    def test_the_ramps_of_the_materials_are_found(self):
        catalog=json.loads((root/'kit/MoonRayForModo/python/moonray_modo/material_catalog.json').read_text(encoding='utf-8'))
        found=ramps.groups(catalog['DwaToonMaterial']['attributes'])
        self.assertEqual(found['iridescence_positions'],('iridescence ramp','iridescence_positions','iridescence_colors','iridescence_interpolations'))
        self.assertEqual(found['positions'][0],'ramp')
        self.assertEqual(found['toon_specular_positions'][2],'toon_specular_values')

    def test_no_ramp_is_left_as_rows_of_numbers_in_the_forms(self):
        text=(root/'kit/MoonRayForModo/material_forms.cfg').read_text(encoding='utf-8')
        self.assertIn('Edit Iridescence Ramp...',text)
        for label in ('iridescence colors','iridescence positions','iridescence interpolations'):
            self.assertNotIn('>'+label+'<',text)

    def test_a_transform_comes_apart_and_goes_back_together(self):
        for move,turn,size in (([0,0,0],[0,0,0],[1,1,1]),([1,-2,3.5],[30,-45,120],[2,.5,3]),([0,1,0],[10,90,0],[1,1,1]),([0,0,0],[-170,20,-95],[1,4,1])):
            made=ramps.matrix(move,turn,size)
            back=ramps.parts(made)
            self.assertIsNotNone(back)
            for a,b in zip(ramps.matrix(*back),made):self.assertAlmostEqual(a,b,places=6)
            for a,b in zip(back[2],size):self.assertAlmostEqual(a,b,places=6)
        again=ramps.parts(ramps.matrix([1,2,3],[30,-45,120],[2,.5,3]))
        for a,b in zip(again[1],[30,-45,120]):self.assertAlmostEqual(a,b,places=5)

    def test_what_a_move_a_turn_and_a_size_cannot_say_is_left_alone(self):
        sheared=[1,0,0,0, .5,1,0,0, 0,0,1,0, 0,0,0,1]
        mirrored=[-1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
        self.assertIsNone(ramps.parts(sheared));self.assertIsNone(ramps.parts(mirrored));self.assertIsNone(ramps.parts([1,2,3]))
        self.assertEqual(ramps.words(ramps.matrix([0,0,0],[0,0,0],[1,1,1])),'Not moved, turned or sized')
        self.assertEqual(ramps.words(ramps.matrix([1,0,2],[0,0,0],[1,1,1])),'Move 1 0 2')


if __name__=='__main__':unittest.main()
