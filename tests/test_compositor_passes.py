"""Render passes in the compositor: the Sum node, a graph built from passes or light groups that gives back the beauty,
the outputs it asks the scene for, and the light-group labels a scene's lights carry."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor


def summed(*sources):
    nodes = {name: {'type': 'input', 'parameters': {'buffer': name}, 'inputs': {}} for name in sources}
    nodes['total'] = {'type': 'sum', 'parameters': {}, 'inputs': {compositor.SUM_INPUTS[n]: name for n, name in enumerate(sources)}}
    nodes['out'] = {'type': 'output', 'parameters': {}, 'inputs': {'image': 'total'}}
    return {'nodes': nodes, 'root': 'out'}


class Sum(unittest.TestCase):
    def test_the_image_tool_adds_every_picture_wired(self):
        steps, final = compositor.jobs(summed('a', 'b', 'c'), {k: k + '.exr' for k in 'abc'}, {}, Path('work'))
        args = steps[-1][0]
        self.assertEqual(final, Path('work') / 'total.exr')
        self.assertEqual(args[:6], [str(Path('work') / 'a.exr'), str(Path('work') / 'b.exr'), '--add', str(Path('work') / 'c.exr'), '--add', '-d'])

    def test_the_program_adds_them_one_after_another(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            compositor.program_jobs(summed('a', 'b', 'c'), {k: k + '.exr' for k in 'abc'}, {}, Path(folder), None, 'composite.exe')
            text = (Path(folder) / 'composite.txt').read_text()
        merges = [l for l in text.splitlines() if l.startswith('step %d ' % compositor.STEP_KINDS['merge'])]
        self.assertEqual(len(merges), 2)
        self.assertTrue(all(l.split()[6] == str(compositor.MODES.index('add')) for l in merges))

    def test_one_picture_passes_and_none_is_black(self):
        steps, final = compositor.jobs(summed('a'), {'a': 'a.exr'}, {}, Path('work'))
        self.assertEqual(final, Path('work') / 'a.exr')

    def test_the_canvas_shows_the_wired_inputs_and_one_free(self):
        node = summed('a', 'b')['nodes']['total']
        self.assertEqual(compositor.ports(node), ['in1', 'in2', 'in3'])
        self.assertEqual(compositor.port_label('in3'), 'input 3')
        node['inputs'] = {'in1': 'a', 'in5': 'b'}
        self.assertEqual(compositor.ports(node), ['in1', 'in2', 'in5'])


class PassGraph(unittest.TestCase):
    def test_every_pass_is_graded_into_a_sum_with_the_remainder(self):
        graph = compositor.pass_graph([('pass_diffuse_direct', 'Direct diffuse'), ('pass_glossy_direct', 'Direct glossy')])
        nodes = graph['nodes']
        self.assertEqual(nodes[graph['root']]['inputs']['image'], 'sum')
        graded = [nodes[source] for source in nodes['sum']['inputs'].values()]
        self.assertEqual([g['type'] for g in graded], ['grade'] * 3)
        self.assertEqual(sorted(compositor.buffers(graph)), ['beauty', 'pass_diffuse_direct', 'pass_glossy_direct'])
        # The remainder: the beauty less the passes, as rendered.
        self.assertEqual(nodes['remainder_negative']['parameters'], {'operation': 'multiply', 'value': -1.0})
        self.assertEqual(sorted(nodes['remainder_passes']['inputs'].values()), ['pass_1', 'pass_2'])

    def test_with_every_grade_alone_it_adds_up_to_the_beauty(self):
        # Pictures as numbers: run the graph's arithmetic by hand.
        values = {'beauty': 10.0, 'p1': 3.0, 'p2': 4.5}
        graph = compositor.pass_graph([('p1', 'one'), ('p2', 'two')])

        def value(identity):
            node = graph['nodes'][identity]
            if node['type'] == 'input':
                return values[node['parameters']['buffer']]
            if node['type'] in ('sum', 'output'):
                return sum(value(source) for source in node['inputs'].values())
            if node['type'] == 'math':
                return value(node['inputs']['image']) * node['parameters']['value']
            if node['type'] == 'grade':
                held = compositor.parameters(node)
                return value(node['inputs']['image']) * 2.0 ** held['exposure']
            raise AssertionError(node['type'])
        self.assertAlmostEqual(value(graph['root']), 10.0)

    def test_the_passes_split_the_light_by_what_it_meets_first(self):
        expressions = [expression for words, name, expression in compositor.PASSES]
        self.assertEqual(len(set(expressions)), len(expressions))
        self.assertIn('CO', expressions)
        self.assertIn('CL', expressions)
        firsts = [e[1:].split('[')[0] for e in expressions if e not in ('CO', 'CL')]
        # Direct and indirect diffuse and glossy share their first event; the others each have one of their own.
        self.assertEqual(sorted(set(firsts)), ['<RD>', '<RG>', '<RS>', '<TD>', '<TG>', '<TS>'])


class Outputs(unittest.TestCase):
    def test_missing_passes_are_added_and_ones_there_are_taken_as_they_are(self):
        held = [{'name': 'my_diffuse', 'kind': 'lpe', 'expression': 'C<RD>[<L.>O]'}, {'name': 'pass_emission', 'kind': 'depth', 'expression': ''}]
        wanted = [('Emission', 'pass_emission', 'CO'), ('Direct diffuse', 'pass_diffuse_direct', 'C<RD>[<L.>O]')]
        entries, names = compositor.pass_outputs(held, wanted)
        self.assertEqual(names, ['pass_emission_2', 'my_diffuse'])
        self.assertEqual(entries[-1], {'name': 'pass_emission_2', 'kind': 'lpe', 'expression': 'CO'})
        self.assertEqual(len(entries), 3)
        again, names_again = compositor.pass_outputs(entries, wanted)
        self.assertEqual(again, entries)

    def test_they_are_outputs_the_scene_takes(self):
        from moonray_modo import outputs
        entries, names = compositor.pass_outputs([], compositor.PASSES)
        self.assertEqual(len(outputs.values(entries)), len(compositor.PASSES))


class Choices(unittest.TestCase):
    def test_the_scenes_own_light_paths_are_offered_too(self):
        held = [{'name': 'my_diffuse', 'kind': 'lpe', 'expression': 'C<RD>[<L.>O]'},
                {'name': 'rim_only', 'kind': 'lpe', 'expression': "C.*<L.'rim'>"}, {'name': 'depth', 'kind': 'depth', 'expression': ''}]
        self.assertEqual(compositor.scene_passes(held, compositor.PASSES), [('rim_only', 'rim_only', "C.*<L.'rim'>")])

    def test_passes_not_chosen_stay_in_the_remainder(self):
        values = {'beauty': 10.0, 'p1': 3.0}
        graph = compositor.pass_graph([('p1', 'one')])

        def value(identity):
            node = graph['nodes'][identity]
            if node['type'] == 'input':
                return values[node['parameters']['buffer']]
            if node['type'] in ('sum', 'output'):
                return sum(value(source) for source in node['inputs'].values())
            if node['type'] == 'math':
                return value(node['inputs']['image']) * node['parameters']['value']
            return value(node['inputs']['image'])
        self.assertAlmostEqual(value(graph['nodes']['remainder']['inputs']['in1']) + value('remainder_negative'), 7.0)
        self.assertAlmostEqual(value(graph['root']), 10.0)

    def test_without_the_remainder_the_composite_is_the_passes_alone(self):
        graph = compositor.pass_graph([('p1', 'one'), ('p2', 'two')], remainder=False)
        self.assertNotIn('remainder', graph['nodes'])
        self.assertEqual(sorted(compositor.buffers(graph)), ['p1', 'p2'])


class LightGroups(unittest.TestCase):
    def test_labels_from_modo_lights_mesh_lights_and_moonray_lights(self):
        production = {'lights': {'light1': {'label': 'key'}, 'light2': {'label': ''}, 'light3': {'label': 'rim'}},
                      'objects': {'mesh1': {'mesh_light': True, 'light_label': 'panel'}, 'mesh2': {'mesh_light': False, 'light_label': 'nope'}}}
        entities = [{'class': 'RectLight', 'parameters': {'label': 'fill'}}, {'class': 'SphereLight', 'parameters': {'label': 'key'}}]
        self.assertEqual(compositor.light_labels(production, entities), ['fill', 'key', 'panel', 'rim'])

    def test_the_environment_is_a_group_of_its_own_first(self):
        groups = compositor.light_groups({'lights': {'l': {'label': 'key'}}})
        self.assertEqual(groups, [('Environment', 'modo_environment'), ('key', 'key')])
        self.assertEqual(compositor.light_groups({}), [('Environment', 'modo_environment')])

    def test_a_group_is_all_the_light_from_its_lights(self):
        self.assertEqual(compositor.light_group_expression('key'), "C.*<L.'key'>")


if __name__ == '__main__':
    unittest.main()
