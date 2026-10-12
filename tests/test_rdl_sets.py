"""An imported MoonRay scene's light, shadow and shadow receiver sets, planned as each mesh's Light Links; and MoonRay
light items named in the Light Links of a scene written out."""
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdl_import

TRIANGLE = {'vertex_list_0': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'face_vertex_count': [3], 'vertices_by_index': [0, 1, 2], 'is_subd': False}


def scene(layer):
    return {'version': 1, 'objects': [
        {'name': 'vars', 'type': 'SceneVariables', 'attributes': {'layer': 'layer'}},
        {'name': 'layer', 'type': 'Layer', 'attributes': dict({'geometries': ['/geo/wall', '/geo/floor'], 'parts': ['', ''], 'surface_shaders': ['paint', 'paint']}, **layer)},
        {'name': '/geo/wall', 'type': 'RdlMeshGeometry', 'attributes': dict(TRIANGLE)},
        {'name': '/geo/floor', 'type': 'RdlMeshGeometry', 'attributes': dict(TRIANGLE)},
        {'name': 'paint', 'type': 'DwaBaseMaterial', 'attributes': {}},
        {'name': '/light/key', 'type': 'SphereLight', 'attributes': {}},
        {'name': '/light/fill', 'type': 'RectLight', 'attributes': {}},
        {'name': 'both', 'type': 'LightSet', 'attributes': {'lights': ['/light/key', '/light/fill']}},
        {'name': 'keyOnly', 'type': 'LightSet', 'attributes': {'lights': ['/light/key']}},
        {'name': 'noFillShadow', 'type': 'ShadowSet', 'attributes': {'lights': ['/light/fill']}},
        {'name': 'notOnFloor', 'type': 'ShadowReceiverSet', 'attributes': {'geometries': ['/geo/floor']}}]}


class Sets(unittest.TestCase):
    def test_shared_prototypes_keep_instancer_material_and_light_assignments(self):
        source=scene({'geometries':['one','two'], 'lightsets':['keyOnly','both']})
        source['objects'][1]['attributes']['surface_shaders']=['paint','otherPaint']
        source['objects'] += [
            {'name':'otherPaint','type':'DwaBaseMaterial','attributes':{'metallic':.5}},
            *[{'name':name,'type':'RdlInstancerGeometry','attributes':{
                'method':2,'references':['/geo/wall'],'xform_list':[rdl_import.IDENTITY]*3}}
              for name in ('one','two')]]
        data=rdl_import.plan(source,'test.rdla')
        meshes=[m for m in data['meshes'] if m['render']]
        self.assertEqual(len(meshes),2)
        self.assertEqual(len(data['instances']),4)
        self.assertEqual(len({m['name'] for m in meshes}),2)
        tags=[m['tags'][0] for m in meshes]
        self.assertNotEqual(*tags)
        self.assertEqual({i['source'] for i in data['instances']},{m['name'] for m in meshes})
        link=next(l for l in data['links'] if l['material']==tags[0])
        self.assertEqual(link['lights'],['key'])
        self.assertIn('otherPaint',tags[1])

    def test_shared_shader_still_separates_different_instancer_light_sets(self):
        source=scene({'geometries':['one','two'], 'lightsets':['keyOnly','both']})
        source['objects'] += [
            {'name':name,'type':'RdlInstancerGeometry','attributes':{
                'method':2,'references':['/geo/wall'],'xform_list':[rdl_import.IDENTITY]*2}}
            for name in ('one','two')]
        data=rdl_import.plan(source,'test.rdla')
        meshes=[m for m in data['meshes'] if m['render']]
        self.assertEqual(len(meshes),2)
        self.assertEqual(len(data['instances']),2)
        self.assertNotEqual(meshes[0]['tags'],meshes[1]['tags'])

    def test_sets_become_the_links_of_the_meshes_they_are_on(self):
        data = rdl_import.plan(scene({'lightsets': ['keyOnly', 'both'], 'shadowsets': ['noFillShadow', None], 'shadowreceiversets': ['notOnFloor', None]}), 'test.rdla')
        names = {record['name'] for record in data['meshes']}
        lights = {record['name'] for record in data['entities']}
        self.assertEqual(len(data['links']), 1)
        link = data['links'][0]
        # The wall is lit by the key alone, casts no shadow for the fill, and none onto the floor.
        self.assertIn(link['geometry'], names)
        self.assertEqual(len(link['lights']), 1)
        self.assertEqual(len(link['shadows']), 1)
        self.assertNotEqual(link['lights'], link['shadows'])
        self.assertTrue(set(link['lights']) | set(link['shadows']) <= lights)
        self.assertEqual(len(link['receivers']), 1)
        self.assertIn(link['receivers'][0], names - {link['geometry']})
        self.assertFalse(any('not imported' in warning for warning in data['warnings']))

    def test_mesh_light_links_use_the_emitting_mesh(self):
        source=scene({'lightsets':['emitterOnly','both'],'shadowsets':['emitterShadow',None]})
        source['objects'][1]['attributes']['surface_shaders'][1]=None
        source['objects'] += [
            {'name':'emitter','type':'MeshLight','attributes':{'geometry':'/geo/floor'}},
            {'name':'emitterOnly','type':'LightSet','attributes':{'lights':['emitter']}},
            {'name':'emitterShadow','type':'ShadowSet','attributes':{'lights':['emitter']}}]
        data=rdl_import.plan(source,'test.rdla')
        link=next(link for link in data['links'] if link['shadows'])
        self.assertEqual(link['lights'],link['shadows'])
        self.assertEqual(len(link['lights']),1)
        self.assertIn(link['lights'][0],{m['name'] for m in data['meshes']})
        self.assertNotEqual(link['geometry'],link['lights'][0])
        emitter=next(e for e in data['entities'] if e['class']=='MeshLight')
        self.assertEqual(emitter['parameters']['geometry'],link['lights'][0])

    def test_native_shape_keeps_light_and_shadow_links(self):
        source=scene({'lightsets':['keyOnly','both'],'shadowsets':['noFillShadow',None]})
        source['objects'][2].update(type='BoxGeometry',attributes={'size':[1,1,1]})
        data=rdl_import.plan(source,'test.rdla')
        shape=next(e for e in data['entities'] if e['class']=='BoxGeometry')
        link=next(l for l in data['links'] if l['shadows'])
        self.assertEqual(link['geometry'],shape['name'])
        from moonray_modo import entities
        lines=[]
        entities.emit_geometry({'entities':[{'identity':'shape-id','name':'Box','class':'BoxGeometry','parameters':{'size':[1,1,1]}}]}, {'':{}},lines)
        text='\n'.join(lines)
        self.assertIn('objectLightSets["shape-id"] or lightSet',text)
        self.assertIn('objectShadowSets["shape-id"]',text)

    def test_native_shadow_receiver_is_preserved(self):
        source=scene({'shadowreceiversets':['notOnFloor',None]})
        source['objects'][3].update(type='SphereGeometry',attributes={'radius':1})
        data=rdl_import.plan(source,'test.rdla')
        target=next(e for e in data['entities'] if e['class']=='SphereGeometry')
        self.assertEqual(data['links'][0]['receivers'],[target['name']])

    def test_native_receiver_references_match_exported_shapes(self):
        from moonray_modo import entities
        shape={'identity':'shape','name':'Shape','class':'BoxGeometry','parameters':{}}
        self.assertEqual(entities.shadow_receiver_references({'entities':[shape]}, {'shape'}),['BoxGeometry("/modo/entity/shape")'])
        self.assertEqual(entities.shadow_receiver_references({'entities':[shape]}, {'other'}),[])
        shape['parameters']['modo_volume']='fog'
        shape['attributes']=[{'name':'Cd','type':'color','value':[1,0,0]}]
        refs=entities.shadow_receiver_references({'entities':[shape]}, {'shape'})
        self.assertEqual(refs,['RdlMeshGeometry("/modo/entity/shape")','RdlInstancerGeometry("/modo/entity/shape/holder")'])

    def test_scene_export_includes_native_shadow_receiver(self):
        from moonray_modo import rdla
        value={'camera':{'matrix':rdla.IDENTITY,'focal_mm':50,'film_mm':36},
               'meshes':[{'identity':'caster','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'material':''}],
               'entities':[{'identity':'target','name':'Target','class':'SphereGeometry','parameters':{'radius':1}}],
               'production':{'objects':{'caster':{'shadow_receivers':['target']}}}}
        text=rdla.scene_text(value)
        self.assertIn('objectShadowReceiverSets["caster"] = ShadowReceiverSet("/modo/shadowReceivers/caster") { ["geometries"] = {SphereGeometry("/modo/entity/target")} }',text)

    def test_light_filter_set_import(self):
        source=scene({'lightfiltersets':['filters',None]})
        source['objects'] += [
            {'name':'tint','type':'IntensityLightFilter','attributes':{'color':[1,.5,.2]}},
            {'name':'filters','type':'LightFilterSet','attributes':{'lightfilters':['tint']}}]
        data=rdl_import.plan(source,'test.rdla')
        target=next(e for e in data['entities'] if e['class']=='IntensityLightFilter')
        self.assertEqual(data['links'][0]['filters'],[target['name']])
        self.assertFalse(any('light filter' in w for w in data['warnings']))
        source['objects'][-1]['attributes']['lightfilters'].append('missing')
        data=rdl_import.plan(source,'test.rdla')
        self.assertTrue(any('missing' in w and 'omitted' in w for w in data['warnings']))

    def test_filter_assignment_export_and_missing_filter(self):
        from moonray_modo import rdla
        value={'camera':{'matrix':rdla.IDENTITY,'focal_mm':50,'film_mm':36},
               'meshes':[{'identity':'mesh','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'material':''}],
               'entities':[{'identity':'tint','name':'Tint','class':'IntensityLightFilter','parameters':{'color':[1,.5,.2]}}],
               'production':{'objects':{'mesh':{'light_filters':['tint']}}}}
        text=rdla.scene_text(value)
        self.assertIn('objectLightFilterSets["mesh"] = LightFilterSet("/modo/lightFilters/mesh")({IntensityLightFilter("/modo/entity/tint")})',text)
        self.assertIn('table.insert(a, objectLightFilterSets[owner] or materialLightFilterSets[tag])',text)
        value['entities']=[]
        with self.assertRaisesRegex(ValueError,'not a MoonRay item of the right kind'):
            rdla.scene_text(value)

    def test_same_material_on_differently_lit_mesh_parts(self):
        source=scene({'geometries':['/geo/wall','/geo/wall','/geo/floor'], 'parts':['left','right',''],
                      'surface_shaders':['paint','paint','paint'], 'lightsets':['keyOnly','both','both'],
                      'shadowsets':['noFillShadow',None,None]})
        source['objects'][2]['attributes'].update(vertex_list_0=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],
            face_vertex_count=[3,3],vertices_by_index=[0,1,2,0,2,3],part_list=['left','right'],
            part_face_count_list=[1,1],part_face_indices=[0,1])
        data=rdl_import.plan(source,'test.rdla')
        mesh=next(m for m in data['meshes'] if len(m['faces'])==2)
        self.assertEqual(len(set(mesh['tags'])),2)
        self.assertEqual(len(mesh['vertices']),4)
        self.assertEqual(len(data['links']),1)
        self.assertEqual(data['links'][0]['material'],mesh['tags'][0])
        self.assertFalse(any('first' in w for w in data['warnings']))

    def test_a_scene_lit_by_all_its_lights_has_no_links(self):
        self.assertEqual(rdl_import.plan(scene({'lightsets': ['both', 'both']}), 'test.rdla')['links'], [])
        self.assertEqual(rdl_import.plan(scene({}), 'test.rdla')['links'], [])


if __name__ == '__main__':
    unittest.main()
