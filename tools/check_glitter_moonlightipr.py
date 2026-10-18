"""The glitter scenes of tools/check_glitter.py through MoonLightIPR: packed as the plugin packs them and rendered by
the built session, to see whether glitter fails there. Printed for each: whether it packed, its warnings, whether
the session finished, and the picture's average. Usage: check_glitter_moonlightipr.py"""
import sys
import traceback
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
import check_moonlightipr_session as fixture  # noqa: E402
from check_glitter import scene  # noqa: E402

folder = root / 'test-results/glitter/moonlightipr'


def main():
    folder.mkdir(parents=True, exist_ok=True)
    cases = [('plain', {}), ('glitter_reference', {'show_glitter': True, 'glitter': 1.0}),
             ('glitter_object', {'show_glitter': True, 'glitter': 1.0, 'glitter_space': 4})]
    session = fixture.Session(folder)
    try:
        for name, parameters in cases:
            try:
                result = session.submit(scene(parameters))
                pixels = result.get('pixels')
                average = sum(pixels[1::4]) / max(1, len(pixels) // 4) if pixels else None
                print('%-18s finished, %d frames, average %s; warnings: %s' % (name, result['frames'], average, '; '.join(result['warnings'])[:200]), flush=True)
            except Exception:
                print('%-18s FAILED\n%s' % (name, traceback.format_exc()[-800:]), flush=True)
                if session.process.poll() is not None:
                    print('    the session ended with exit 0x%08x' % (session.process.returncode & 0xffffffff), flush=True)
                    session = fixture.Session(folder)
    finally:
        try:
            session.process.stdin.write(b'quit\n'); session.process.stdin.flush(); session.process.wait(timeout=30)
        except Exception:
            pass


if __name__ == '__main__':
    main()
