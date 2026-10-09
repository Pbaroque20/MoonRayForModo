"""Check that MoonRay accepts every MoonRay item class the plugin can export.

Usage: check_moonray_entities.py <moonray-runtime>
Builds one scene holding an item of each class in entity_catalog.json, with references between
them where a class has any (light filters on a light, a portal's environment, a volume in a
box), renders it small through a fisheye camera item, and fails on any MoonRay error. Classes
that cannot work without a file on disk are exported alone to confirm they are at least
recognised. Run outside Modo. Output goes to build/moonlight/entities.
"""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
from moonray_modo import entities, native, rdla
import check_moonlight_session as fixture

NEEDS_FILE = ('VdbGeometry', 'VdbVolume', 'VdbLightFilter', 'CookieLightFilter', 'CookieLightFilter_v2')


def item(name, x=0.0, y=3.0, z=0.0, **parameters):
    return {'identity': 'item_' + name, 'name': name, 'class': name, 'matrix': fixture.placed(x, y, z), 'parameters': parameters}


def render(runtime, folder, name, scene):
    output = folder / (name + '.exr')
    source = folder / (name + '.rdla')
    source.write_text(rdla.scene_text(scene, 160, 90, 1, 0.0, str(output)), encoding='utf-8')
    done = subprocess.run([str(runtime / 'moonray.exe')] + native.arguments(source, output, 0, 'auto'), env=native.environment(runtime),
                          cwd=str(folder), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    return done.returncode, done.stdout.decode(errors='replace')


def main():
    runtime = native.find_runtime(sys.argv[1])
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    folder = fixture.BUILD / 'entities'
    folder.mkdir(parents=True, exist_ok=True)
    base = fixture.snapshot()
    base.update(lights=[], environments=[], render_settings={'sampling_mode': 0, 'max_depth': 2})
    filters = ['IntensityLightFilter', 'DecayLightFilter', 'RodLightFilter', 'BarnDoorLightFilter', 'ColorRampLightFilter']
    together = [item(name) for name in entities.classes() if name not in NEEDS_FILE and name not in ('CombineLightFilter', 'RectLight', 'PortalLight',
                                                                                              'BoxGeometry', 'FisheyeCamera')]
    together += [item('CombineLightFilter', light_filters=filters[:2]),
                 item('RectLight', 2, 5, 3, intensity=30.0, light_filters=filters + ['CombineLightFilter']),
                 item('PortalLight', light='EnvLight'),
                 item('BoxGeometry', -4, 1, 2, size=[1.0, 2.0, 1.0], modo_material='red', modo_volume='BaseVolume'),
                 dict(item('FisheyeCamera', modo_render_camera=True), matrix=base['camera']['matrix'])]
    code, log = render(runtime, folder, 'all', dict(base, entities=together))
    problems = [line for line in log.splitlines() if 'Error' in line or 'rror:' in line]
    print('%d classes in one scene: exit %d, %d error lines' % (len(together), code, len(problems)))
    for line in problems[:20]:
        print('  ', line[:240])
    failed = bool(code or problems)
    for name in NEEDS_FILE:
        code, log = render(runtime, folder, name, dict(base, entities=[item(name)]))
        unknown = [line for line in log.splitlines() if 'RDLA Error' in line or 'unknown' in line.lower() and name in line]
        print('%-22s alone, without its file: exit %d%s' % (name, code, '; ' + unknown[0][:200] if unknown else ''))
        failed = failed or bool(unknown)
    if failed:
        raise SystemExit('MoonRay did not accept every MoonRay item')
    print('MoonRay item check passed')


if __name__ == '__main__':
    main()
