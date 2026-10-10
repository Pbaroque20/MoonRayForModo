"""Render a small scene with MoonRay to check that an object can be told not to cast its shadow onto another.

Usage: check_shadow_receivers.py <runtime folder>
The scene is rendered as it is, and again with its ball and its cube casting no shadow onto the ground. MoonRay must
take both, and the second must be the brighter: the ground has lost two shadows."""
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'kit/MoonRayForModo/python')]
import check_moonlightipr_session as fixture  # noqa: E402
from moonray_modo import native, rdla  # noqa: E402


def main():
    runtime = native.find_runtime(Path(sys.argv[1]).resolve())
    out = Path(tempfile.mkdtemp(prefix='moonray-receivers-'))
    env = native.environment(runtime)
    base = fixture.snapshot()
    owners = [mesh.get('source_item') or str(mesh.get('identity', '')).split('|')[0] for mesh in base['meshes']]
    ground, others = owners[0], owners[1:]
    means, texts = {}, {}
    for name, objects in (('shadowed', {}), ('spared', {owner: {'shadow_receivers': [ground]} for owner in others})):
        scene = dict(base, production=dict(base.get('production', {}), objects=objects))
        picture = out / (name + '.exr')
        texts[name] = rdla.scene_text(scene, 240, 135, 3, 0.2, str(picture))
        (out / (name + '.rdla')).write_text(texts[name], encoding='utf-8')
        done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(out / (name + '.rdla')), '-out', str(picture), '-exec_mode', 'vectorized'], env=env, capture_output=True, timeout=600)
        log = (done.stdout + done.stderr).decode(errors='replace')
        if done.returncode or not picture.is_file():
            raise SystemExit('MoonRay did not render %s:\n%s' % (name, log[-1500:]))
        stats = subprocess.run([str(runtime / 'oiiotool.exe'), '--stats', str(picture)], env=env, capture_output=True, text=True).stdout
        line = next(l for l in stats.splitlines() if 'Stats Avg' in l)
        means[name] = sum(float(v) for v in line.split(':', 1)[1].split()[:3]) / 3
    sets = texts['spared'].count('ShadowReceiverSet(')
    print('receiver sets written: %d; mean brightness shadowed %.4f, spared %.4f' % (sets, means['shadowed'], means['spared']))
    if 'ShadowReceiverSet(' in texts['shadowed'] or sets != len(others):
        raise SystemExit('The receiver sets were not written as asked')
    if not means['spared'] > means['shadowed'] * 1.01:
        raise SystemExit('The ground is no brighter for losing the shadows')
    print('Shadow receiver check passed; files in', out)


if __name__ == '__main__':
    main()
