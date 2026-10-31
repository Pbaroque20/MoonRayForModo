"""Glitter turned on and off again in one live session on a mesh read without rest positions: does the material go pink, and does the
pink stay? In MoonRay, MoonRay XPU and XPU2, outside Modo with the built kit, on make_car_paint_scene.py's scene. Off is tried both
as the form writes it (the setting removed) and as the graph editor does (false). check_glitter_pink.py [vectorized|xpu|xpu2 ...]
prints the colour on the car at each step; (1, 0, 1) is MoonRay's colour for a failed material."""
import copy
import os
import pickle
import struct
import sys
import time
from pathlib import Path
os.environ['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
for folder in (r'C:\Program Files\Modo16.1v9\modo', r'C:\Program Files\Modo16.1v9\modo\resrc\python3kit\extra64'):
    os.add_dll_directory(folder)
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
runtime = KIT / 'runtime'
os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
from PySide2 import QtCore
app = QtCore.QCoreApplication([])
from moonray_modo import options, persistent, rdla
from moonray_modo.preferences import Preferences

out = ROOT / 'test-results/glitter-pink'
out.mkdir(parents=True, exist_ok=True)
W, H = 320, 180
base = pickle.loads((ROOT / 'test-results/car-paint-scene/snapshot.pickle').read_bytes())
base.update(width=W, height=H, aovs=[], custom_aovs=[], preview_buffer='beauty')
base['render_settings'] = options.render_values(dict(base.get('render_settings') or {}, sampling_mode=0, pixel_samples=4))
for mesh in base['meshes']:
    mesh.pop('point_attributes', None)
PLAIN = {'metallic_color': [.22, .22, .8], 'metallic_edge_color': [.5, .5, 1.0], 'roughness': .4}
ON = dict(PLAIN, show_glitter=True)
FALSE = dict(PLAIN, show_glitter=False)


def scene_text(parameters):
    scene = dict(base)
    scene['materials'] = copy.deepcopy(base['materials'])
    found = 0
    for material in scene['materials'].values():
        for layer in [material] + list(material.get('material_stack') or []):
            if layer.get('native_shader') == 'DwaMetalMaterial':
                layer['native_parameters'] = dict(parameters)
                found += 1
    assert found
    return rdla.scene_text(scene, W, H, 4, 0, str(out / 'unused.exr'))


ROUNDS = (('as the form', (('off', PLAIN), ('on', ON), ('removed', PLAIN), ('on', ON), ('removed', PLAIN))),
          ('as the graph', (('off', PLAIN), ('on', ON), ('false', FALSE), ('on', ON), ('false', FALSE))))


def run(mode, title, steps):
    store = Preferences().store
    store.setValue('xpu2/renderer', 'xpu2' if mode == 'xpu2' else 'moonray')
    store.sync()
    session = persistent.Session()
    last, finished, failed = {}, [], []
    session.memory_image.connect(lambda p: last.__setitem__(p[1], p))
    session.ready.connect(lambda g: finished.append(g))
    session.failed.connect(lambda m: (failed.append(m[:300]), finished.append(-1)))
    for generation, (name, parameters) in enumerate(steps, 1):
        del finished[:]
        last.clear()
        session.submit(scene_text(parameters), runtime, 0, 'xpu' if mode in ('xpu', 'xpu2') else mode, generation)
        deadline = time.time() + 90
        while not finished and time.time() < deadline:
            app.processEvents()
            time.sleep(.02)
        picture = last.get('beauty')
        colour = None
        if picture:
            values = struct.unpack('<%df' % (picture[2] * picture[3] * 3), picture[4])
            # The car's side, near the middle of the picture.
            spots = [(picture[2] // 2 + dx, picture[3] // 2 + dy) for dx in range(-8, 9, 4) for dy in range(-8, 1, 4)]
            colour = [round(sum(values[3 * (y * picture[2] + x) + c] for x, y in spots) / len(spots), 3) for c in range(3)]
        print(mode, title, name, 'PINK' if colour == [1.0, 0.0, 1.0] else colour, 'finished', bool(finished), failed[-1:], flush=True)
    session.close()
    for _ in range(50):
        app.processEvents()
        time.sleep(.02)
    store.remove('xpu2/renderer')


for mode in sys.argv[1:] or ('vectorized', 'xpu', 'xpu2'):
    for title, steps in ROUNDS:
        run(mode, title, steps)
