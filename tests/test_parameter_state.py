"""Deferred value-color checks; no Modo or Qt required."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import parameter_state as state

class ParameterState(unittest.TestCase):
    def test_scalar_default_and_reset(self):
        spec={'type':'Float','default':'0.5f'}
        self.assertEqual(state.color(.5,spec),'#000000')
        self.assertEqual(state.color(.8,spec),'#00ffff')
        self.assertEqual(state.color(.5,spec),'#000000')
    def test_rgb_and_vector(self):
        spec={'type':'Rgb','default':'Rgb(0.2f, 0.3f, 0.4f)'}
        self.assertEqual(state.color([.2,.3,.4],spec),'#000000')
        self.assertEqual(state.color([.2,.3,.9],spec),'#00ffff')
    def test_file_bool_and_reference(self):
        for spec,default,changed in [({'type':'String','default':'""'},'',r'C:/texture.exr'),
                                     ({'type':'Bool','default':'false'},False,True),
                                     ({'type':'SceneObject*'},None,{'item':'camera'})]:
            self.assertEqual(state.color(default,spec),'#000000')
            self.assertEqual(state.color(changed,spec),'#00ffff')
    def test_connected_default_is_edited(self):
        self.assertEqual(state.color(1,{'type':'Int','default':'1'},connected=True),'#00ffff')
    def test_control_rounding_does_not_fake_edits(self):
        self.assertTrue(state.equal(.333333,1/3))
        self.assertFalse(state.equal(.333334,1/3))
        self.assertFalse(state.equal(1e12,1e12+1))
    def test_declared_arrays(self):
        self.assertEqual(state.color([0.,1.],{'type':'FloatVector','default':'{0.0f, 1.0f}'}),'#000000')

if __name__=='__main__':unittest.main()
