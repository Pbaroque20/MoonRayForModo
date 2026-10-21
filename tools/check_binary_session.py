"""A loaded MoonRay session fed scenes with their geometry as binary (rdlb.py): started from the text and the binary
file, changed by a delta that carries a changed list as text (its fingerprint changed), and reloaded from the text and
the binary file named together (text|binary). Run explicitly; never opens or changes Modo.

check_binary_session.py <runtime>"""
import argparse, copy, hashlib, queue, subprocess, sys, threading, time
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native, rdla, rdlb
from moonray_modo.scene_delta import difference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    args = parser.parse_args()
    runtime = native.find_runtime(args.runtime)
    out = root / 'test-results' / ('binary-session-' + time.strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True, exist_ok=False)
    scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 50, 'film_mm': 36},
             'materials': {'': {'color': [.7, .1, .1]}}, 'lights': [],
             'meshes': [{'name': 'quad', 'vertices': [[-.5, -.5, 0], [.5, -.5, 0], [.5, .5, 0], [-.5, .5, 0]],
                         'faces': [[0, 1, 2, 3]], 'uvs': [[0, 0], [1, 0], [1, 1], [0, 1]], 'material': '',
                         'matrix': rdla.IDENTITY[:]}],
             'render_settings': {'sampling_mode': 0}, 'preview_buffer': 'beauty'}

    def serialize(value, generation):
        value = copy.deepcopy(value)
        value['preview_buffer_file'] = str(out / ('%d.buffer.exr' % generation))
        with rdlb.collecting() as sink:
            text = rdla.scene_text(value, 64, 64, 1, 1)
        path = out / ('%d.full.rdla' % generation)
        path.write_text(text, encoding='utf-8')
        sink.write(path.with_suffix('.rdlb'))
        return text, path, sink
    previous, source, _ = serialize(scene, 1)
    assert '["vertex_list_0"] =' not in previous
    env = native.environment(runtime)
    env['MOONRAY_MODO_SESSION'] = str(out)
    env['MOONRAY_MODO_GENERATION'] = '1'
    messages = queue.Queue()
    arguments = native.arguments(source, out / 'main.exr', 4, 'scalar')
    arguments[2:2] = ['-in', str(source.with_suffix('.rdlb'))]
    process = subprocess.Popen([str(runtime / 'moonray.exe')] + arguments, cwd=out, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    seen = []

    def reader():
        with (out / 'session.log').open('wb') as log:
            for line in iter(process.stdout.readline, b''):
                log.write(line)
                log.flush()
                text = line.decode('utf-8', errors='replace').strip()
                seen.append(text)
                messages.put(text)
        messages.put('EXIT')
    thread = threading.Thread(target=reader, daemon=True)
    thread.start()

    def wait_done(generation):
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                line = messages.get(timeout=1)
            except queue.Empty:
                continue
            if line == '@@MODO_SESSION DONE %d' % generation:
                break
            if line == 'EXIT':
                raise RuntimeError('Renderer exited; inspect ' + str(out / 'session.log'))
        else:
            raise TimeoutError('Session did not complete frame %d' % generation)
        image = out / ('%d.buffer.exr' % generation)
        assert image.is_file() and image.stat().st_size > 16
        png = out / ('%d.png' % generation)
        subprocess.run([str(runtime / 'oiiotool.exe'), str(image), '-o', str(png)], env=native.environment(runtime),
                       check=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        return hashlib.sha256(png.read_bytes()).hexdigest()

    def send(generation, mode, path, full):
        command = out / 'command.tmp'
        command.write_text('%d\n%s\n%s\n%s\n' % (generation, mode, path, full), encoding='utf-8')
        command.replace(out / 'command.txt')
    try:
        first = wait_done(1)
        # The points move: only their fingerprint changes in the text, and the delta carries them as text.
        scene['meshes'][0]['vertices'] = [[x * 1.8, y * 1.8, z] for x, y, z in scene['meshes'][0]['vertices']]
        current, full, sink = serialize(scene, 2)
        delta = difference(previous, current, sink.text_of)
        assert delta is not None and '["vertex_list_0"] = {Vec3(' in delta, delta
        update = out / '2.delta.rdla'
        update.write_text(delta, encoding='utf-8')
        send(2, 'delta', update.as_posix(), '%s|%s' % (full.as_posix(), full.with_suffix('.rdlb').as_posix()))
        second = wait_done(2)
        assert first != second, 'Moved points did not change the picture'
        # New faces: a full reload, from the text and the binary file named together.
        previous = current
        scene['meshes'][0]['faces'] = [[0, 1, 2], [0, 2, 3]]
        scene['meshes'][0]['uvs'] = [[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]]
        scene['meshes'][0]['matrix'][12] = .4
        current, full, sink = serialize(scene, 3)
        assert difference(previous, current, sink.text_of) is None
        send(3, 'full', full.as_posix(), '%s|%s' % (full.as_posix(), full.with_suffix('.rdlb').as_posix()))
        third = wait_done(3)
        assert third != second, 'The reload did not change the picture'
        assert any(line == 'Modo session: scene files 2' for line in seen), 'The reload did not read two files'
        send(4, 'quit', '-', '-')
        assert process.wait(timeout=30) == 0
        print('One session rendered a binary start, a list delta and a two-file reload:', process.pid)
        print('Reports:', out)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
