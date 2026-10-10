"""Modo's shading models as the lobe, roughness and strength MoonRay draws them with."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import shading_models


class ShadingModels(unittest.TestCase):
    def test_gtr_and_principled_pass_as_they_are(self):
        for model in ('principled','something else'):
            self.assertEqual(shading_models.translated(model,.37),(.37,1.0,False))
        found=shading_models.translated('gtr',.37)
        self.assertAlmostEqual(found[0],.37);self.assertEqual(found[1:],(1.0,False))
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


if __name__=='__main__':unittest.main()
