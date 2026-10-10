"""Strands turned into the B-spline segments MoonLightIPR draws trace the shapes MoonRay is given."""
import struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_curves as curves


def at(controls,first,u):
    """A uniform cubic B-spline segment's point."""
    v=1-u;weights=(v**3/6,(3*u**3-6*u*u+4)/6,(-3*u**3+3*u*u+3*u+1)/6,u**3/6)
    return [sum(w*controls[first+i][axis] for i,w in enumerate(weights)) for axis in range(3)]


class Curves(unittest.TestCase):
    def near(self,a,b):
        for x,y in zip(a,b):self.assertAlmostEqual(x,y,places=6)

    def test_a_line_through_points_is_straight_pieces_between_them(self):
        entry={'vertices':[[0,0,0],[1,0,0],[1,2,0]],'counts':[3],'radii':[.2,.1,0.0],'curve_type':0}
        controls,widths,firsts,strands,straight,alongs=curves.segments(entry)
        self.assertTrue(straight);self.assertEqual(controls,entry['vertices'])
        self.assertEqual(firsts,[0,1]);self.assertEqual(strands,[0]*3);self.near(widths,[.2,.1,0.0]);self.near(alongs,[0,.5,1])
        # A second strand does not run on from the first.
        both=curves.segments(dict(entry,vertices=entry['vertices']*2,counts=[3,3],radii=[.2,.1,0.0]*2))
        self.assertEqual(both[2],[0,1,3,4])

    def test_bezier_points_trace_the_same_cubic(self):
        b=[[0,0,0],[1,2,0],[3,2,1],[4,0,1]]
        controls,widths,firsts,strands,straight,alongs=curves.segments({'vertices':b,'counts':[4],'radius':.1,'curve_type':1})
        self.assertEqual(firsts,[0]);self.assertFalse(straight)
        for u in (0,.25,.5,1):
            v=1-u;want=[v**3*b[0][k]+3*v*v*u*b[1][k]+3*v*u*u*b[2][k]+u**3*b[3][k] for k in range(3)]
            self.near(at(controls,0,u),want)
        self.near(widths,[.1]*4)

    def test_b_spline_points_are_used_as_they_are(self):
        points=[[i,i*i*.1,0] for i in range(6)]
        controls,widths,firsts,strands,straight,alongs=curves.segments({'vertices':points,'counts':[6],'radius':.05,'curve_type':2})
        self.assertEqual(controls,points);self.assertEqual(firsts,[0,1,2]);self.assertFalse(straight)
        # Too few points for a cubic: the line through them.
        self.assertTrue(curves.segments({'vertices':points[:3],'counts':[3],'radius':.05,'curve_type':2})[4])

    def test_the_payload_holds_points_radii_segments_and_a_coordinate_for_each_point(self):
        entry={'identity':'a','vertices':[[0,0,0],[0,1,0],[1,0,0],[1,1,0]],'counts':[2,2],'radius':.1,'uvs':[[.25,.5],[.75,.5]]}
        key,data,coordinates,straight,moves=curves.payload(entry,0)
        self.assertTrue(coordinates and straight)
        points,segments=struct.unpack_from('<2I',data)
        self.assertEqual((points,segments),(4,2))
        self.assertEqual(len(data),8+points*12+points*4+segments*4+points*12+points*8)
        self.assertFalse(moves)
        moving=curves.payload(dict(entry,vertices_close=[[x,y+1,z] for x,y,z in entry['vertices']]),0)
        self.assertTrue(moving[4]);self.assertEqual(len(moving[1]),len(data)+points*12);self.assertNotEqual(moving[0],key)
        self.assertEqual(struct.unpack_from('<2f',data,len(data)-8),(.75,.5))
        self.assertFalse(curves.payload(entry,None)[2])
        self.assertIsNone(curves.payload({'vertices':[[0,0,0]],'counts':[1]},None))

    def test_the_same_lists_are_known_without_reading_them_and_a_changed_one_is_not(self):
        entry={'identity':'a','vertices':[[0,0,0],[0,1,0],[1,0,0],[1,1,0]],'counts':[2,2],'radius':.1}
        first=curves.payload(entry,None)
        self.assertIs(curves.payload(dict(entry),None),first)
        self.assertNotEqual(curves.payload(dict(entry,radius=.2),None)[1],first[1])
        self.assertNotEqual(curves.payload(dict(entry,vertices=[[0,0,0],[0,2,0],[1,0,0],[1,1,0]]),None)[0],first[0])


if __name__=='__main__':unittest.main()
