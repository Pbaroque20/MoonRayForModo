"""Time a persistent MoonRay session through the kinds of edit a preview sees. Never opens or changes Modo.

Usage: time_persistent_preview.py <moonray-runtime> [execution mode, auto by default]
For each edit: whether it went as an update or as a whole scene, how long until the first picture and until the
last, and what the renderer said about its GPU on the way."""
import copy
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root / 'tools'), str(root / 'kit/MoonRayForModo/python')]
from moonray_modo import native, rdla
from moonray_modo.scene_delta import difference
import check_moonlight_session as fixture

SAID = ('executing an xpu render', 'gpu: setup complete', 'falling back to cpu', 'executing a vectorized render', 'gpu:')


def main():
    runtime = native.find_runtime(sys.argv[1])
    mode = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    out = root / 'test-results' / ('persistent-timing-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    scene = fixture.snapshot()
    scene.update(render_settings={'sampling_mode': 0}, preview_buffer='beauty')

    def serialize(value, generation):
        value = copy.deepcopy(value)
        value['preview_buffer_file'] = str(out / ('%d.buffer.exr' % generation))
        text = rdla.scene_text(value, 640, 360, 4, 1)
        path = out / ('%d.full.rdla' % generation)
        path.write_text(text, encoding='utf-8')
        return text, path

    previous, source = serialize(scene, 1)
    env = native.environment(runtime)
    env['MOONRAY_MODO_SESSION'] = str(out)
    env['MOONRAY_MODO_GENERATION'] = '1'
    messages = queue.Queue()
    process = subprocess.Popen([str(runtime / 'moonray.exe')] + native.arguments(source, out / 'main.exr', 0, mode), cwd=out, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)

    def reader():
        with (out / 'session.log').open('wb') as log:
            for line in iter(process.stdout.readline, b''):
                log.write(line)
                log.flush()
                messages.put((time.perf_counter(), line.decode('utf-8', errors='replace').strip()))
        messages.put((time.perf_counter(), 'EXIT'))
    threading.Thread(target=reader, daemon=True).start()

    def timed(title, generation, how, started):
        first, said = None, []
        while True:
            at, line = messages.get(timeout=300)
            if line == 'EXIT':
                raise RuntimeError('Renderer exited; see ' + str(out / 'session.log'))
            low = line.lower()
            for phrase in SAID:
                if phrase in low and line[-70:] not in said:
                    said.append('%.1fs %s' % (at - started, line[-70:]))
                    break
            if line.startswith('@@MODO_SESSION FRAME_beauty %d' % generation):
                first = first or at
                # The session waits for each picture to be taken before it writes the next.
                for path in out.glob('preview_%d_*.pfm' % generation):
                    try:
                        path.unlink()
                    except OSError:
                        pass
            if line == '@@MODO_SESSION DONE %d' % generation:
                print('%-28s %-7s first picture %6.1f s, done %6.1f s' % (title, how, (first or at) - started, at - started))
                for line in said[:6]:
                    print('      ' + line)
                return

    generation = 1
    try:
        timed('Session start', 1, 'full', time.perf_counter() - 0)
        edits = []
        def camera(s): s['camera']['matrix'] = list(s['camera']['matrix']); s['camera']['matrix'][12] += .3
        def light(s): s['lights'][0]['intensity'] = s['lights'][0].get('intensity', 1.0) * 1.5
        def colour(s):
            key = next(iter(s['materials']))
            s['materials'][key] = dict(s['materials'][key], color=[.2, .6, .9])
        def moved(s): s['meshes'][1]['matrix'] = list(s['meshes'][1].get('matrix') or rdla.IDENTITY); s['meshes'][1]['matrix'][12] += .4
        def reshaped(s): s['meshes'][1]['vertices'] = [[x, y * 1.2, z] for x, y, z in s['meshes'][1]['vertices']]
        def added(s): s['meshes'].append(dict(copy.deepcopy(s['meshes'][1]), name='Another', identity='another'))
        for title, edit in (('Camera moved', camera), ('Light brightened', light), ('Material colour', colour), ('Mesh moved', moved),
                            ('Camera moved again', camera), ('Mesh reshaped', reshaped), ('Mesh added', added), ('Camera after reload', camera)):
            edit(scene)
            generation += 1
            current, full = serialize(scene, generation)
            delta = difference(previous, current)
            started = time.perf_counter()
            if delta is None:
                command = '%d\nfull\n%s\n%s\n' % (generation, full.as_posix(), full.as_posix())
            else:
                update = out / ('%d.delta.rdla' % generation)
                update.write_text(delta, encoding='utf-8')
                command = '%d\ndelta\n%s\n%s\n' % (generation, update.as_posix(), full.as_posix())
            staged = out / 'command.tmp'
            staged.write_text(command, encoding='utf-8')
            staged.replace(out / 'command.txt')
            timed(title, generation, 'whole' if delta is None else 'update', started)
            previous = current
        staged = out / 'command.tmp'
        staged.write_text('%d\nquit\n-\n-\n' % (generation + 1), encoding='utf-8')
        staged.replace(out / 'command.txt')
        process.wait(timeout=30)
        print('log:', out / 'session.log')
    finally:
        if process.poll() is None:
            process.kill()


if __name__ == '__main__':
    main()
