"""How long the preview takes to show a picture after an HDRI environment is turned, by each way it can be turned.

A ball lit by an HDRI is rendered in MoonRay's loaded preview session (as the preview window uses it). The time to the
first picture is measured: for the first scene, for the HDRI turned by its locator (the environment light's own
transform, sent as a change to the scene), for the HDRI turned by its texture's UV rotation (which the plugin
bakes, with its other layers, into an image of its own), and for an HDRI over another layer turned by its locator
(baked once at rest, turned by the light's transform). The plugin's preparing of the scene is timed apart from
MoonRay's. Usage: time_hdri_rotation.py <runtime> <hdri>"""
import math
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))
import check_fresnel  # noqa: E402,F401  (sets the plugin's modules up without Modo)
from moonray_modo import native, rdla  # noqa: E402
from moonray_modo.scene_delta import difference  # noqa: E402

folder = root / 'test-results/hdri-rotation'


def turned(degrees):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1]


def scene(hdri, locator=0.0, uv_rotation=0.0, layered=False):
    image = {'kind': 'image', 'path': str(hdri), 'srgb': False, 'color_space': '(default)', 'matrix': turned(locator),
             'intensity': 1.0, 'effect': 'envColor', 'opacity': .9 if layered else 1, 'blend': 'normal', 'invert': False,
             'uv_matrix': [1, 0, 0, 0, 1, 0], 'rotation': uv_rotation, 'scale': [1, 1], 'transformed': uv_rotation != 0}
    # At less than full opacity, over a colour, the HDRI is one layer of several, which the plugin bakes together.
    under = {'kind': 'color', 'color': [.2, .3, .4], 'effect': 'envColor', 'opacity': 1, 'blend': 'normal', 'invert': False}
    environment = (dict(image) if not image['transformed'] and not layered
                   else {'kind': 'stack', 'intensity': 1.0, 'layers': [image] + ([under] if layered else [])})
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 50, 'film_mm': 36},
            'materials': {'': {'color': [.8, .8, .8], 'roughness': .2}},
            'meshes': [{'name': 'Ball', 'identity': 'ball', 'vertices': [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]],
                        'faces': [[0, 1, 2, 3]], 'matrix': rdla.IDENTITY}],
            'environments': [environment], 'render_settings': {'sampling_mode': 0}}


def written(value, generation):
    began = time.perf_counter()
    text = rdla.scene_text(value, 480, 270, 2, 0.0)
    path = folder / ('%d.full.rdla' % generation)
    path.write_text(text, encoding='utf-8')
    return text, path, time.perf_counter() - began


def main():
    runtime, hdri = native.find_runtime(Path(sys.argv[1])), Path(sys.argv[2])
    # The plugin's own steps look MoonRay's tools up in the runtime the preview uses.
    import os
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob('*'):
        if old.is_file():
            old.unlink()
    text, path, prepared = written(scene(hdri), 1)
    print('first scene: prepared in %.2f s (the HDRI made into a .tx the first time)' % prepared, flush=True)
    env = native.environment(runtime)
    env['MOONRAY_MODO_SESSION'] = str(folder)
    env['MOONRAY_MODO_GENERATION'] = '1'
    process = subprocess.Popen([str(runtime / 'moonray.exe')] + native.arguments(path, folder / 'main.exr', 0, 'vectorized'), cwd=folder, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    messages = queue.Queue()

    def reader():
        with (folder / 'session.log').open('wb') as log:
            for line in iter(process.stdout.readline, b''):
                log.write(line)
                log.flush()
                messages.put(line.decode('utf-8', errors='replace').strip())
        messages.put('EXIT')
    threading.Thread(target=reader, daemon=True).start()

    def first_picture(generation, began):
        while True:
            line = messages.get(timeout=300)
            if line.startswith('@@MODO_SESSION FRAME') and line.endswith(' %d' % generation):
                return time.perf_counter() - began
            if line == 'EXIT':
                raise RuntimeError('MoonRay ended; see ' + str(folder / 'session.log'))

    def wait_done(generation):
        while True:
            line = messages.get(timeout=600)
            if line == '@@MODO_SESSION DONE %d' % generation:
                return
            if line == 'EXIT':
                raise RuntimeError('MoonRay ended; see ' + str(folder / 'session.log'))

    try:
        began = time.perf_counter()
        print('first scene: first picture after %.2f s' % first_picture(1, began), flush=True)
        wait_done(1)
        previous = text
        for generation, (label, value) in enumerate((('turned 90 degrees by its locator', scene(hdri, locator=90)),
                                                     ('turned 45 more by its locator', scene(hdri, locator=135)),
                                                     ('turned by its texture UV rotation', scene(hdri, uv_rotation=30)),
                                                     ('UV rotation changed again', scene(hdri, uv_rotation=60)),
                                                     ('layered, turned by its locator', scene(hdri, locator=90, layered=True)),
                                                     ('layered, turned again', scene(hdri, locator=135, layered=True))), start=2):
            began = time.perf_counter()
            current, full, prepared = written(value, generation)
            delta = difference(previous, current)
            kind = 'delta' if delta is not None else 'full'
            source = full
            if delta is not None:
                source = folder / ('%d.delta.rdla' % generation)
                source.write_text(delta, encoding='utf-8')
            command = folder / 'command.tmp'
            command.write_text('%d\n%s\n%s\n%s\n' % (generation, kind, source.as_posix(), full.as_posix()), encoding='utf-8')
            command.replace(folder / 'command.txt')
            seen = first_picture(generation, began)
            print('%-34s plugin %.2f s, sent as a %s (%d bytes), first picture after %.2f s in all' % (label, prepared, kind, len(delta or current), seen), flush=True)
            wait_done(generation)
            previous = current
        command = folder / 'command.tmp'
        command.write_text('99\nquit\n-\n-\n', encoding='utf-8')
        command.replace(folder / 'command.txt')
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()


if __name__ == '__main__':
    main()
