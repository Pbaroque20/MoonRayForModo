"""Blobs and Sprites in MoonLightIPR, outside Modo: snapshots pickled by tools/probe_cl_moonlightipr_snapshot.py (a scene
read as MoonLightIPR reads it) rendered by a runtime's MoonLightIPR session, each saved as <pickle>.moonlightipr.png
with the warnings the packing gave.

check_moonlightipr_particles.py <runtime folder> <snapshot.pickle> [...] [--samples N] [--size WxH]"""
import argparse
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import moonlightipr_scene, native  # noqa: E402


class Session(fixture.Session):
    """The runtime's own MoonLightIPR session (runtime/moonlightipr), not a build's."""

    def __init__(self, folder, runtime):
        folder.mkdir(parents=True, exist_ok=True)
        self.folder, self.generation, self.known, self.runtime = folder, 0, set(), runtime
        own = runtime / 'moonlightipr'
        env = native.environment(runtime)
        env['PATH'] = os.pathsep.join([str(own), str(runtime), env.get('PATH', '')])
        self.process = subprocess.Popen([str(own / 'moonlightipr_session.exe'), str(own / 'MoonLightIPRKernel.ptx')],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runtime')
    parser.add_argument('pickles', nargs='+')
    parser.add_argument('--samples', type=int, default=256)
    parser.add_argument('--size', default='960x540')
    args = parser.parse_args()
    runtime = native.find_runtime(args.runtime)
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    width, height = (int(v) for v in args.size.split('x'))
    session = Session(ROOT / 'test-results/moonlightipr-particles', runtime)
    try:
        for name in args.pickles:
            path = Path(name)
            scene = pickle.loads(path.read_bytes())
            started = time.perf_counter()
            payload, keys, warnings = moonlightipr_scene.pack(scene, width, height, 0.0, session.known, args.samples, denoise=False, runtime=runtime)
            packed = time.perf_counter() - started
            session.send(payload)
            result = session.wait()
            if result['event'] != 'DONE':
                print(path.name, 'MoonLightIPR did not finish:', result.get('event'))
                continue
            session.known = keys
            pfm = path.with_suffix('.moonlightipr.pfm')
            pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (width, height)).encode() + result['pixels'])
            png = path.with_suffix('.moonlightipr.png')
            subprocess.run([str(runtime / 'oiiotool.exe'), str(pfm), '--colorconvert', 'linear', 'sRGB', '-o', str(png)], env=native.environment(runtime), check=True)
            print(path.name, 'packed in %.2f s, %d bytes; warnings: %s' % (packed, len(payload), warnings), '->', png)
    finally:
        try:
            session.process.stdin.write(b'quit\n')
            session.process.stdin.flush()
            session.process.wait(timeout=10)
        except Exception:
            pass
        if session.process.poll() is None:
            session.process.kill()


if __name__ == '__main__':
    main()
