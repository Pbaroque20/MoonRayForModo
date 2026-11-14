"""Render MoonLightIPR scene files (.mls, as tools/probe_cl_moonlightipr_pack.py writes them) in one MoonLightIPR
session, each to <name>.pfm/.ppm/.png beside it (prefix ipr_). render_mls_files.py <file.mls> ... The files must be
packed at the harness size (960 x 540)."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture  # noqa: E402


def main():
    files = [pathlib.Path(p) for p in sys.argv[1:]]
    session = fixture.Session(files[0].parent)
    try:
        for path in files:
            session.generation += 1
            session.process.stdin.write(('scene %d %s\n' % (session.generation, path)).encode())
            session.process.stdin.flush()
            result = session.wait()
            target = path.with_name('ipr_' + path.stem)
            if result.get('pixels'):
                fixture.write_images(target, result['pixels'])
                try:
                    from PIL import Image
                    Image.open(target.with_suffix('.ppm')).save(target.with_suffix('.png'))
                except Exception:
                    pass
            print(path.name, result.get('event'), result.get('samples'), 'frames', result.get('frames'))
    finally:
        session.process.kill()


if __name__ == '__main__':
    main()
