"""The compositor's graph: what is a graph, what order it is worked in, and what the image tool is asked for."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import compositor


def graph(**nodes):
    built={identity:{'type':kind,'parameters':held,'inputs':inputs} for identity,(kind,held,inputs) in nodes.items()}
    return {'nodes':built,'root':'out'}


class Graphs(unittest.TestCase):
    def test_a_new_graph_does_nothing(self):
        self.assertTrue(compositor.trivial(compositor.new()))
        self.assertTrue(compositor.trivial({}))
        self.assertEqual(compositor.buffers(compositor.new()),['beauty'])
        graded=graph(a=('input',{'buffer':'beauty'},{}),g=('grade',{'exposure':1.0},{'image':'a'}),out=('output',{},{'image':'g'}))
        self.assertFalse(compositor.trivial(graded))

    def test_what_is_not_a_graph_is_refused(self):
        for bad in ({'nodes':{'out':{'type':'output'}}},                                                       # no root
                    graph(out=('output',{},{}),other=('output',{},{})),                                        # two outputs
                    graph(a=('sharpen',{},{}),out=('output',{},{'image':'a'})),                                # unknown node
                    graph(a=('merge',{'mode':'burn'},{}),out=('output',{},{'image':'a'})),                     # unknown mode
                    graph(a=('blur',{'radius':-1},{}),out=('output',{},{'image':'a'})),                        # out of range
                    graph(a=('input',{'buffer':'../x'},{}),out=('output',{},{'image':'a'})),                   # not a buffer's name
                    graph(a=('blur',{},{'image':'gone'}),out=('output',{},{'image':'a'})),                     # wired to nothing
                    graph(a=('blur',{},{'image':'b'}),b=('blur',{},{'image':'a'}),out=('output',{},{'image':'a'}))):   # a loop
            with self.assertRaises(ValueError):compositor.validate(bad)

    def test_nodes_are_worked_after_what_they_take_from_and_only_those_the_output_needs(self):
        built=graph(a=('input',{'buffer':'beauty'},{}),b=('input',{'buffer':'albedo'},{}),unused=('input',{'buffer':'depth'},{}),
                    m=('merge',{'mode':'multiply'},{'a':'a','b':'b'}),g=('grade',{},{'image':'m'}),out=('output',{},{'image':'g'}))
        found=compositor.order(compositor.validate(built))
        self.assertEqual(found[-1],'out');self.assertNotIn('unused',found)
        self.assertLess(found.index('a'),found.index('m'));self.assertLess(found.index('m'),found.index('g'))
        self.assertEqual(compositor.buffers(built),['albedo','beauty'])

    def test_where_a_node_stands_does_not_change_the_picture(self):
        a=graph(a=('input',{'buffer':'beauty'},{}),g=('grade',{'exposure':1.0},{'image':'a'}),out=('output',{},{'image':'g'}))
        b=graph(a=('input',{'buffer':'beauty'},{}),g=('grade',{'exposure':1.0},{'image':'a'}),out=('output',{},{'image':'g'}))
        b['nodes']['g']['position']=[400,90]
        self.assertEqual(compositor.signature(a),compositor.signature(b))
        b['nodes']['g']['parameters']['exposure']=2.0
        self.assertNotEqual(compositor.signature(a),compositor.signature(b))

    def test_the_image_tool_is_asked_for_each_node_in_turn(self):
        built=graph(a=('input',{'buffer':'beauty'},{}),b=('input',{'buffer':'alpha'},{}),
                    m=('merge',{'mode':'screen','mix':.5},{'a':'a','b':'a','mask':'b'}),out=('output',{},{'image':'m'}))
        steps,result=compositor.jobs(built,{'beauty':'B.pfm','alpha':'A.exr'},{'beauty':'beauty','alpha':'alpha'},'work')
        self.assertEqual(len(steps),3);self.assertEqual(Path(result).name,'m.exr')
        self.assertIn('0,1,2',steps[0][0]);self.assertIn('0,0,0',steps[1][0])      # one number a pixel becomes three
        merge=steps[2][0]
        self.assertEqual(merge.count('--invert'),3);self.assertIn('--sub',merge);self.assertIn('0.5',merge)
        self.assertEqual(merge[-1],str(result))
        with self.assertRaises(ValueError):compositor.jobs(built,{'beauty':'B.pfm'},{'beauty':'beauty'},'work')   # the render has no alpha
        with self.assertRaises(ValueError):compositor.jobs(graph(a=('input',{'buffer':'crypto'},{}),out=('output',{},{'image':'a'})),
                                                          {'crypto':'C.exr'},{'crypto':'cryptomatte'},'work')

    def test_a_node_with_nothing_to_work_on_is_black_and_one_that_does_nothing_is_passed_by(self):
        steps,result=compositor.jobs(graph(g=('grade',{},{}),out=('output',{},{'image':'g'})),{'beauty':'B.pfm'},{'beauty':'beauty'},'work')
        self.assertEqual(Path(result).name,'black.exr');self.assertEqual(len(steps),1)
        steps,result=compositor.jobs(graph(a=('input',{'buffer':'beauty'},{}),x=('blur',{'radius':0.0},{'image':'a'}),out=('output',{},{'image':'x'})),
                                     {'beauty':'B.pfm'},{'beauty':'beauty'},'work')
        self.assertEqual(Path(result).name,'a.exr');self.assertEqual(len(steps),1)


if __name__=='__main__':unittest.main()
