"""Light path expressions: the presets on offer are written as MoonRay reads them, and a slip is named in plain words."""
import sys,types,unittest
from pathlib import Path
for name in ('modo','lx','lxifc','lxu'):sys.modules.setdefault(name,types.ModuleType(name))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import options,outputs


class LightPaths(unittest.TestCase):
    def test_what_the_plugin_itself_offers_passes(self):
        for label,name,expression in outputs.PRESETS:
            self.assertIsNone(outputs.lpe_problem(expression),expression)
        for key,(label,attributes,_) in options.AOVS.items():
            if 'lpe' in attributes:self.assertIsNone(outputs.lpe_problem(attributes['lpe']),attributes['lpe'])
        self.assertEqual(len({name for _,name,_ in outputs.PRESETS}),len(outputs.PRESETS))
        made=outputs.values([{'name':name,'kind':'lpe','expression':expression} for _,name,expression in outputs.PRESETS])
        self.assertEqual(len(made),len(outputs.PRESETS))

    def test_expressions_an_artist_might_write_pass(self):
        for expression in ("C.*<L.'key'>","C<RD>[<L.>O]","C<TS>.*[<L.>O]","unoccluded; CD[<L.>O]","(C<RD>L)|(C<RG>L)","C<R[^S]>+L","CV[<L.>O]"):
            self.assertIsNone(outputs.lpe_problem(expression),expression)

    def test_a_slip_is_named(self):
        for expression,word in (("","Enter"),("difuse","Unknown word"),("C<RD[<L.>O]","angle brackets"),("C<RD>[<L.>O","square brackets"),
                                ("C.*<L.'key>","quotes"),("CXL","Unknown event X"),("*CDL","nothing before"),("RDL","starts at the camera"),
                                ("shadow;CDL","unoccluded"),("C[]L","Empty"),("C$L","do not belong")):
            found=outputs.lpe_problem(expression)
            self.assertIsNotNone(found,expression);self.assertIn(word,found)
        with self.assertRaises(ValueError):outputs.values([{'name':'broken','kind':'lpe','expression':'C<RD[L'}])


if __name__=='__main__':unittest.main()
