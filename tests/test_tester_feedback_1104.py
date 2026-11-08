"""A tester's look-dev and MoonLightIPR reports (2026-11-04): a node moved, or added wired to nothing, in the graph editor
restarted the preview; a dw Metal or Base material's own roughness did nothing in MoonLightIPR (Modo's Material Ref
roughness was used)."""
import struct
import sys
import types
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))
sys.modules.setdefault('lx', types.ModuleType('lx'))
from moonray_modo import nodes


def graph():
    return {'version': 1, 'root': 'surface', 'nodes': {
        'surface': {'type': 'DwaBaseMaterial', 'parameters': {'roughness': 0.3}, 'inputs': {'albedo': 'image'}, 'position': [300, 50]},
        'image': {'type': 'ImageMap', 'parameters': {'texture': 'a.tx'}, 'inputs': {}, 'position': [0, 0], 'label': 'Paint'}},
        'overrides': []}


class LookDev(unittest.TestCase):
    def test_moving_a_node_renders_the_same(self):
        moved = graph()
        moved['nodes']['image']['position'] = [-500, 200]
        self.assertEqual(nodes.rendered(graph()), nodes.rendered(moved))

    def test_a_node_wired_to_nothing_renders_the_same(self):
        added = graph()
        added['nodes']['loose'] = {'type': 'ImageMap', 'parameters': {}, 'inputs': {}, 'position': [10, 10]}
        self.assertEqual(nodes.rendered(graph()), nodes.rendered(added))
        self.assertEqual(nodes.material_form({'node_graph': graph()}), nodes.material_form({'node_graph': added}))

    def test_a_value_or_a_wire_renders_anew(self):
        valued = graph()
        valued['nodes']['image']['parameters']['texture'] = 'b.tx'
        self.assertNotEqual(nodes.rendered(graph()), nodes.rendered(valued))
        wired = graph()
        wired['nodes']['loose'] = {'type': 'ImageMap', 'parameters': {}, 'inputs': {}}
        wired['nodes']['surface']['inputs']['specular'] = 'loose'
        self.assertNotEqual(nodes.rendered(graph()), nodes.rendered(wired))

    def test_the_preview_skips_a_write_with_nothing_new_and_the_editor_says_its_form_first(self):
        panel = (KIT / 'moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn("if reuse=='materials' and not settling and self._materials_as_rendered(items,self.changes.consumed_channels):return", panel)
        editor = (KIT / 'moonray_modo/node_editor.py').read_text(encoding='utf-8')
        self.assertIn('nodes.FORMS.setdefault(self.item.id,nodes.material_form(properties.read(self.item)))', editor)
        changes = (KIT / 'moonray_modo/changes.py').read_text(encoding='utf-8')
        self.assertIn('self.consumed_channels=set(self.channel_items)', changes)


class NativeRoughness(unittest.TestCase):
    def test_a_native_material_leaves_modos_highlight_out(self):
        source = (KIT / 'moonray_modo/moonlightipr_materials.py').read_text(encoding='utf-8')
        self.assertIn("for key in ('raw_roughness', 'shading_model'):", source)
        self.assertIn("source['_specular_strength'] = 1.0", source)


class MirroredMeshes(unittest.TestCase):
    """A mesh with a negative scale and normals of its own rendered black in MoonRay and XPU2."""

    def test_the_switch_reaches_moonray_and_the_preferences(self):
        native = (KIT / 'moonray_modo/native.py').read_text(encoding='utf-8')
        self.assertIn("env['MOONRAY_MODO_MIRRORED_MESHES'] = '1' if mirrored_meshes() else '0'", native)
        self.assertIn("camera_light_lpe(), mirrored_meshes(), dso_search())", native)
        cfg = (ROOT / 'kit/MoonRayForModo/preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.mirroredMeshes ?', cfg)

    def test_the_port_reverses_a_mirrored_mesh_and_xpu2_follows(self):
        port = (ROOT / 'tools/port_mirrored_meshes.py').read_text(encoding='utf-8')
        self.assertIn('if (mIsNormalReversed != modoMirror) {', port)
        self.assertIn('if (calculateSmoothNormal && modoMirrored(mPolyMeshData->mXforms)) {', port)
        scene = (ROOT / 'xpu2/interactive/cpu_scene.h').read_text(encoding='utf-8')
        self.assertIn('(on("MOONRAY_MODO_MIRRORED_MESHES")?16u:0u)', scene)
        self.assertIn('if(reversed!=mirrored){', scene)


class PbrValidity(unittest.TestCase):
    def test_a_diagnostic_in_the_preferences(self):
        from moonray_modo import options
        self.assertEqual(options.AOVS['pbr_validity'][1], {'result': 7, 'material_aov': 'pbr_validity'})
        cfg = (ROOT / 'kit/MoonRayForModo/preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.pbrValidity ?', cfg)
        self.assertNotIn('aov_pbr_validity', (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8'))
        rdla = (KIT / 'moonray_modo/rdla.py').read_text(encoding='utf-8')
        self.assertIn("selected = ['pbr_validity']", rdla)



class Shaderball(unittest.TestCase):
    """The graph editor's MoonRay Widget: XPU2 renders it at its size, up to 4096 samples, and an Object scale."""

    def test_xpu2_renders_it_at_its_size(self):
        source = (KIT / 'moonray_modo/material_preview.py').read_text(encoding='utf-8')
        self.assertNotIn("scene['execution_mode']='vectorized'", source)
        # XPU2 whatever the preview's choice (MoonRay XPU in the preferences), where its shaders are compiled.
        self.assertIn('self.renderer.session.always_xpu2=True', source)
        session = (KIT / 'moonray_modo/persistent.py').read_text(encoding='utf-8')
        self.assertIn("self.xpu2_active=bool(self.xpu2_chosen() and request['mode'] in ('xpu','auto')", session)
        self.assertIn('size=max(256,min(1024,int(round(shown/32.0))*32))', source)
        from moonray_modo.ipr import WIDGET_SAMPLES
        self.assertEqual([row[2][0] for row in WIDGET_SAMPLES], [1024, 2048, 4096])

    def test_the_scale_moves_everything_together(self):
        source = (KIT / 'moonray_modo/material_preview.py').read_text(encoding='utf-8')
        self.assertIn("def snapshot(material, library, all_parts=False, scale=1.0):", source)
        self.assertIn("'matrix':look_at(s((2.5,1.4,3.8)),s((0,-.22,0)))", source)
        self.assertIn("'width':2*scale,'height':2*scale", source)


class VdbVolumeFile(unittest.TestCase):
    def test_a_vdb_volume_takes_its_file(self):
        command = (KIT.parent / 'lxserv/moonray_entities.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(VolumeFile,'moonray.entity.volumeFile')", command)
        forms = (KIT.parent / 'entities.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.entity.volumeFile', forms)


class XpuRealtime(unittest.TestCase):
    """Realtime with MoonRay and MoonRay LS where the standard XPU is chosen (XPU2 off): an opt-in, on the processor or
    (since 2026-11-05) on the graphics card, one choice in Modo's Preferences and Preview Preferences."""

    def test_a_choice_on_the_xpu_page(self):
        source = (KIT / 'moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("'xpu_realtime_mode': ('', str)", source)
        self.assertIn("XPU_REALTIME_MODES = ('off', 'vector', 'xpu')", source)
        # The switch it replaces gives the default: on was the processor.
        self.assertIn("return 'vector' if self.get('xpu_realtime') else 'off'", source)
        self.assertIn("combo('xpu_realtime_mode'", source)
        cfg = (KIT.parent / 'preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.xpuRealtime ?', cfg)
        lxserv = (KIT.parent / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn("choice('xpu_realtime_mode',XPU_REALTIME_CHOICES,render_settings_changed)", lxserv)

    def test_rt_follows_moonray_on_the_processor_or_the_card(self):
        panel = (KIT / 'moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn("if self._engine()!='moonray':return False\n        if self.preferences.get('xpu_realtime_mode')!='off':return True", panel)
        self.assertIn("scene=dict(scene,execution_mode='xpu' if realtime_mode=='xpu' else 'vectorized')", panel)


class Xpu2FallbackSampling(unittest.TestCase):
    """XPU2 left the preview to MoonRay XPU: MoonRay's own sampling settings, which it then uses, are no longer greyed."""

    def test_a_fallback_frees_moonrays_sampling(self):
        from moonray_modo import xpu2_sampling
        try:
            xpu2_sampling.fell_back('it does not render this scene')
            self.assertFalse(xpu2_sampling.active())
        finally:
            xpu2_sampling.fell_back(None)

    def test_the_session_tells_of_it_and_the_form_looks_again(self):
        session = (KIT / 'moonray_modo/persistent.py').read_text(encoding='utf-8')
        self.assertIn('fallback=QtCore.Signal(str)', session)
        self.assertIn('xpu2_sampling.fell_back(reason)', session)
        render = (KIT / 'moonray_modo/render.py').read_text(encoding='utf-8')
        self.assertIn('self.session.fallback.connect(self._xpu2_fallback)', render)


class VdbOnTheCard(unittest.TestCase):
    """VDB volumes on XPU2's graphics card: NanoVDB grids uploaded and sampled there, a march with no table of steps (the
    card kept 34 and a cloud came out 1.6% too bright), and the cell probe asking the card's own rule."""
    X = ROOT / 'xpu2/interactive'

    def test_nanovdb_reaches_the_card(self):
        build = (self.X / 'gpu_build.py').read_text(encoding='utf-8')
        self.assertIn("'cuda/std/limits':HERE/'nvrtc_limits.h'", build)
        flags = (self.X / 'build_async.py').read_text(encoding='utf-8')
        self.assertIn("'-default-device'", flags)
        upload = (self.X / 'async_gpu.h').read_text(encoding='utf-8')
        self.assertIn('static_cast<const nanovdb::GridData*>(host)->mGridSize', upload)

    def test_the_card_marches_again_for_a_step(self):
        integrator = (self.X / 'async_integrator.h').read_text(encoding='utf-8')
        self.assertIn('struct ReplaySteps {', integrator)
        self.assertIn('const ReplaySteps<VolumeMarch<Backend>> lookup{march, count, weights != 0.0f ? weights : 1.0f, weights == 0.0f,', integrator)
        # Since 2026-11-08 from the first march's checkpoints, the same steps bit for bit (GPU_MARCH_CHECKPOINTS).
        self.assertIn('volume::gpuMarchCheckpoints() ? &record : nullptr};', integrator)
        self.assertIn('m.run(emit, from);', integrator)
        core = (self.X / 'volume_core.h').read_text(encoding='utf-8')
        self.assertIn('constexpr bool GpuVdb = true;', core)
        self.assertIn('constexpr U32 MarchLimit = 1u << 14;', core)

    def test_the_probe_asks_the_cards_rule(self):
        suit = (self.X / 'device_suit.h').read_text(encoding='utf-8')
        self.assertIn('if (!volume::gpuRenders(v, hostGrids)) defer = true;', suit)


class FirstGroupOpen(unittest.TestCase):
    """A node with neither Diffuse nor Specular (a map, a light filter) showed every group of its properties folded:
    its first group starts open, and a stored state that folds every group still leaves the first open."""

    def setUp(self):
        import re, sys
        sys.path.insert(0, str(KIT))
        from moonray_modo import nodes
        src = (KIT / 'moonray_modo/node_editor.py').read_text(encoding='utf-8')
        self.src = src
        self.ns = {'nodes': nodes, 'OPEN_GROUPS': ('diffuse', 'specular')}
        for name in ('grouped', 'default_folds'):
            exec(re.search(r'^def %s\(kind\):.*?(?=^def |\Z)' % name, src, re.S | re.M).group(0), self.ns)
        self.nodes = nodes

    def test_no_kind_starts_all_folded(self):
        grouped, folds = self.ns['grouped'], self.ns['default_folds']
        for kind in self.nodes.kinds():
            groups = {g for _, (g,) in grouped(kind) if g is not None}
            if len(groups) > 1:
                with self.subTest(kind=kind):
                    self.assertFalse(groups <= folds(kind))

    def test_dwabase_keeps_diffuse_and_specular(self):
        grouped, folds = self.ns['grouped'], self.ns['default_folds']
        groups = {g for _, (g,) in grouped('DwaBaseMaterial') if g is not None}
        self.assertEqual(groups - folds('DwaBaseMaterial'), {'Diffuse', 'Specular'})

    def test_stored_state_never_folds_every_group(self):
        self.assertIn('if groups and set(groups)<=folded:folded.discard(groups[0])', self.src)


class WiresFollowNodes(unittest.TestCase):
    """The tester's wires stayed put as nodes moved: a wire in the editor's list had been deleted by Qt, asking it for its
    scene threw at every move (the diagnostics' 'wires not redrawn'). Wires are found by a mark Qt keeps on each."""

    def test_wires_are_found_by_their_mark(self):
        editor = (KIT / 'moonray_modo/node_editor.py').read_text(encoding='utf-8')
        body = editor.split('    def edges(self):', 1)[1].split('    def remember(', 1)[0]
        self.assertIn("if item.data(WIRE)=='wire':self.canvas.removeItem(item)", body)
        self.assertIn("edge.setData(WIRE,'wire')", body)
        self.assertNotIn('for item in self.links', body)


class LinkedEngineChoices(unittest.TestCase):
    """XPU2 Sampling greyed under the standard XPU; the engine in Preview Preferences as well as Modo's Preferences, one
    setting, each place following the other; RT following both."""

    def test_xpu2_sampling_greyed_by_the_engine(self):
        lxserv = (KIT.parent / 'lxserv/moonray_render_settings.py').read_text(encoding='utf-8')
        block = lxserv.split("'xpu2_cpu', 'xpu2_realtime'):", 1)[1].split('# Smart Render', 1)[0]
        self.assertIn('return bool(native.xpu2())', block)

    def test_preview_preferences_offer_the_engine(self):
        prefs = (KIT / 'moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("combo('xpu2/renderer', [('XPU2', 'xpu2'), ('MoonRay XPU (standard)', 'xpu')]", prefs)

    def test_preview_preferences_offer_pbr_validity(self):
        # 2026-11-05: the Diagnostics switch in Preview Preferences too, the same setting as Modo's Preferences.
        prefs = (KIT / 'moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("form.addRow(check('pbr_validity', 'PBR validity output',", prefs)
        lxserv = (KIT.parent / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn("switch('pbr_validity',render_settings_changed)", lxserv)

    def test_modo_preferences_follow(self):
        lxserv = (KIT.parent / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn('class Switch(Followed,lxu.command.BasicCommand):', lxserv)
        self.assertIn('class Choice(Followed,lxu.command.BasicCommand):', lxserv)
        self.assertIn("choice('xpu_realtime_mode',XPU_REALTIME_CHOICES,render_settings_changed)", lxserv)

    def test_rt_follows_the_preferences(self):
        panel = (KIT / 'moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn('property_notifications.watchers.append(self._preferences_followed)', panel)
        self.assertIn('property_notifications.watchers.remove(self._preferences_followed)', panel)


class AlembicStreamed(unittest.TestCase):
    """Alembic loaded as Modo's own streamed items (Alembic Mesh, Curves, Point Cloud) has no mesh channel: the scene is
    read from Modo's render cache, frame by frame, so they render and blur (probe_alembic: all three load modes)."""

    def test_streamed_items_read_from_the_render_cache(self):
        host = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertIn("ALEMBIC_ITEMS = ('AlembicMesh', 'AlembicCurves', 'AlembicCloud')", host)
        self.assertIn('if alembic_items(scene):', host.split('def _snapshot(', 1)[1].split('camera = scene.renderCamera', 1)[0])

    def test_no_alembic_loader_is_no_items(self):
        import sys
        sys.path.insert(0, str(KIT))
        import types
        for name in ('lx', 'lxu', 'lxu.object', 'lxu.command', 'lxifc', 'modo'):
            sys.modules.setdefault(name, types.ModuleType(name))
        src = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        start = src.index('ALEMBIC_ITEMS = ')
        ns = {}
        exec(src[start:src.index('def snapshot(', start)], ns)
        class Scene:
            def items(self, kind, superType=False):
                if kind == 'AlembicMesh': return ['m']
                raise LookupError(kind)
        self.assertEqual(ns['alembic_items'](Scene()), ['m'])


class PbrValidityReplaces(unittest.TestCase):
    """PBR validity on: it takes the standard outputs' place in MoonRay XPU's and XPU2's renders, and the preview shows
    it; off, the standard outputs and the beauty again."""

    def test_outputs_replaced_while_on(self):
        rdla = (KIT / 'moonray_modo/rdla.py').read_text(encoding='utf-8')
        self.assertIn("if pbr_validity():\n            selected = ['pbr_validity']", rdla)

    def test_preview_shows_it_and_gives_it_back(self):
        panel = (KIT / 'moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn("self.buffer.setCurrentIndex(self.buffer.findData('pbr_validity'))", panel)
        self.assertIn("if was and self.buffer.currentData()=='pbr_validity':self.buffer.setCurrentIndex(self.buffer.findData('beauty'))", panel)


class ModoMeshLights(unittest.TestCase):
    """A tester's Modo Mesh Lights lit nothing (the kit skipped the type). The light shines from its Prototype mesh
    (shadeLoc), placed by the prototype or the light (Use Prototype Transform), its radiance per square metre as an area
    light's. Since 2026-11-05 a hidden Prototype gives no light, as in Modo (test_mesh_lights_1105)."""

    def test_radiance_over_the_area(self):
        import math, sys
        sys.path.insert(0, str(KIT))
        from moonray_modo import light_units
        self.assertAlmostEqual(light_units.intensity('meshLight', 3.0, {'area': 2.0}), 3.0 * math.pi * 2.0)
        # The same as an area light of that size.
        self.assertAlmostEqual(light_units.intensity('meshLight', 3.0, {'area': 2.0}),
                               light_units.intensity('areaLight', 3.0, {'width': 1.0, 'height': 2.0}))

    def test_written_as_a_mesh_light_with_its_own_geometry(self):
        import sys
        sys.path.insert(0, str(KIT))
        from moonray_modo import lighting
        light = {'kind': 'MeshLight', 'identity': 'meshLight1', 'name': 'Mesh Light', 'color': [1, 1, 1], 'intensity': 3.0,
                 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 0, 1],
                 'shape': {'vertices': [[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], 'faces': [[0, 1, 2, 3]],
                           'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 0, 1]}}
        lines = []
        lighting.emit({'lights': [light]}, [], 0, lines)
        text = '\n'.join(lines)
        self.assertIn('RdlMeshGeometry("/modo/light/meshLight1/geometry") {', text)
        self.assertIn('MeshLight("/modo/light/meshLight1") {', text)
        self.assertIn('["geometry"] = RdlMeshGeometry("/modo/light/meshLight1/geometry")', text)
        self.assertNotIn('table.insert(geometries', text)

    def test_seen_by_the_camera_in_moonlightipr(self):
        # The engine shows a mesh light where a camera ray meets its surface; a Modo Mesh Light's surface is its own,
        # found by camera rays alone, and only when Visible to Camera is on.
        import sys
        sys.path.insert(0, str(KIT))
        from moonray_modo import moonlightipr_scene
        shape = {'vertices': [[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], 'faces': [[0, 1, 2, 3]],
                 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 0, 1]}

        def packed(seen):
            scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                     'materials': {'': {'color': [.5, .5, .5], 'roughness': .6}}, 'meshes': [], 'environments': [],
                     'lights': [{'kind': 'MeshLight', 'identity': 'meshLight1', 'name': 'Mesh Light', 'color': [1, 1, 1],
                                 'intensity': 3.0, 'matrix': shape['matrix'], 'shape': shape, 'area': 4.0,
                                 'camera_visible': seen}]}
            return moonlightipr_scene.pack(scene, 320, 180, .2)
        shown, keys, _ = packed(True)
        hidden, none, _ = packed(False)
        self.assertEqual(len(keys), 1)
        self.assertEqual(len(none), 0)
        self.assertIn(struct.pack('<iI', 0, 1), shown)

    def test_the_kit_reads_the_prototype(self):
        host = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        self.assertIn("light.itemGraph('shadeLoc').forward()", host)
        self.assertIn("'meshLight': 'MeshLight'", host)
        self.assertIn("world_matrix(prototype if own else light)", host)


class CleanQuit(unittest.TestCase):
    """Modo crashed as it quit (0xC0000005 in its Python plug-in's clean-up): looking through every widget of Modo's
    (QApplication.allWidgets) gave each a Python wrapper; a graph editor left open was not put away; the preview's
    scene listener could never be removed, which stopped the window's putting away at it. Each found with a test Modo:
    tools/probe_quit_preview.py and tools/probe_quit_graph_editor.py."""

    def test_no_widget_scan_left(self):
        for path in list((KIT / 'moonray_modo').glob('*.py')) + list((KIT.parent / 'lxserv').glob('*.py')):
            text = path.read_text(encoding='utf-8')
            code = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('#'))
            with self.subTest(path=path.name):
                self.assertNotIn('.allWidgets()', code)

    def test_editors_closed_on_quit(self):
        editor = (KIT / 'moonray_modo/node_editor.py').read_text(encoding='utf-8')
        self.assertIn('application.aboutToQuit.connect(closing)', editor)
        self.assertIn('_close_on_quit()', editor)

    def test_listener_removed_through_its_own_object(self):
        changes = (KIT / 'moonray_modo/changes.py').read_text(encoding='utf-8')
        self.assertIn('self.com=lx.object.Unknown(self)', changes)
        self.assertIn('self.service.AddListener(self.com)', changes)
        self.assertIn('self.service.RemoveListener(self.com)', changes)

    def test_window_put_away_on_quit(self):
        panel = (KIT / 'moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn('application.aboutToQuit.connect(self.dispose)', panel)


class KitCompiles(unittest.TestCase):
    """Every Python file of the kit compiles: a module only Modo's Qt imports (preferences.py) once broke on a quote, with
    no other test to see it."""

    def test_every_kit_file_compiles(self):
        import py_compile
        for path in (KIT.parent).rglob('*.py'):
            with self.subTest(path=str(path)):
                py_compile.compile(str(path), doraise=True)

if __name__ == '__main__':
    unittest.main()
