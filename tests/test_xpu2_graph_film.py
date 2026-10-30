import unittest
import test_xpu2_streamed_film as fixture
from xpu2.graph_film_evidence import validate_graph,compare_graph

class GraphFilmTests(unittest.TestCase):
    def profile(self):
        p=fixture.StreamedFilmTests().profile();p.update(graph_enabled=1,graph_captures=1,graph_sources_freed=1,graph_builds=1,graph_frees=1,graph_launches=2,graph_build_ns=0)
        return p
    def test_replay_requires_live_dispatches(self):
        p=self.profile();self.assertEqual(validate_graph(p,'fast')['status'],'passed')
        p['graph_launches']=1
        with self.assertRaises(ValueError):validate_graph(p,'fast')
    def test_graph_source_must_be_destroyed(self):
        p=self.profile();p['graph_sources_freed']=0
        with self.assertRaises(ValueError):validate_graph(p,'fast')
    def test_executable_must_be_destroyed(self):
        p=self.profile();p['graph_frees']=0
        with self.assertRaises(ValueError):validate_graph(p,'fast')
    def test_failed_build_cannot_launch(self):
        p=self.profile();p.update(errors=2,accepted=0,replaced=0,cpu_skipped=0,shader_checked=0,graph_builds=0,graph_frees=0,graph_launches=0,async_batches=0,async_completed=0,completion_waits=0,dispatches=0)
        self.assertEqual(validate_graph(p,'graph_build_fault')['status'],'passed')
        p['graph_launches']=1
        with self.assertRaises(ValueError):validate_graph(p,'graph_build_fault')
    def test_enqueued_failure_must_drain(self):
        p=self.profile();p.update(errors=2,accepted=0,replaced=0,cpu_skipped=0,shader_checked=0,async_completed=0,completion_waits=0,error_drains=2)
        self.assertEqual(validate_graph(p,'graph_launch_fault')['status'],'passed')
        p['error_drains']=1
        with self.assertRaises(ValueError):validate_graph(p,'graph_launch_fault')
