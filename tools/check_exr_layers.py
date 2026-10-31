"""Render EXR's layers outside Modo with the built kit: one file with standard names, and as a multi-part file, in each case what the
file holds, that every output has a picture in it, and that the compositor finds alpha and depth. On make_car_paint_scene.py's scene.
Writes test-results/layered-exr/."""
import os
import pickle
import shutil
import subprocess
import sys
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
from moonray_modo import composite_output, compositor, native, options, rdla, recovery

out = ROOT / 'test-results/layered-exr'
out.mkdir(parents=True, exist_ok=True)
env = native.environment(runtime)
W, H = 320, 180
scene = pickle.loads((ROOT / 'test-results/car-paint-scene/snapshot.pickle').read_bytes())
scene.update(width=W, height=H, aovs=['alpha', 'albedo', 'diffuse_direct', 'glossy_direct', 'depth', 'normal', 'position', 'motion_vectors', 'uv'],
             custom_aovs=[], preview_buffer='beauty')
scene['render_settings'] = options.render_values(dict(scene.get('render_settings') or {}, sampling_mode=0, pixel_samples=2))


def tool(*arguments):
    return subprocess.run([str(runtime / 'oiiotool.exe')] + [str(a) for a in arguments], env=env, capture_output=True, text=True)


for name, exr_settings in (('layers', {}), ('parts', {'multipart': True})):
    held = dict(scene, exr=dict({'compression': 1, 'dwa_level': 85.0}, **exr_settings))
    exr = out / (name + '.exr')
    if exr.exists():
        exr.unlink()
    path = out / (name + '.rdla')
    path.write_text(rdla.scene_text(held, W, H, 2, 0, str(exr)), encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    parts = composite_output.channel_parts(runtime, exr)
    print(name, 'rc', done.returncode, 'parts', len(parts))
    for index, names in enumerate(parts):
        stats = tool('--no-autopremult', exr, '--subimage', index, '--stats').stdout
        peak = [line.strip()[:60] for line in stats.splitlines() if 'Max' in line][:1]
        print('  part', index, names[:3], 'max', peak)
    for key in ('beauty', 'alpha', 'depth', 'normal', 'diffuse_direct'):
        print('  finds', key, 'in part', composite_output.part_of(key, parts))
    print('  first part has R,G,B,A:', all(c in parts[0] for c in 'RGBA'))
    # The compositor taking each of these for its picture: alpha, and what a multi-part file keeps outside its first part.
    for key in ('alpha', 'depth', 'diffuse_direct'):
        graph = compositor.new()
        graph['nodes']['beauty']['parameters']['buffer'] = key
        graph['nodes']['grade'] = {'type': 'grade', 'parameters': {'gain': 1.0001}, 'inputs': {'image': 'beauty'}, 'position': [100, 0]}
        graph['nodes']['out']['inputs']['image'] = 'grade'
        try:
            made = composite_output.write(runtime, graph, exr)
            kept = out / ('%s-%s-composite.exr' % (name, key))
            kept.write_bytes(Path(made).read_bytes())
            if name == 'parts':
                print('  composite of', key, 'against the single file:', tool('--diff', '--fail', '0.00001', out / ('layers-%s-composite.exr' % key), kept).stdout.strip().splitlines()[-1:])
        except Exception as exc:
            print('  composite of', key, 'FAILED', str(exc)[:200])
# Checkpoints with parts: the render, and the same render taken up again.
exr = out / 'parts-resume.exr'
for leftover in out.glob('parts-resume*'):
    shutil.rmtree(leftover) if leftover.is_dir() else leftover.unlink()
for run, samples in (('first', 2), ('resumed', 2)):
    held = dict(scene, exr={'compression': 1, 'dwa_level': 85.0, 'multipart': True}, recovery={'enabled': True, 'resume': True, 'minutes': 1.0})
    held['render_settings'] = options.render_values(dict(scene['render_settings'], pixel_samples=samples))
    try:
        held['_recovery'] = recovery.prepare(held, exr, W, H, samples, 0, runtime)
    except Exception as exc:
        print('checkpoint', run, 'prepare refused:', str(exc)[:200])
        continue
    path = out / 'parts-resume.rdla'
    path.write_text(rdla.scene_text(held, W, H, samples, 0, str(exr)), encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(path, exr, 0, 'vectorized'), env=env, cwd=str(out), capture_output=True, text=True)
    said = [line.split('|', 1)[-1].strip()[:110] for line in done.stdout.splitlines() if any(word in line.lower() for word in ('resum', 'fatal', 'could not')) and ' = ' not in line][:4]
    print('checkpoint', run, 'rc', done.returncode, 'resume', held['_recovery']['resume'], 'file', Path(held['_recovery']['file']).name, 'parts', [p[:1] for p in composite_output.channel_parts(runtime, exr)], said)
