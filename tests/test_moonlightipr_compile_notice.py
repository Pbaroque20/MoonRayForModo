"""MoonLightIPR's cold compiles said in the status line: OptiX compiling a kernel its cache does not hold keeps the first
preview of a kind of scene after an install waiting a minute or more, with nothing on screen. The library tells of a
compile still going after a second and a half (a cached kernel is ready in under one), the session says COMPILING and
COMPILED, and the kit's status line says so, with the time so far, until it is done."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class CompileNotice(unittest.TestCase):
    def test_the_library_tells_of_a_compile_that_goes_on(self):
        self.assertIn('void setCompileNotice(std::function<void(bool compiling)> notice);',
                      text('moonlightipr/include/moonlightipr/moonlightipr.h'))
        renderer = text('moonlightipr/src/renderer.cpp')
        self.assertIn('std::chrono::milliseconds(1500)', renderer)
        self.assertIn('tellCompiling(true);', renderer)
        self.assertIn('if (told) tellCompiling(false);', renderer)

    def test_the_session_says_it_for_the_scene_compiled_for(self):
        session = text('moonlightipr/session/moonlightipr_session.cpp')
        self.assertIn('event(compiling ? "COMPILING" : "COMPILED", compilingFor)', session)
        # Set before the renderer is made (its first kernel), and to each scene's generation as it is loaded.
        self.assertLess(session.index('moonlightipr::setCompileNotice('), session.index('moonlightipr::Renderer renderer('))
        self.assertIn('compilingFor = generation;\n                settings = loader.apply(path);', session)

    def test_the_kit_shows_it_in_the_status_line(self):
        kit = ROOT / 'kit/MoonRayForModo/python/moonray_modo'
        wrapper = (kit / 'moonlightipr_session.py').read_text(encoding='utf-8')
        self.assertIn('compiling = QtCore.Signal(bool)', wrapper)
        self.assertIn("self.compiling.emit(parts[1] == 'COMPILING')", wrapper)
        render = (kit / 'render.py').read_text(encoding='utf-8')
        self.assertIn('self.moonlightipr.compiling.connect(self._moonlightipr_compiling)', render)
        self.assertIn('MoonLightIPR is compiling its GPU program', render)
        # Done: back to what the preview says while it renders.
        self.assertIn("self.status.emit('Rendering · '+self.backend_status)", render)


if __name__ == '__main__':
    unittest.main()
