"""Deferred node-default checks. Run manually; never launched by installation."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import nodes,node_defaults

class NodeDefaults(unittest.TestCase):
    def test_every_catalog_node_initializes(self):
        for kind in nodes.kinds():
            with self.subTest(kind=kind):
                parameters=node_defaults.parameters(kind)
                self.assertIsInstance(parameters,dict)
                for key,spec in nodes.specs(kind).items():
                    if not spec['type'].startswith('SceneObject'):self.assertIn(key,parameters)
    def test_color_array_and_matrix(self):
        self.assertEqual(node_defaults.parameters('ConstantColorMap')['color_value'],[1,1,1])
        self.assertEqual(node_defaults.value({'type':'RgbVector','default':'{Rgb(0.25), Rgb(1, 0, 1)}'}),[[.25]*3,[1,0,1]])
        self.assertEqual(node_defaults.value({'type':'Mat3f','default':'Mat3f(1)'}),[1,0,0,0,1,0,0,0,1])
    def test_defaults_are_independent(self):
        first=node_defaults.parameters('constant');first['value'][0]=99
        self.assertEqual(node_defaults.parameters('constant')['value'],[.5,.5,.5])
    def test_source_expressions_are_not_executed(self):
        with self.assertRaises(ValueError):node_defaults.value({'type':'Float','default':'call_function()'})

if __name__=='__main__':unittest.main()
