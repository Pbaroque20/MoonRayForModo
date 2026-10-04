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
        records=[dict(name=n,type='BoxGeometry',attributes={'size':[size]*3}) for n,size in [('small',1),('large',2)]]
        records.append(dict(name='instances',type='RdlInstancerGeometry',attributes={
            'references':['small','large'],'method':2,'ref_indices':[0,1,0],
            'disable_indices':[2],'xform_list':[rdl_import.IDENTITY]*3}))
        plan=rdl_import.plan({'version':1,'objects':records},'example.rdla')
        self.assertEqual(len(plan['meshes']),2)
        self.assertEqual(max(v[0] for v in plan['meshes'][0]['vertices']),.5)
        self.assertEqual(max(v[0] for v in plan['meshes'][1]['vertices']),1)
    def test_invalid_dimensions(self):
        for attrs in ({'radius':0},{'radius':float('nan')},{'zmin':1,'zmax':-1}):
            with self.assertRaises(ValueError):self.sphere(**attrs)
    def test_material_assignment_and_transform_survive(self):
        matrix=list(rdl_import.IDENTITY);matrix[12]=4
        objects=[dict(name='ball',type='SphereGeometry',attributes={'radius':.12,'node_xform':matrix}),
                 dict(name='layer',type='Layer',attributes={'geometries':['ball'],'parts':[''],'surface_shaders':['red']})]
        plan=rdl_import.plan({'version':1,'objects':objects},'example.rdla')
        self.assertEqual(len(plan['meshes']),1)
        mesh=plan['meshes'][0];self.assertEqual(set(mesh['tags']),{'red'})
        self.assertTrue(all(v[0]>3 for v in mesh['vertices']))

if __name__=='__main__':unittest.main()
