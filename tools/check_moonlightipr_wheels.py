"""MoonLightIPR rendering a scene's turning parts outside Modo (tools/probe_cl_wheel_motion.py's wheels.pickle): the
parts at the frame, and with the shutter's ends held at the frame's own moment (motion blur off, as realtime shows it),
by the session given (SESSION: the build's, else the installed kit's with SESSION=kit). How many pixels the parts cover
in each, and how far the held picture is from the frame's: a part turning a third of a turn while the shutter was open
came out half its size where the matrices were blended number by number. Writes <name>.pfm/.ppm and report.json in
FOLDER (test-results/wheel-motion)."""
import json
import os
import pathlib
import pickle
import struct
import subprocess
import sys
import time
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import moonlightipr_scene  # noqa: E402

FOLDER = pathlib.Path(os.environ.get('FOLDER', str(ROOT / 'test-results/wheel-motion')))
KIT = pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo'
RUNTIME = str(KIT / 'runtime')
W, H = fixture.WIDTH, fixture.HEIGHT


class Session(fixture.Session):
    """The fixture's session, from the build or from the installed kit, held at a moment of the shutter."""

    def __init__(self, folder, installed):
        env = dict(os.environ)
        env['PATH'] = os.pathsep.join([str(ROOT / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/bin'), env.get('PATH', '')])
        self.folder, self.generation, self.known = folder, 0, set()
        if installed:
            exe, ptx = KIT / 'runtime/moonlightipr/moonlightipr_session.exe', KIT / 'runtime/moonlightipr/MoonLightIPRKernel.ptx'
        else:
            exe, ptx = fixture.BUILD / 'bin/moonlightipr_session.exe', fixture.BUILD / 'shaders/MoonLightIPRKernel.ptx'
        self.process = subprocess.Popen([str(exe), str(ptx)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                                        creationflags=subprocess.CREATE_NO_WINDOW)

    def held(self, held, moment=0.5):
        self.process.stdin.write(('vectors %d %.6f\n' % (1 if held else 0, moment)).encode())
        self.process.stdin.flush()


def pixels(result):
    return struct.unpack('<%df' % (W * H * 3), result['pixels'])


def covered(values, empty):
    return sum(1 for i in range(0, W * H * 3, 3)
               if any(abs(values[i + c] - empty[i + c]) > 0.05 * max(0.05, empty[i + c]) for c in range(3)))


def main():
    held = pickle.loads((FOLDER / 'wheels.pickle').read_bytes())
    # The parts were thinned (every so many faces kept): their normals, each corner's, no longer fit; shaded smooth from
    # their points instead, the same in each picture.
    for scene in held.values():
        scene['meshes'] = [{key: value for key, value in mesh.items() if key != 'normals'} for mesh in scene['meshes']]
    # Parts read before motion.apply_motion kept where each stands at the frame: taken from the frame's own reading, as
    # apply_motion now keeps them (FRAMED=0 leaves them out, for the session to blend between the ends alone).
    if os.environ.get('FRAMED', '1') == '1':
        at_frame = {mesh['identity']: mesh for mesh in held['frame']['meshes']}
        for mesh in held['moving']['meshes']:
            still = at_frame.get(mesh['identity'])
            if still is None:
                continue
            if 'instances' in mesh and 'instances_frame' not in mesh and len(still.get('instances') or []) == len(mesh['instances']):
                mesh['instances_frame'] = still['instances']
            elif 'instances' not in mesh and 'matrix_frame' not in mesh and mesh.get('matrix') != mesh.get('matrix_close'):
                mesh['matrix_frame'] = still.get('matrix')
    installed = os.environ.get('SESSION') == 'kit'
    label = ('kit' if installed else 'build') + ('' if os.environ.get('FRAMED', '1') == '1' else '-ends')
    session = Session(FOLDER, installed)
    report = {}
    try:
        with mock.patch('moonray_modo.native.default_runtime', return_value=RUNTIME), \
                mock.patch('moonray_modo.cache_folder.scene_cache', return_value=False):
            pictures = {}
            for name, scene, hold in (('empty', dict(held['frame'], meshes=[]), False), ('frame', held['frame'], False),
                                      ('held', held['moving'], True), ('blurred', held['moving'], False)):
                session.held(hold, 0.5)
                began = time.perf_counter()
                result = session.submit(dict(scene, _full_textures=True, _flat_out=True))
                pictures[name] = pixels(result)
                fixture.write_images(FOLDER / ('%s-%s' % (label, name)), result['pixels'])
                for stale in FOLDER.glob('*.mls'):
                    stale.unlink()
                report[name] = {'seconds': round(time.perf_counter() - began, 1), 'warnings': result['warnings'][:3]}
            empty = pictures['empty']
            for name in ('frame', 'held', 'blurred'):
                report[name]['covered'] = covered(pictures[name], empty)
            frame, moved = pictures['frame'], pictures['held']
            report['held_against_frame'] = {
                'mean_difference': round(sum(abs(a - b) for a, b in zip(frame, moved)) / len(frame), 5),
                'pixels_differing': sum(1 for i in range(0, W * H * 3, 3) if any(abs(frame[i + c] - moved[i + c]) > 0.05 for c in range(3)))}
    finally:
        session.process.kill()
    (FOLDER / ('report-%s.json' % label)).write_text(json.dumps(report, indent=1))
    print(label, json.dumps(report), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
