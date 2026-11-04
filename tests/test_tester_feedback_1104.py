"""A tester's look-dev and MoonLightIPR reports (2026-11-04): a node moved, or added wired to nothing, in the graph editor
restarted the preview; a dw Metal or Base material's own roughness did nothing in MoonLightIPR (Modo's Material Ref
roughness was used)."""
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
        self.assertIn("selected = list(selected) + ['pbr_validity']", rdla)



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
    """Realtime with MoonRay and MoonRay LS where the standard XPU is chosen (XPU2 off), on the processor: an opt-in."""

    def test_an_opt_in_on_the_xpu_page(self):
        source = (KIT / 'moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("'xpu_realtime': (False, bool)", source)
        cfg = (KIT.parent / 'preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.xpuRealtime ?', cfg)

    def test_rt_follows_moonray_and_moonray_ls_on_the_processor(self):
        panel = (KIT / 'moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn("if self._engine()!='moonray':return False\n        if self.preferences.get('xpu_realtime'):return True", panel)
        self.assertIn("scene=dict(scene,execution_mode='vectorized')", panel)


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
        self.assertIn('const ReplaySteps<VolumeMarch<Backend>> lookup{march, count, weights != 0.0f ? weights : 1.0f, weights == 0.0f};', integrator)
        core = (self.X / 'volume_core.h').read_text(encoding='utf-8')
        self.assertIn('constexpr bool GpuVdb = true;', core)
        self.assertIn('constexpr U32 MarchLimit = 1u << 14;', core)

    def test_the_probe_asks_the_cards_rule(self):
        suit = (self.X / 'device_suit.h').read_text(encoding='utf-8')
        self.assertIn('if (!volume::gpuRenders(v, hostGrids)) defer = true;', suit)

if __name__ == '__main__':
    unittest.main()
