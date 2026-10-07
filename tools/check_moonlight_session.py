"""Drive the MoonLightIPR session with packed snapshots, as the plugin will; run outside Modo.

Checks scene loading, progressive shared-memory frames, edits that reuse loaded meshes,
rejection of a bad scene, and shutdown. Writes the final frames to build/moonlight/session.
"""
import math
import os
import pathlib
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/moonlight'
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlight_scene
from moonray_modo.shared_image import receive

WIDTH, HEIGHT, SAMPLES = 960, 540, 256


def look_at(eye, target):
    """A Modo-style matrix: basis vectors in rows, looking down local -Z."""
    back = [e - t for e, t in zip(eye, target)]
    length = math.sqrt(sum(v * v for v in back))
    back = [v / length for v in back]
    right = [back[2], 0.0, -back[0]]
    length = math.sqrt(sum(v * v for v in right))
    right = [v / length for v in right]
    up = [back[1] * right[2] - back[2] * right[1], back[2] * right[0] - back[0] * right[2], back[0] * right[1] - back[1] * right[0]]
    return right + [0.0] + up + [0.0] + back + [0.0] + list(eye) + [1.0]


def placed(x, y, z, scale=1.0):
    return [scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, x, y, z, 1]


def ball(segments=96, rings=48):
    vertices = [[math.sin(math.pi * r / rings) * math.cos(2 * math.pi * s / segments), math.cos(math.pi * r / rings),
                 math.sin(math.pi * r / rings) * math.sin(2 * math.pi * s / segments)] for r in range(rings + 1) for s in range(segments)]
    faces = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
             for r in range(rings) for s in range(segments)]
    return vertices, faces


def snapshot():
    vertices, faces = ball()
    cube = [[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    cube_faces = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return {
        'camera': {'matrix': look_at([0, 2.2, 8.5], [0, .9, 0]), 'focal_mm': 50.0, 'film_mm': 36.0},
        'materials': {'': {'color': [.5, .5, .5], 'roughness': .6},
                      'red': {'color': [.8, .1, .08], 'roughness': .8},
                      'gold': {'color': [1, .77, .34], 'metallic': 1, 'roughness': .2},
                      'blue': {'color': [.05, .2, .7], 'roughness': .1}},
        'meshes': [
            {'name': 'Ground', 'identity': 'ground', 'vertices': [[-20, 0, -20], [20, 0, -20], [20, 0, 20], [-20, 0, 20]],
             'faces': [[0, 3, 2, 1]], 'material': ''},
            # One shared prototype placed twice, as Modo mesh instances arrive.
            {'name': 'Ball', 'identity': 'ball', 'vertices': vertices, 'faces': faces, 'material': 'gold',
             'instances': [placed(0, 1, 0), placed(-2.3, 1, 0)], 'instance_ids': ['a', 'b']},
            # Faceted, with a material per polygon.
            {'name': 'Cube', 'identity': 'cube', 'vertices': cube, 'faces': cube_faces, 'smooth': False,
             'face_materials': ['blue', 'blue', 'red', 'red', 'blue', 'blue'], 'matrix': placed(2.3, .8, 0, .8)}],
        'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, .95, .85], 'intensity': 3.0, 'angle': 2.0,
                    'matrix': look_at([0, 0, 0], [-.5, -.8, .4])}],
        'environments': [{'kind': 'grad4', 'name': 'Sky', 'intensity': 1.0, 'zenith': [.2, .4, .9], 'sky': [.6, .75, 1],
                          'ground': [.3, .25, .2], 'nadir': [.1, .1, .1], 'sky_exponent': 4, 'ground_exponent': 4}]}


class Session:
    def __init__(self, folder):
        env = dict(os.environ)
        env['PATH'] = os.pathsep.join([str(ROOT / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/bin'), env.get('PATH', '')])
        self.folder, self.generation, self.known = folder, 0, set()
        self.process = subprocess.Popen([str(BUILD / 'bin/moonlight_session.exe'), str(BUILD / 'shaders/MoonLightKernel.ptx')],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, creationflags=subprocess.CREATE_NO_WINDOW)

    def send(self, payload):
        self.generation += 1
        path = self.folder / ('%d.mls' % self.generation)
        path.write_bytes(payload)
        self.process.stdin.write(('scene %d %s\n' % (self.generation, path)).encode())
        self.process.stdin.flush()

    def submit(self, scene):
        started = time.perf_counter()
        payload, keys, warnings = moonlight_scene.pack(scene, WIDTH, HEIGHT, environment=0, known=self.known, samples=SAMPLES)
        packed = time.perf_counter()
        self.send(payload)
        result = self.wait()
        if result['event'] != 'DONE':
            raise RuntimeError('Session did not finish scene %d' % self.generation)
        self.known = keys     # only acknowledged scenes prove what the session holds
        result.update(bytes=len(payload), pack_ms=(packed - started) * 1000, warnings=warnings,
                      first_ms=(result['first'] - packed) * 1000, done_ms=(result['done'] - packed) * 1000)
        return result

    def wait(self):
        """Read events for the current generation until it finishes or fails."""
        result = {'frames': 0, 'first': None, 'pixels': None}
        for raw in self.process.stdout:
            line = raw.decode('utf-8', errors='replace').strip()
            if line.startswith('@@MODO_SHARED '):
                generation, key, width, height, pixels = receive(line, self.process.pid)
                if generation == self.generation and (width, height) == (WIDTH, HEIGHT):
                    result['frames'] += 1
                    result['first'] = result['first'] or time.perf_counter()
                    result['pixels'] = pixels
            elif line.startswith('@@MODO_SESSION '):
                _, event, generation = line.split()
                if int(generation) == self.generation and event in ('DONE', 'FAILED'):
                    result.update(event=event, done=time.perf_counter())
                    return result
        raise RuntimeError('Session exited early')


def write_images(path, pixels):
    """PFM for comparison, and an sRGB PPM for a quick look. Frames arrive bottom row first."""
    path.with_suffix('.pfm').write_bytes(('PF\n%d %d\n-1.0\n' % (WIDTH, HEIGHT)).encode() + pixels)
    values = struct.unpack('<%df' % (WIDTH * HEIGHT * 3), pixels)
    encode = lambda v: round(255 * (12.92 * v if v <= .0031308 else 1.055 * v ** (1 / 2.4) - .055))
    rows = [bytes(encode(min(1.0, max(0.0, v))) for v in values[y * WIDTH * 3:(y + 1) * WIDTH * 3]) for y in reversed(range(HEIGHT))]
    path.with_suffix('.ppm').write_bytes(('P6\n%d %d\n255\n' % (WIDTH, HEIGHT)).encode() + b''.join(rows))


def mean(pixels):
    values = struct.unpack('<%df' % (len(pixels) // 4), pixels)
    if not all(math.isfinite(v) for v in values):
        raise RuntimeError('Frame contains non-finite pixels')
    return sum(values) / len(values)


def main():
    folder = BUILD / 'session'
    folder.mkdir(parents=True, exist_ok=True)
    for stale in folder.glob('*.mls'):
        stale.unlink()
    scene = snapshot()
    session = Session(folder)
    try:
        report = lambda label, r: print('%-22s %9d bytes, pack %6.1f ms, first frame %6.1f ms, %d samples %6.1f ms, %d frames, mean %.4f'
                                        % (label, r['bytes'], r['pack_ms'], r['first_ms'], SAMPLES, r['done_ms'], r['frames'], mean(r['pixels'])))
        full = session.submit(scene)
        report('Full scene', full)
        for warning in full['warnings']:
            print('  warning:', warning)
        write_images(folder / 'moonlight_scene', full['pixels'])

        scene['camera'] = dict(scene['camera'], matrix=look_at([4, 2.5, 7.5], [0, .9, 0]))
        camera = session.submit(scene)
        report('Camera edit', camera)
        scene['materials'] = dict(scene['materials'], gold={'color': [.9, .9, .92], 'metallic': 1, 'roughness': .05})
        material = session.submit(scene)
        report('Material edit', material)
        scene['meshes'][1] = dict(scene['meshes'][1], instances=[placed(0, 1.6, 0), placed(-2.3, 1, 0)])
        moved = session.submit(scene)
        report('Transform edit', moved)
        write_images(folder / 'moonlight_scene_edited', moved['pixels'])

        if not (camera['bytes'] < full['bytes'] // 10 and material['bytes'] < full['bytes'] // 10 and moved['bytes'] < full['bytes'] // 10):
            raise RuntimeError('An edit resent mesh data the session already held')
        if min(mean(r['pixels']) for r in (full, camera, material, moved)) <= 0:
            raise RuntimeError('A frame is black')
        if full['pixels'] == camera['pixels'] or material['pixels'] == moved['pixels']:
            raise RuntimeError('An edit did not change the image')

        session.send(b'not a scene')
        if session.wait()['event'] != 'FAILED':
            raise RuntimeError('A malformed scene was not rejected')
        recovered = session.submit(scene)
        report('After rejected scene', recovered)

        # Motion blur and depth of field: the camera slides, one ball rises and the cube shears
        # between the shutter opening and closing, seen through a wide lens.
        cube = scene['meshes'][2]
        blurred = dict(scene, motion_steps=[-.25, .25],
                       camera=dict(scene['camera'], matrix_close=look_at([4.4, 2.5, 7.5], [0, .9, 0]), dof=True, f_stop=.5, focus_distance=8.5),
                       meshes=[scene['meshes'][0],
                               dict(scene['meshes'][1], instances_close=[placed(0, 2.4, 0), placed(-2.3, 1, 0)]),
                               dict(cube, vertices_close=[[x + .6 * y, y, z] for x, y, z in cube['vertices']])])
        motion = session.submit(blurred)
        report('Motion blur and lens', motion)
        write_images(folder / 'moonlight_scene_motion', motion['pixels'])
        if motion['pixels'] == recovered['pixels'] or mean(motion['pixels']) <= 0:
            raise RuntimeError('Motion blur and depth of field did not change the image')
        still = session.submit(scene)
        report('Still again', still)
        if abs(mean(still['pixels']) - mean(recovered['pixels'])) > .02 * mean(recovered['pixels']):
            raise RuntimeError('The scene did not return to rest after motion blur')

        session.process.stdin.write(b'quit\n')
        session.process.stdin.flush()
        if session.process.wait(timeout=10) != 0:
            raise RuntimeError('Session did not exit cleanly')
        print('MoonLightIPR session check passed')
    finally:
        if session.process.poll() is None:
            session.process.kill()


if __name__ == '__main__':
    main()
