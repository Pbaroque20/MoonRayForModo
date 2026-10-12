"""Modo's shading models as the lobe, roughness and strength MoonRay draws them with."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import shading_models


class ShadingModels(unittest.TestCase):
    def test_gtr_and_principled_pass_as_they_are(self):
        for model in ('principled','something else'):
            self.assertEqual(shading_models.translated(model,.37),(.37,1.0,False))
        # GTR is MoonRay's own lobe at its own roughness from the middle up, and wider where it is smooth.
        found=shading_models.translated('gtr',.5)
        self.assertAlmostEqual(found[0],.5);self.assertEqual(found[1:],(1.0,False))
        self.assertAlmostEqual(shading_models.translated('gtr',.1)[0],.16)
        self.assertLess(shading_models.translated('gtr',.9)[1],1.0)

    def test_blinn_and_ashikhmin_are_beckmann_at_the_measured_values(self):
        for model,rows in shading_models.MEASURED.items():
            for rough,to,strength in rows:
                found=shading_models.translated(model,rough)
                self.assertAlmostEqual(found[0],to);self.assertAlmostEqual(found[1],strength);self.assertEqual(found[2],model in ('blinn','ashikhmin'))

    def test_between_and_beyond_what_was_measured(self):
        low,mid,high=(shading_models.translated('blinn',r) for r in (.2,.275,.35))
        self.assertAlmostEqual(mid[0],(low[0]+high[0])/2);self.assertAlmostEqual(mid[1],(low[1]+high[1])/2)
        self.assertEqual(shading_models.translated('blinn',1.0)[:2],(.50,.730))
        smooth=shading_models.translated('blinn',.05)
        self.assertAlmostEqual(smooth[0],.10);self.assertAlmostEqual(smooth[1],.301)
        self.assertTrue(all(0<shading_models.translated(m,r/20)[1]<=1 for m in shading_models.MEASURED for r in range(21)))


    def test_a_roughness_an_image_drives_goes_through_the_same_curve(self):
        from unittest.mock import patch
        from moonray_modo import moonshine
        from moonray_modo.graph import bindings
        # The curve runs from nothing, through what was measured, to wholly rough; GTR needs none.
        self.assertEqual(shading_models.curve('blinn')[:3], [(0.0, 0.0), (.1, .20), (.2, .28)])
        self.assertEqual(shading_models.curve('blinn')[-1][0], 1.0)
        self.assertEqual(shading_models.curve('gtr')[1], (.1, .16))
        self.assertIsNone(shading_models.curve('principled'))
        for model, ramped in (('blinn', True), ('ashikhmin', True), ('gtr', True), ('principled', False)):
            material = {'color': [1] * 3, 'roughness': .36, 'raw_roughness': .35, 'shading_model': model, 'standard_material': True,
                        'layers': [{'kind': 'imageMap', 'effect': 'rough', 'path': 'rough.png', 'image_channel': 'red'}]}
            lines = []
            with patch('moonray_modo.textures.prepare', return_value='rough.tx'):
                found = bindings(material, 0, lines)
                moonshine.emit(material, 'tag', 0, found, lines)
            text = ' '.join(lines)
            self.assertEqual('RampMap("/modo/roughness/0")' in text, ramped, model)
            if ramped:
                self.assertIn('["ramp_type"] = 8', text)
                self.assertIn('["roughness"] = bind(RampMap("/modo/roughness/0"), 1)', text)

    def test_the_gpu_has_the_same_roughnesses(self):
        # MoonLightIPR turns a roughness its layers vary into the lobe's at each hit, from a copy of the table.
        import re
        kernel=(Path(__file__).resolve().parents[1]/'moonlightipr/src/device/kernel.cu').read_text(encoding='utf-8')
        def row(name):return [float(v.rstrip('f')) for v in re.search(r'const float %s\[8\] = \{([^}]*)\}'%name,kernel).group(1).split(',')]
        for model in ('blinn','ashikhmin','gtr'):
            rows=shading_models.MEASURED[model]
            self.assertEqual(row('from'),[0.0]+[r for r,_,_ in rows]+[1.0])
            self.assertEqual(row(model),[0.0]+[to for _,to,_ in rows]+[rows[-1][1]])
        self.assertEqual(list(shading_models.MEASURED),['blinn','ashikhmin','gtr'])

    def test_a_principled_highlight_rises_less_toward_the_edge_as_it_roughens(self):
        rise=shading_models.principled_rise
        self.assertEqual(rise({'raw_roughness':.1}),1.0)
        self.assertAlmostEqual(rise({'raw_roughness':.2}),1.0)
        self.assertAlmostEqual(rise({'raw_roughness':.4}),.5)
        self.assertAlmostEqual(rise({'raw_roughness':.6}),0.0)
        self.assertEqual(rise({'raw_roughness':.9}),0.0)
        # The lobe's roughness stands in where Modo's own is not carried, and a rise given outright is kept.
        self.assertAlmostEqual(rise({'roughness':.5}),.25)
        self.assertEqual(rise({'raw_roughness':.9,'_principled_rise':.7}),.7)


if __name__=='__main__':unittest.main()
