"""MoonLightIPR's first preview after an install waits while OptiX compiles its kernel (asked 2026-11-24: "1 minute
waiting is a long time for a user"). Three things make it shorter:

- the kernel's costliest code is written once where it was copies inlined side by side (OptiX's compile time grows
  faster than the code), without __noinline__: any call that is not inlined made every render 12-20% slower;
- the session compiles only the kernel the first scene wants, not the plain one first and then that one;
- the kernels this machine has used are compiled into OptiX's cache in the background as Modo opens (--warm)."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


def body(source, signature):
    """The text of the function that begins with signature, to its closing brace."""
    start = source.index(signature)
    depth, i = 0, source.index('{', start)
    while True:
        depth += {'{': 1, '}': -1}.get(source[i], 0)
        if depth == 0:
            return source[start:i + 1]
        i += 1


class SmallerKernel(unittest.TestCase):
    kernel = text('moonlightipr/src/device/kernel.cu')

    def test_nothing_is_left_out_of_line(self):
        # A call that is not inlined cost every render 12-20%, even one never made (tested 2026-11-24), and OptiX
        # inlines anything that calls its API whatever it is told.
        self.assertNotIn('__noinline__', self.kernel)
        self.assertNotIn('__noinline__', text('moonlightipr/src/device/vec.h'))

    def test_direct_light_evaluates_the_bsdf_and_traces_its_shadow_once(self):
        direct = body(self.kernel, 'ML_INLINE float3 directLight(')
        self.assertEqual(direct.count('evalBsdf('), 1)
        self.assertEqual(direct.count('shadow(shadowFrom('), 1)
        # In the order the numbers were drawn before: the environment, the distant lights, the light picked once they
        # are done, then that light.
        self.assertIn('if (k == distantEnd) {', direct)
        self.assertLess(direct.index('if (k < envParts) {'), direct.index('} else if (k < distantEnd) {'))
        self.assertLess(direct.index('sampleEnv('), direct.index('sampleDistant('))
        self.assertLess(direct.index('sampleDistant('), direct.index('sampleLight('))

    def test_fog_lights_each_scattering_with_one_call(self):
        # The scattering point itself is order 0 of the loop that follows the light on through the fog: one call of
        # fogLight for a grid fog and one for a fog the path is inside, where there were two of each.
        raygen = body(self.kernel, 'extern "C" __global__ void __raygen__moonlightipr()')
        self.assertEqual(raygen.count('fogLight('), 2)
        self.assertEqual(raygen.count('for (unsigned order = 0;; ++order) {'), 2)

    def test_a_light_is_tinted_by_one_call_of_each_filter(self):
        self.assertEqual(body(self.kernel, 'ML_INLINE float3 lightTint(').count('filterFactor('), 1)

    def test_a_bump_reads_the_layers_beside_the_point_in_one_loop(self):
        hit = body(self.kernel, 'extern "C" __global__ void __closesthit__radiance()')
        self.assertEqual(hit.count('evalLayers('), 2)    # beside the point, and in resolveMaterial's place
        loop = hit[hit.index('#pragma unroll 1'):]
        self.assertTrue(re.match(r'#pragma unroll 1\s+for \(unsigned side = bumped \? 0u : 4u; side < \(sloped \? 5u : 4u\); \+\+side\)', loop))


class FirstSceneKernelOnly(unittest.TestCase):
    renderer = text('moonlightipr/src/renderer.cpp')

    def test_no_kernel_is_compiled_before_a_scene_asks(self):
        constructor = body(self.renderer, 'Renderer::Renderer(const std::string& ptxPath)')
        self.assertNotIn('createPipeline', constructor)
        self.assertIn('if (pipeline && features == kernelFeatures) return;', self.renderer)

    def test_a_launch_before_any_scene_takes_the_plain_kernel(self):
        self.assertIn('if (!pipeline) specialize(0);', self.renderer)
        self.assertIn('impl->ready();', body(self.renderer, 'void Renderer::render()'))
        self.assertIn('impl->ready();', body(self.renderer, 'void Renderer::displacementValues('))

    def test_each_kernel_used_is_written_down_beside_the_cache(self):
        self.assertIn('"\\\\MoonLightIPRKernels.txt"', self.renderer)
        self.assertIn('remember(features);', body(self.renderer, '    void specialize(unsigned features)'))


class WarmUp(unittest.TestCase):
    def test_the_session_compiles_in_the_background_and_exits(self):
        session = text('moonlightipr/session/moonlightipr_session.cpp')
        warm = body(session, 'int warm(int argc, char** argv)')
        # Not below normal priority: a render that kept every processor busy left it nothing (2026-11-25).
        self.assertNotIn('PRIORITY_CLASS', warm)
        self.assertIn('hardware_concurrency() / 2', warm)
        self.assertIn('MOONLIGHTIPR_COMPILE_THREADS', warm)
        self.assertIn('ullAvailPhys < (6ull << 30)', warm)
        self.assertIn('Local\\\\MoonLightIPRWarm', warm)
        self.assertIn('warming.usedKernels()', warm)
        self.assertIn('if (argc >= 3 && std::string(argv[1]) == "--warm") return warm(argc, argv);', session)
        self.assertIn('MOONLIGHTIPR_COMPILE_THREADS', self.renderer_text())

    def renderer_text(self):
        return text('moonlightipr/src/renderer.cpp')

    def test_the_kit_starts_it_as_modo_opens_where_moonlightipr_was_used(self):
        wrapper = text('kit/MoonRayForModo/python/moonray_modo/moonlightipr_session.py')
        warm = wrapper[wrapper.index('def warm_up('):]
        self.assertIn("'--warm'", warm)
        self.assertIn('used_kernels_list().is_file()', warm)
        self.assertIn("MOONRAY_MODO_MOONLIGHTIPR_WARM') == '0'", warm)
        self.assertNotIn('0x00004000', warm)     # not below normal: it must finish on a busy machine
        commands = text('kit/MoonRayForModo/lxserv/moonray_commands.py')
        hook = commands[commands.rindex('if not lx.service.Platform().IsHeadless():'):]
        self.assertIn('_moonlightipr_session.warm_up()', hook)


if __name__ == '__main__':
    unittest.main()
