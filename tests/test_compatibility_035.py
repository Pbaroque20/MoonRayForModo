"""Deferred offline regression checks. This module is never run by the installer."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import working_space,environment_layers,materialx,materialx_document
from moonray_modo import material_groups,cryptomatte,motion,rdla


def scene():
    return {'camera':{'identity':'camera','matrix':list(rdla.IDENTITY),'focal_mm':50,'film_mm':36},
        'materials':{'':{'color':[.5,.5,.5],'roughness':.3}},'lights':[], 'fps':24,
        'meshes':[{'name':'Triangle','identity':'mesh','vertices':[[-1,0,0],[1,0,0],[0,1,0]],
                   'faces':[[0,1,2]],'matrix':list(rdla.IDENTITY)}]}


class Compatibility035(unittest.TestCase):
    def test_working_color_white_and_round_trip(self):
        for color in ([1,1,1],[0,0,0],[.1,.6,4],[-.1,2,.3]):
            converted=working_space.product(working_space.TO_AP1,color)
            actual=working_space.product(working_space.TO_REC709,converted)
            for a,b in zip(actual,color):self.assertAlmostEqual(a,b,places=9)
        for value in working_space.product(working_space.TO_AP1,[1,1,1]):self.assertAlmostEqual(value,1,places=8)
        self.assertAlmostEqual(working_space.TO_AP1[0][0],.6131,places=3)

    def test_soft_light_neutral_and_blend_limits(self):
        background=[.1,.4,.9]
        self.assertEqual(environment_layers.blend(background,[.5]*3,'softlight',1),background)
        self.assertEqual(environment_layers.blend(background,[1]*3,'colordodge',1),[1,1,1])
        self.assertEqual(environment_layers.blend(background,[0]*3,'colorburn',1),[0,0,0])
        self.assertEqual(environment_layers.blend(background,[.9]*3,'multiply',0),background)

    def test_group_scope_and_image_order_survive_flattening(self):
        group={'id':'group','opacity':.25,'blend':'multiply'}
        base={'color':[1,0,0],'material_groups':[group], 'layers':[{'kind':'constant','effect':'diffCol','value':[0,1,0],'absolute_groups':[group]}]}
        value=material_groups.flatten([base])
        self.assertEqual([x['kind'] for x in value],['materialBase','constant'])
        self.assertEqual(value[0]['groups'],value[1]['groups'])
        self.assertEqual(value[1]['groups'][0]['opacity'],.25)

    def test_masked_absorption_uses_composited_color(self):
        value=scene();glass={'color':[1,1,1],'transmission':1,'transmission_color':[.2,.8,.9],
            'absorption_distance':.25,'material_groups':[{'id':'mask','opacity':.5,'blend':'normal','invert':True}]}
        value['materials']['']['material_stack']=[glass]
        text=rdla.scene_text(value)
        self.assertIn('BaseVolume(',text)
        self.assertIn('["mode"] = 11',text)
        self.assertIn('volumes[tag]',text)

    def test_materialx_include_cycle_and_definition_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=root/'a.mtlx';b=root/'b.mtlx'
            a.write_text('<materialx><include href="b.mtlx"/></materialx>')
            b.write_text('<materialx><include href="a.mtlx"/></materialx>')
            with self.assertRaisesRegex(ValueError,'cycle'):materialx_document.load(a)
            a.write_text('<materialx><include href="b.mtlx"/><nodedef name="same" node="one"/></materialx>')
            b.write_text('<materialx><nodedef name="same" node="two"/></materialx>')
            with self.assertRaisesRegex(ValueError,'Conflicting'):materialx_document.load(a)

    def test_materialx_named_outputs_and_fileprefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);library=root/'library.mtlx';main=root/'main.mtlx'
            library.write_text("""<materialx version="1.38" fileprefix="maps/">
              <nodedef name="ND_pair" node="pair"><output name="red" type="color3"/><output name="green" type="color3"/></nodedef>
              <nodegraph name="NG_pair" nodedef="ND_pair">
                <output name="red" type="color3" value="1,0,0"/>
                <output name="green" type="color3" value="0,1,0"/>
              </nodegraph>
              <image name="unused" type="color3"><input name="file" type="filename" value="test.exr"/></image>
            </materialx>""")
            main.write_text("""<materialx version="1.38"><include href="library.mtlx"/>
              <pair name="p" type="multioutput" nodedef="ND_pair"/>
              <standard_surface name="s" type="surfaceshader"><input name="base_color" type="color3" nodename="p" output="green"/></standard_surface>
              <surfacematerial name="m" type="material"><input name="surfaceshader" type="surfaceshader" nodename="s"/></surfacematerial>
            </materialx>""")
            document,_=materialx_document.load(main)
            self.assertEqual(Path(document.find("image/input").get('value')),(root/'maps/test.exr').resolve())
            graph=materialx.read(main)
            self.assertTrue(any(n.get('parameters',{}).get('value')==[0,1,0] for n in graph['nodes'].values()))
            self.assertIn(str(library.resolve()),graph['materialx_dependencies'])

    def test_instance_and_material_crypto_names(self):
        value=scene();mesh=dict(value['meshes'][0],instances=[rdla.IDENTITY]*2,instance_ids=['a','b'],face_materials=['red','green'])
        value['materials']={'red':{'name':'Paint'},'green':{'name':'Glass'}}
        labels=cryptomatte.labels(mesh,'object',value,True)
        self.assertNotEqual(cryptomatte.float_id(labels[0]),cryptomatte.float_id(labels[1]))
        self.assertEqual(cryptomatte.labels(mesh,'material',value),['Paint [red]','Glass [green]'])
        value['production']={'objects':{'a':{'asset_label':'Vehicle'}}}
        self.assertEqual(cryptomatte.name(mesh,'asset',value,'a|17'),'Vehicle')

    def test_strict_and_frozen_changing_topology(self):
        center=scene();first=copy.deepcopy(center);last=copy.deepcopy(center)
        last['meshes'][0]['vertices'].append([0,0,1]);last['meshes'][0]['faces']=[[0,1,3]]
        with self.assertRaisesRegex(ValueError,'stable topology'):motion.apply_motion(copy.deepcopy(center),first,last,[-.25,.25])
        center['motion_policies']={'mesh':'freeze'}
        motion.apply_motion(center,first,last,[-.25,.25])
        self.assertEqual(center['meshes'][0]['faces'],[[0,1,2]])
        self.assertNotIn('vertices_close',center['meshes'][0])

    def test_particle_velocity_is_applied_once(self):
        center=scene();center['extra_geometry']=[{'kind':'points','identity':'particles','vertices':[[0,0,0]],'velocities':[[24,0,0]]}]
        center['motion_policies']={'particles':'velocity'}
        first=copy.deepcopy(center);last=copy.deepcopy(center)
        motion.apply_motion(center,first,last,[-.25,.25])
        point=center['extra_geometry'][0]
        self.assertEqual(point['vertices'],[[-.25,0,0]])
        self.assertEqual(point['vertices_close'],[[.25,0,0]])
        self.assertNotIn('velocities',point)

if __name__=='__main__':unittest.main()
