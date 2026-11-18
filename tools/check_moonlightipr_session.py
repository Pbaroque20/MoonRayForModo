"""Drive the MoonLightIPR session with packed snapshots, as the plugin will; run outside Modo.

Checks scene loading, progressive shared-memory frames, edits that reuse loaded meshes,
rejection of a bad scene, and shutdown. Writes the final frames to build/moonlightipr/session.
"""
import math
import os
import pathlib
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/moonlightipr'
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene
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
        self.process = subprocess.Popen([str(BUILD / 'bin/moonlightipr_session.exe'), str(BUILD / 'shaders/MoonLightIPRKernel.ptx')],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, creationflags=subprocess.CREATE_NO_WINDOW)

    def send(self, payload):
        self.generation += 1
        path = self.folder / ('%d.mls' % self.generation)
        path.write_bytes(payload)
        self.process.stdin.write(('scene %d %s\n' % (self.generation, path)).encode())
        self.process.stdin.flush()

    def submit(self, scene):
        started = time.perf_counter()
        payload, keys, warnings = moonlightipr_scene.pack(scene, WIDTH, HEIGHT, environment=0, known=self.known, samples=SAMPLES)
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
                _, event, generation = line.split()[:3]
                if event == 'SAMPLES':
                    # The samples a pixel of the frame about to come (the label under the picture).
                    if int(generation) == self.generation:
                        result['samples'] = int(line.split()[3])
                    continue
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


def hold_and_continue(session, scene):
    """A render held where it stands (pause: the mouse pressed for a drag, Follow drags on) sends nothing more, and taken
    up again (continue: let go having moved nothing) goes on from the samples it has to the end, at the pace it had. The
    last check of a session: its output is read on another thread from here on."""
    import queue
    import threading
    payload, keys, warnings = moonlightipr_scene.pack(scene, WIDTH, HEIGHT, environment=0, known=session.known, samples=SAMPLES)
    session.send(payload)
    lines = queue.Queue()

    def read():
        for raw in session.process.stdout:
            lines.put(raw.decode('utf-8', errors='replace').strip())
        lines.put(None)
    threading.Thread(target=read, daemon=True).start()
    state = {'samples': 0, 'done': False, 'frames': []}

    def take(seconds, until=lambda: False):
        """Events of this scene for up to seconds, or until until(); the samples said of the frames among them."""
        end = time.perf_counter() + seconds
        said = []
        while time.perf_counter() < end and not until():
            try:
                line = lines.get(timeout=max(0.0, end - time.perf_counter()))
            except queue.Empty:
                break
            if line is None:
                raise RuntimeError('Session exited early')
            if line.startswith('@@MODO_SHARED '):
                generation, key, width, height, pixels = receive(line, session.process.pid)
                if generation == session.generation:
                    state['frames'] = (state['frames'] + [pixels])[-3:]
            elif line.startswith('@@MODO_SESSION '):
                words = line.split()
                if int(words[2]) != session.generation:
                    continue
                if words[1] == 'SAMPLES':
                    state['samples'] = int(words[3]); said.append(state['samples'])
                elif words[1] == 'DONE':
                    state['done'] = True
        return said

    take(30, lambda: state['samples'] >= 40)
    if state['done'] or state['samples'] < 40:
        raise RuntimeError('The scene to hold did not get under way')
    session.process.stdin.write(b'pause\n'); session.process.stdin.flush()
    take(0.3)       # a frame already on its way
    paused = state['samples']
    after = take(1.5)
    if after or state['done']:
        raise RuntimeError('A held render went on sampling: %s' % after)
    session.process.stdin.write(('continue %d\n' % session.generation).encode()); session.process.stdin.flush()
    began = time.perf_counter()
    went_on = take(30, lambda: state['done'])
    seconds = time.perf_counter() - began
    if not state['done'] or not went_on or went_on[0] <= paused or state['samples'] != SAMPLES:
        raise RuntimeError('A render taken up again did not go on from %d samples to %d: %s' % (paused, SAMPLES, went_on[:5]))
    # The pace is 8 s for the whole render: what was left of it, not all of it again.
    left = 8.0 * (SAMPLES - paused) / SAMPLES
    if os.environ.get('MOONLIGHTIPR_PACE') is None and seconds > left + 2.0:
        raise RuntimeError('A render taken up again began its pace again: %.1f s for %.1f s left' % (seconds, left))
    print('%-22s held at %d samples, nothing sent for 1.5 s; went on from %d to %d in %.1f s (%.1f s left at its pace)'
          % ('Held and taken up', paused, went_on[0], SAMPLES, seconds, left))


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
        write_images(folder / 'moonlightipr_scene', full['pixels'])

        scene['camera'] = dict(scene['camera'], matrix=look_at([4, 2.5, 7.5], [0, .9, 0]))
        camera = session.submit(scene)
        report('Camera edit', camera)
        scene['materials'] = dict(scene['materials'], gold={'color': [.9, .9, .92], 'metallic': 1, 'roughness': .05})
        material = session.submit(scene)
        report('Material edit', material)
        scene['meshes'][1] = dict(scene['meshes'][1], instances=[placed(0, 1.6, 0), placed(-2.3, 1, 0)])
        moved = session.submit(scene)
        report('Transform edit', moved)
        write_images(folder / 'moonlightipr_scene_edited', moved['pixels'])

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
        write_images(folder / 'moonlightipr_scene_motion', motion['pixels'])
        if motion['pixels'] == recovered['pixels'] or mean(motion['pixels']) <= 0:
            raise RuntimeError('Motion blur and depth of field did not change the image')
        still = session.submit(scene)
        report('Still again', still)
        if abs(mean(still['pixels']) - mean(recovered['pixels'])) > .02 * mean(recovered['pixels']):
            raise RuntimeError('The scene did not return to rest after motion blur')

        hold_and_continue(session, scene)

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
