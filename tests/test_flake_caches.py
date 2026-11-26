"""Dense glitter in MoonRay's Vector and XPU modes (tools/port_flake_caches.py, MOONRAY_MODO_FLAKE_CACHES): the stochastic
flakes lobe's two reflection caches, a 2.8 MB stack frame as varying locals, are taken from a block of the thread's own
on the heap, so that Vector and XPU renders of fine or dense glitter no longer end with a stack overflow."""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import native  # noqa: E402


def tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


port = tool('port_flake_caches')

# The two functions as MoonRay has them (BsdfStochasticFlakes.ispc), cut to what the port anchors on.
UPSTREAM = '''#define UNIFORM_SAMPLING 0

varying Color
StochasticFlakesBsdfLobe_eval(const varying BsdfLobe * uniform lobe,
                              const varying BsdfSlice &slice,
                              const Vec3f &wi,
                              varying float * uniform pdf)
{
    varying StochasticFlakesBsdfLobe * uniform sfLobe =
            (varying StochasticFlakesBsdfLobe * uniform) lobe;
    // The bsdf from [2016] is not reciprocal (evaluating reflection cache based on Wo)
    // Using an additional reflection cache computed using Wi and
    // averaging the D term in the bsdf is a cheat we use to make
    // this bsdf reciprocal.
    varying FlakeCaches evalCachesWo, evalCachesWi;
    varying bool validCache = StochasticFlakesBsdfLobe_computeReflectionCache(sfLobe, slice.mWo, evalCachesWo, false);
    return StochasticFlakesBsdfLobe_computeBrdf(sfLobe, slice, wi, evalCachesWo, evalCachesWi, pdf);
}

varying Color
StochasticFlakesBsdfLobe_sample(const varying BsdfLobe * uniform lobe,
                                const varying BsdfSlice &slice,
                                varying float r1, varying float r2,
                                varying Vec3f &wi, varying float &pdf)
{
    varying StochasticFlakesBsdfLobe * uniform sfLobe =
            (varying StochasticFlakesBsdfLobe * uniform) lobe;

    varying FlakeCaches sampleCachesWo;
    // generate reflection cache and weights with weighted CDF
    // Same as in eval() - we use an additional reflection cache created
    // using Wi to enforce reciprocity in bsdf computation
    varying FlakeCaches sampleCachesWi;
    validCache = StochasticFlakesBsdfLobe_computeReflectionCache(sfLobe, wi, sampleCachesWi, false);
    return StochasticFlakesBsdfLobe_computeBrdf(sfLobe, slice, wi, sampleCachesWo, sampleCachesWi, &pdf);
}
'''


class FlakeCachesPort(unittest.TestCase):
    def patched(self, text):
        return port.patch_text('BsdfStochasticFlakes.ispc', text, port.EDITS['ispc/bsdf/BsdfStochasticFlakes.ispc'])

    def test_the_caches_leave_the_stack_unless_the_switch_is_off(self):
        for ending in ('\n', '\r\n'):
            text = self.patched(UPSTREAM.replace('\n', ending)).replace(ending, '\n')
            # Each entry asks for the two caches on the heap; with none (the switch off) it runs MoonRay's stack caches,
            # in a function of their own, so the entry's own frame stays small.
            for name, args in (('eval', 'lobe, slice, wi, pdf'), ('sample', 'lobe, slice, r1, r2, wi, pdf')):
                entry = text[text.index('varying Color\nStochasticFlakesBsdfLobe_%s(' % name):]
                entry = entry[:entry.index('\n}\n')]
                self.assertIn('CPP_modoFlakeCaches(2 * sizeof(varying FlakeCaches))', entry)
                self.assertIn('StochasticFlakesBsdfLobe_%sWith(%s, caches[0], caches[1]);' % (name, args), entry)
                self.assertIn('return StochasticFlakesBsdfLobe_%sOnStack(%s);' % (name, args), entry)
                self.assertNotRegex(entry, r'varying FlakeCaches \w+[,;]')   # no cache as a local of its own
                self.assertIn('static noinline varying Color\nStochasticFlakesBsdfLobe_%sOnStack(' % name, text)
            # No cache is declared anywhere but in the two stack functions.
            self.assertEqual(text.count('varying FlakeCaches evalCachesWo, evalCachesWi;'), 1)
            self.assertEqual(text.count('varying FlakeCaches sampleCachesWo, sampleCachesWi;'), 1)
            self.assertEqual(text.count('varying FlakeCaches sampleCachesWo;'), 0)
            self.assertEqual(text.count('varying FlakeCaches sampleCachesWi;'), 0)
            self.assertIn('extern "C" uniform intptr_t\nCPP_modoFlakeCaches(uniform int64 bytes);', text)
            # Run again, it changes nothing.
            self.assertEqual(self.patched(text), text)

    def test_the_heap_block_and_the_switch(self):
        self.assertIn('const char *value = std::getenv("MOONRAY_MODO_FLAKE_CACHES");\n        return !value || value[0] != \'0\';',
                      port.HEADER_TEXT)
        cpp = port.CPP_INCLUDE_NEW
        self.assertIn('extern "C" intptr_t\nCPP_modoFlakeCaches(int64_t bytes)', cpp)
        self.assertIn('if (!moonray::shading::modoFlakeCaches() || bytes <= 0) {\n        return 0;', cpp)
        self.assertIn('thread_local Held held;', cpp)
        self.assertIn('_aligned_malloc(size, 64)', cpp)
        default_on = tool('port_switches_default_on')
        self.assertIn('FLAKE_CACHES', default_on.SWITCHES)
        self.assertEqual(default_on.READS['moonray/lib/rendering/shading/bsdf/ModoFlakeCaches.h'], 1)

    def test_the_tree_and_the_patch_have_it(self):
        # Where the upstream tree is checked out, it is as the port leaves it; the shipped patch carries it.
        source = port.SHADING / 'ispc/bsdf/BsdfStochasticFlakes.ispc'
        if source.exists():
            text = source.read_bytes().decode('utf-8')
            self.assertEqual(self.patched(text), text)
        patch = (ROOT / 'patches/native-windows/moonray.patch').read_text(encoding='utf-8')
        self.assertIn('+CPP_modoFlakeCaches(int64_t bytes)', patch)
        self.assertIn('b/lib/rendering/shading/bsdf/ModoFlakeCaches.h', patch)
        self.assertIn('StochasticFlakesBsdfLobe_sampleOnStack', patch)

    def test_the_kit_sets_the_switch_from_its_preference(self):
        with mock.patch.dict(sys.modules, {'PySide2': None}):
            for value in ('1', '0'):
                with mock.patch.dict(os.environ, {'MOONRAY_MODO_FLAKE_CACHES': value}):
                    self.assertEqual(native.environment(KIT)['MOONRAY_MODO_FLAKE_CACHES'], value)
            with mock.patch.dict(os.environ, {}):
                os.environ.pop('MOONRAY_MODO_FLAKE_CACHES', None)
                self.assertTrue(native.flake_caches())
        self.assertIn("'flake_caches': (True, bool)", (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8'))
        self.assertIn("lx.bless(switch('flake_caches'),'moonray.pref.flakeCaches')",
                      (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8'))
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        section = page[page.index('<hash type="Sheet" key="MoonRaySourceOverrides:sheet">'):]
        self.assertIn('cmd moonray.pref.flakeCaches ?', section[:section.index('</hash>')])
        # A realtime session started with the other setting is started again.
        self.assertIn('glass_alpha(), flake_caches())', (KIT / 'python/moonray_modo/native.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
