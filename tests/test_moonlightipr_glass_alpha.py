"""Glass in alpha in MoonLightIPR (tools/port_glass_alpha.py): the session reads MOONRAY_MODO_GLASS_ALPHA as MoonRay does,
the kit passes it to the session and starts it again when it changes, and the kernel takes what is seen through glass
alone off the alpha and gives it to the Environment background pass."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class GlassAlphaTests(unittest.TestCase):
    def test_session_reads_the_switch(self):
        self.assertIn('std::getenv("MOONRAY_MODO_GLASS_ALPHA")', text('moonlightipr/src/renderer.cpp'))
        self.assertIn('unsigned glassAlpha;', text('moonlightipr/src/device/shared.h'))

    def test_kit_passes_the_switch(self):
        session = text('kit/MoonRayForModo/python/moonray_modo/moonlightipr_session.py')
        self.assertIn("env.insert('MOONRAY_MODO_GLASS_ALPHA', '1' if self.glass else '0')", session)
        self.assertIn('native.glass_alpha() != self.glass', session)

    def test_kernel(self):
        kernel = text('moonlightipr/src/device/kernel.cu')
        self.assertIn('seenThroughGlass(pixel, glassSeen)', kernel)
        self.assertIn('passTo(pixel, PASS_BACKGROUND, radiance, passMark, passShare)', kernel)
        self.assertIn('clamp(1.0f - throughGlass, 0.0f, 1.0f)', kernel)


if __name__ == '__main__':
    unittest.main()
