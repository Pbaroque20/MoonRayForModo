"""Modo's evaluated geometry kept between Modo's sessions (geometry_cache, evaluated._capture_kept): a cold start reads
again only the surfaces of meshes whose fingerprint changed, and of whatever is not a plain mesh; takes the others from
the kept reading; keeps itself again only where a plain mesh was read anew; and reads whole where nothing is kept. The
environment's alpha check is kept in the cache folder too (environment_layers.has_alpha)."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import cache_folder, evaluated, geometry_cache, environment_layers  # noqa: E402


def reading(*owners):
    return {'surfaces': [], 'prototypes': {str(i): {'item': owner, 'material': 'm', 'part': ''} for i, owner in enumerate(owners)}}


class Changed(unittest.TestCase):
    def test_only_meshes_whose_fingerprint_changed_and_what_is_no_plain_mesh(self):
        before = {'a': '1', 'b': '2', 'c': '3'}
        now = {'a': '1', 'b': '9', 'c': '3', 'd': '4'}
        # b changed, d is new, r (a replicator's or a proxy's surface) has no fingerprint: read again; a and c kept.
        self.assertEqual(geometry_cache.changed(before, now, reading('a', 'b', 'c', 'r')), {'b', 'd', 'r'})

    def test_a_mesh_gone_is_read_again_where_a_surface_names_it(self):
        self.assertEqual(geometry_cache.changed({'a': '1'}, {}, reading('a')), {'a'})

    def test_nothing_changed(self):
        self.assertEqual(geometry_cache.changed({'a': '1'}, {'a': '1'}, reading('a')), set())


class CaptureKept(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        cache_folder.forget()
        cache_folder._HELD.update(root=pathlib.Path(self.folder.name), scene=True)
        self.calls = []
        real = evaluated.capture

        def fake(time, path=None, displaced=True, only=None, before=None, kept=True):
            if kept and only is None and before is None:
                return real(time, path, displaced)
            self.calls.append(None if only is None else set(only))
            return reading('a', 'b') if before is None else dict(before)
        patches = [mock.patch.object(evaluated, 'capture', fake), mock.patch.object(evaluated, '_load'),
                   mock.patch.object(geometry_cache, 'key', return_value=('k',)),
                   mock.patch.object(geometry_cache.threading, 'Thread', Inline),
                   mock.patch.object(geometry_cache, 'standing', side_effect=lambda data, time: self.stood),
                   mock.patch.object(geometry_cache, 'session', side_effect=lambda *displaced: self.memory)]
        self.memory = None
        self.stood = {'places': {'a': 'here'}, 'shading': 's'}
        for each in patches:
            each.start()
            self.addCleanup(each.stop)

    def tearDown(self):
        cache_folder.forget()
        self.folder.cleanup()

    def test_read_whole_then_kept_then_only_the_changed_mesh(self):
        with mock.patch.object(geometry_cache, 'fingerprints', return_value={'a': '1', 'b': '2'}):
            evaluated.capture(0.0)
        self.assertEqual(self.calls, [None])
        self.assertEqual(geometry_cache.LAST['refused'], 'none kept')
        # Nothing changed, nothing moved: no render cache made at all, the kept surfaces taken whole.
        with mock.patch.object(geometry_cache, 'fingerprints', return_value={'a': '1', 'b': '2'}):
            data = evaluated.capture(0.0)
        self.assertEqual(self.calls, [None])
        self.assertIs(geometry_cache.LAST['render_cache'], False)
        self.assertEqual(set(h['item'] for h in data['prototypes'].values()), {'a', 'b'})
        # An item moved: the render cache made for the surfaces' places, every mesh taken from the kept reading
        # (one name no item has), and kept again with where the items now stand.
        self.stood = {'places': {'a': 'there'}, 'shading': 's'}
        with mock.patch.object(geometry_cache, 'fingerprints', return_value={'a': '1', 'b': '2'}):
            evaluated.capture(0.0)
        self.assertEqual(self.calls[-1], {evaluated.NO_ITEM})
        self.assertEqual(geometry_cache.load(('k',))[2], self.stood)
        # b edited: its surfaces alone read again, and the reading kept again with b's new fingerprint.
        with mock.patch.object(geometry_cache, 'fingerprints', return_value={'a': '1', 'b': '5'}):
            evaluated.capture(0.0)
        self.assertEqual(self.calls[-1], {'b'})
        self.assertEqual(geometry_cache.load(('k',))[0], {'a': '1', 'b': '5'})

    def test_surfaces_only_the_render_cache_makes_are_never_taken_whole(self):
        # A replicator's or proxy's surfaces (standing None): the render cache is made every time.
        self.stood = None
        with mock.patch.object(geometry_cache, 'fingerprints', return_value={'a': '1', 'b': '2'}):
            evaluated.capture(0.0)
            evaluated.capture(0.0)
        self.assertEqual(self.calls, [None, {evaluated.NO_ITEM}])

    def test_held_in_memory_while_the_scene_is_open(self):
        # The scene's last reading held in memory: taken again without the kept one on disk, and let go on closing.
        self.memory = {'key': None, 'held': None, 'watched': {}}
        with mock.patch.object(geometry_cache, 'fingerprints', return_value={'a': '1', 'b': '2'}):
            evaluated.capture(0.0)
            for kept in pathlib.Path(self.folder.name).rglob('*.bin'):
                kept.unlink()
            data = evaluated.capture(0.0)
        self.assertTrue(geometry_cache.LAST.get('in_memory'))
        self.assertIs(geometry_cache.LAST['render_cache'], False)
        self.assertEqual(set(h['item'] for h in data['prototypes'].values()), {'a', 'b'})
        self.assertEqual(self.calls, [None])
        geometry_cache._SESSION.update(one=self.memory)
        geometry_cache._closed('one')
        self.assertNotIn('one', geometry_cache._SESSION)

    def test_no_adapter_digest_reads_whole(self):
        with mock.patch.object(geometry_cache, 'fingerprints', return_value=None):
            evaluated.capture(0.0)
            evaluated.capture(0.0)
        self.assertEqual(self.calls, [None, None])


class Inline:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class AlphaKept(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        cache_folder.forget()
        cache_folder._HELD.update(root=pathlib.Path(self.folder.name), scene=True)
        environment_layers._ALPHA.clear()
        self.image = pathlib.Path(self.folder.name) / 'sky.exr'
        self.image.write_bytes(b'not really an image')

    def tearDown(self):
        environment_layers._ALPHA.clear()
        cache_folder.forget()
        self.folder.cleanup()

    def test_oiiotool_is_asked_once_across_sessions(self):
        done = mock.Mock(returncode=0, stdout=b'<ImageSpec><alpha_channel>3</alpha_channel></ImageSpec>')
        with mock.patch.object(environment_layers.subprocess, 'run', return_value=done) as run, \
                mock.patch.object(environment_layers.native, 'tool', return_value=pathlib.Path('oiiotool.exe')), \
                mock.patch.object(environment_layers.native, 'environment', return_value=dict(os.environ)), \
                mock.patch.object(environment_layers, 'alpha_index', return_value=3):
            self.assertTrue(environment_layers.has_alpha(self.image))
            environment_layers._ALPHA.clear()   # Modo started again
            self.assertTrue(environment_layers.has_alpha(self.image))
        self.assertEqual(run.call_count, 1)


if __name__ == '__main__':
    unittest.main()
