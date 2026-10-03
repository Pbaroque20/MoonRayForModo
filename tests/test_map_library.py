"""Deferred node and group checks; invoke explicitly outside Modo."""
import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import nodes,materialx
from moonray_modo.compositing import Groups

class MapsTests(unittest.TestCase):
    def test_native_normal_socket_rejects_color(self):
        graph=nodes.new();graph['nodes']['color']={'type':'ConstantColorMap'}
        graph['nodes']['surface']['inputs']['input_normal']='color'
        with self.assertRaises(ValueError):nodes.validate(graph)
        graph['nodes']['color']={'type':'ImageNormalMap'}
        nodes.validate(graph)

    def test_native_procedural_binding(self):
        graph=nodes.new();graph['nodes']['noise']={'type':'NoiseMap_v2','parameters':{'seed':17}}
        graph['nodes']['surface']['inputs']['albedo']='noise'
        lines=[];nodes.emit({'node_graph':graph,'color':[.5]*3},'/test',[0],lines,{})
        text='\n'.join(lines)
        self.assertIn('NoiseMap_v2(',text);self.assertIn('["seed"] = 17',text)
        self.assertIn('["albedo"] = bind(NoiseMap_v2(',text)

    def test_group_blend_mask_and_opacity_apply_once(self):
        def blend(a,b,g,m,e):return a+(a*b-a)*g['opacity']*(1 if m is None else m)
        groups=Groups({'diffCol':.8,'groupMask':1},None,blend)
        groups.select([{'id':'g','opacity':.5,'blend':'multiply'}])
        groups.current.update(diffCol=.25,groupMask=.5);groups.used.update(('diffCol','groupMask'))
        current,used=groups.finish()
        self.assertAlmostEqual(current['diffCol'],.65);self.assertEqual(current['groupMask'],1)
        self.assertNotIn('groupMask',used)

    def test_local_materialx_definition_instances(self):
        xml='''<materialx version="1.38">
<nodedef name="ND_tint" node="tint"><input name="value" type="color3" value="0.1,0.2,0.3"/><output name="out" type="color3"/></nodedef>
<nodegraph name="NG_tint" nodedef="ND_tint"><constant name="c" type="color3"><input name="value" type="color3" interfacename="value"/></constant><output name="out" type="color3" nodename="c"/></nodegraph>
<tint name="t" type="color3" nodedef="ND_tint"><input name="value" type="color3" value="0.7,0.5,0.2"/></tint>
<standard_surface name="surface" type="surfaceshader"><input name="base_color" type="color3" nodename="t"/></standard_surface>
<surfacematerial name="m" type="material"><input name="surfaceshader" type="surfaceshader" nodename="surface"/></surfacematerial></materialx>'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.mtlx';path.write_text(xml)
            graph=materialx.read(path)
        self.assertTrue(any(n.get('parameters',{}).get('value')==[.7,.5,.2] for n in graph['nodes'].values()))

if __name__=='__main__':unittest.main()
