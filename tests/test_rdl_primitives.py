"""Deferred regression checks; run manually after implementation."""
import math,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import rdl_primitives,rdl_import

class RdlPrimitives(unittest.TestCase):
    def sphere(self,**attrs):
        return rdl_primitives.mesh_record(dict(name='ball',type='SphereGeometry',attributes=attrs))['attributes']
    def test_sphere_closed_edges_and_non_degenerate_faces(self):
        a=self.sphere(radius=.12);edges={};offset=0
        for n in a['face_vertex_count']:
            face=a['vertices_by_index'][offset:offset+n];offset+=n
            self.assertEqual(len(set(face)),n)
            for i,j in zip(face,face[1:]+face[:1]):
                key=tuple(sorted((i,j)));edges[key]=edges.get(key,0)+1
        self.assertTrue(all(v==2 for v in edges.values()))
        self.assertEqual(len(a['uv_list']),len(a['vertices_by_index']))
        for v in a['vertex_list_0']:self.assertAlmostEqual(sum(x*x for x in v),.12**2)
    def test_clipped_sphere(self):
        a=self.sphere(radius=2,zmin=-.5,zmax=.7,phi_max=90)
        for x,y,z in a['vertex_list_0']:
            self.assertGreaterEqual(z,-.500001);self.assertLessEqual(z,.700001)
            self.assertGreaterEqual(x,-1e-9);self.assertGreaterEqual(y,-1e-9)
    def test_box_dimensions(self):
        a=rdl_primitives.mesh_record(dict(name='box',type='BoxGeometry',attributes={'size':[2,4,6]}))['attributes']
        self.assertEqual(a['face_vertex_count'],[4]*6)
        self.assertEqual([max(v[i] for v in a['vertex_list_0']) for i in range(3)],[1,2,3])
    def test_multiple_prototypes_and_disabled_instances(self):
        records=[dict(name=n,type='BoxGeometry',attributes={'size':[size]*3}) for n,size in [('small',2),('large',3)]]
        records.append(dict(name='red',type='DwaBaseMaterial',attributes={}))
        records.append(dict(name='layer',type='Layer',attributes={'geometries':['small','large'],'parts':['',''],'surface_shaders':['red','red']}))
        records.append(dict(name='instances',type='RdlInstancerGeometry',attributes={
            'references':['small','large'],'method':2,'ref_indices':[0,1,0],
            'disable_indices':[2],'xform_list':[rdl_import.IDENTITY]*3}))
        plan=rdl_import.plan({'version':1,'objects':records},'example.rdla')
        # Each instance that is on is a MoonRay box of its prototype's size; the prototypes do not stand in the scene themselves.
        self.assertEqual([(e['class'],e['parameters']['size']) for e in plan['entities']],[('BoxGeometry',[2,2,2]),('BoxGeometry',[3,3,3])])
        self.assertEqual(plan['meshes'],[])
    def test_instances_of_a_mesh_and_their_turns(self):
        mesh=dict(name='leaf',type='RdlMeshGeometry',attributes={'vertex_list_0':[[0,0,0],[1,0,0],[0,1,0]],'face_vertex_count':[3],'vertices_by_index':[0,1,2]})
        half=2**-.5
        scatter=dict(name='scatter',type='RdlInstancerGeometry',attributes={'references':['leaf'],'method':0,
            'positions':[[1,0,0],[0,2,0]],'orientations':[[0,0,0,1],[0,0,half,half]],'scales':[[1,1,1],[2,2,2]]})
        nested=dict(name='grove',type='RdlInstancerGeometry',attributes={'references':['scatter'],'method':2,
            'xform_list':[rdl_import.IDENTITY,[1,0,0,0,0,1,0,0,0,0,1,0,10,0,0,1]]})
        worn=[dict(name='green',type='DwaBaseMaterial',attributes={}),
              dict(name='layer',type='Layer',attributes={'geometries':['leaf'],'parts':[''],'surface_shaders':['green']})]
        plan=rdl_import.plan({'version':1,'objects':[mesh,scatter,nested]+worn},'example.rdla')
        # Without a material MoonRay would not render the leaf at all, and it is left out.
        bare=rdl_import.plan({'version':1,'objects':[mesh,scatter,nested]},'example.rdla')
        self.assertEqual((bare['meshes'],bare['instances']),([],[]))
        self.assertTrue(any('no material' in w for w in bare['warnings']))
        # One mesh, placed four times: the first placing is the mesh itself, the rest are instances of it.
        self.assertEqual(len(plan['meshes']),1)
        self.assertEqual(len(plan['instances']),3)
        places=sorted([plan['meshes'][0]['matrix']]+[i['matrix'] for i in plan['instances']],key=lambda m:(m[12],m[13]))
        self.assertEqual([m[12:15] for m in places],[[0,2,0],[1,0,0],[10,2,0],[11,0,0]])
        # A quarter turn about z, twice the size: x goes to y.
        for got,want in zip(places[0][:3],[0,2,0]):self.assertAlmostEqual(got,want,places=5)
        self.assertIsNotNone(rdl_import.decomposed(places[0]))
    def test_curves_lights_and_settings(self):
        records=[dict(name='black',type='HairDiffuseMaterial',attributes={}),
                 dict(name='layer',type='Layer',attributes={'geometries':['/s/hair'],'parts':[''],'surface_shaders':['black']}),
                 dict(name='/s/hair',type='RdlCurveGeometry',attributes={'curves_vertex_count':[2,3],'vertex_list_0':[[0,0,0],[0,1,0],[1,0,0],[1,1,0],[1,2,0]],
                      'radius_list':[.001,.002],'curve_type':2}),
                 dict(name='/s/key',type='SphereLight',authored=['intensity','radius','node_xform'],attributes={'intensity':7.0,'radius':.5,'exposure':0.0,'node_xform':rdl_import.IDENTITY}),
                 dict(name='vars',type='SceneVariables',authored=['image_width','image_height','pixel_samples','max_depth'],
                      attributes={'image_width':800,'image_height':600,'pixel_samples':6,'max_depth':7,'light_samples':2}),
                 dict(name='/out/spec',type='RenderOutput',attributes={'result':8,'lpe':'C<RS>L','channel_name':'spec'})]
        plan=rdl_import.plan({'version':1,'objects':records},'example.rdla')
        # Too few points for a span of the curve: they are kept as they are.
        # Two curves of two widths: an item each, so that each keeps its own.
        self.assertEqual([[len(line) for line in c['lines']] for c in plan['curves']],[[2],[3]])
        # A B-spline does not pass through its control points; what is imported is the path it does take.
        path=rdl_import.followed([[0,0,0],[0,3,0],[3,3,0],[3,0,0],[6,0,0]],rdl_import.BSPLINE,4)
        self.assertEqual(len(path),9)
        for got,want in zip(path[0],[.5,2.5,0]):self.assertAlmostEqual(got,want)
        bezier=rdl_import.followed([[0,0,0],[0,3,0],[3,3,0],[3,0,0]],rdl_import.BEZIER,4)
        self.assertEqual((bezier[0],bezier[-1]),([0,0,0],[3,0,0]))
        self.assertEqual(plan['curves'][0]['kind'],rdl_import.BSPLINE)
        self.assertAlmostEqual(plan['curves'][0]['root_mm'],2.0)
        self.assertAlmostEqual(plan['curves'][1]['root_mm'],4.0)
        self.assertEqual([(e['name'],e['class'],e['parameters']) for e in plan['entities']],[('key','SphereLight',{'intensity':7.0,'radius':.5})])
        self.assertEqual(plan['settings']['resolution'],[800,600])
        self.assertEqual(plan['settings']['samples'],6)
        self.assertEqual(plan['settings']['render'],{'max_depth':7})
        self.assertEqual([(o['name'],o['kind'],o['expression']) for o in plan['settings']['custom_aovs']],[('spec','lpe','C<RS>L')])
    def test_invalid_dimensions(self):
        for attrs in ({'radius':0},{'radius':float('nan')},{'zmin':1,'zmax':-1}):
            with self.assertRaises(ValueError):self.sphere(**attrs)
    def test_material_assignment_and_transform_survive(self):
        matrix=list(rdl_import.IDENTITY);matrix[12]=4
        objects=[dict(name='ball',type='SphereGeometry',authored=['radius','node_xform'],attributes={'radius':.12,'node_xform':matrix}),
                 dict(name='red',type='DwaBaseMaterial',attributes={'albedo':[1,0,0]}),
                 dict(name='layer',type='Layer',attributes={'geometries':['ball'],'parts':[''],'surface_shaders':['red']})]
        plan=rdl_import.plan({'version':1,'objects':objects},'example.rdla')
        # A sphere stays MoonRay's own sphere, where it stood and wearing what it wore.
        ball=plan['entities'][0]
        self.assertEqual((ball['class'],ball['parameters'],ball['material'],ball['matrix'][12]),('SphereGeometry',{'radius':.12},'red',4))
        self.assertIn('red',plan['materials'])

if __name__=='__main__':unittest.main()
