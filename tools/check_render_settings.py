"""Render a small scene with MoonRay to check the render settings and one-click outputs added from its documentation.

Usage: check_render_settings.py <runtime folder>
Renders once with every setting at the value it starts with and once with each moved off it, and checks that MoonRay
takes both and that moving them changes the scene it is given. Then renders with every one-click output ticked and
checks that the EXR holds a channel for each."""
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
from moonray_modo import native, options, rdla  # noqa: E402

NEW = ('max_volume_depth', 'max_presence_depth', 'max_hair_depth', 'max_subsurface_per_path', 'russian_roulette_threshold', 'transparency_threshold',
       'presence_threshold', 'enable_presence_shadows', 'volume_quality', 'volume_shadow_quality', 'volume_illumination_samples', 'volume_indirect_samples',
       'volume_opacity_threshold', 'volume_overlap_mode', 'sample_clamping_value', 'sample_clamping_depth', 'roughness_clamping_factor', 'texture_blur',
       'pixel_filter', 'pixel_filter_width', 'lock_frame_noise')
MOVED = {'max_volume_depth': 3, 'max_presence_depth': 8, 'max_hair_depth': 3, 'max_subsurface_per_path': 2, 'russian_roulette_threshold': .05,
         'transparency_threshold': .98, 'presence_threshold': .99, 'enable_presence_shadows': 1, 'volume_quality': .7, 'volume_shadow_quality': .6,
         'volume_illumination_samples': 2, 'volume_indirect_samples': 1, 'volume_opacity_threshold': .98, 'volume_overlap_mode': 1,
         'sample_clamping_value': 4.0, 'sample_clamping_depth': 2, 'roughness_clamping_factor': .3, 'texture_blur': .5, 'pixel_filter': 0,
         'pixel_filter_width': 2.0, 'lock_frame_noise': 1}
OUTPUTS = ('indirect_diffuse', 'indirect_glossy', 'mirror_reflection', 'subsurface', 'unshadowed_diffuse', 'albedo', 'motion_vectors')


def main():
    runtime = native.find_runtime(Path(sys.argv[1]).resolve())
    out = Path(tempfile.mkdtemp(prefix='moonray-settings-'))
    failed = []

    def check(what, passed, detail=''):
        print('%-58s %s %s' % (what, 'ok' if passed else 'FAILED', detail), flush=True)
        if not passed:
            failed.append(what)

    def render(name, scene):
        path, picture = out / (name + '.rdla'), out / (name + '.exr')
        text = rdla.scene_text(scene, 160, 90, 2, 0.5, str(picture))
        path.write_text(text, encoding='utf-8')
        done = subprocess.run([str(runtime / 'moonray.exe'), '-in', str(path), '-out', str(picture), '-exec_mode', 'vectorized'],
                              env=native.environment(runtime), capture_output=True, timeout=600)
        log = (done.stdout + done.stderr).decode(errors='replace')
        return text, done.returncode == 0 and picture.is_file(), picture, log

    check('every new setting is in the form\'s list', all(key in options.RENDER for key in NEW) and set(MOVED) == set(NEW))
    base = fixture.snapshot()
    plain, passed, _, log = render('as_they_start', base)
    check('MoonRay renders with the settings as they start', passed, log[-300:] if not passed else '')
    moved, passed, _, log = render('moved', dict(base, render_settings=dict(base.get('render_settings', {}), **MOVED)))
    check('MoonRay renders with every setting moved', passed, log[-300:] if not passed else '')
    unknown = [line for line in log.splitlines() if 'nknown' in line or 'not a valid' in line or 'rror' in line]
    check('MoonRay names no setting it does not know', not unknown, '; '.join(unknown)[:300])
    for key in NEW:
        line = next((l for l in moved.splitlines() if l.startswith('  ["%s"] = ' % key)), None)
        was = next((l for l in plain.splitlines() if l.startswith('  ["%s"] = ' % key)), None)
        check('  %s is written, and changes when moved' % key, bool(line) and bool(was) and line != was, '%s -> %s' % ((was or '').strip(), (line or '').strip()))
    _, passed, picture, log = render('outputs', dict(base, aovs=['alpha'] + list(OUTPUTS)))
    check('MoonRay renders with every one-click output ticked', passed, log[-300:] if not passed else '')
    if passed:
        info = subprocess.run([str(runtime / 'oiiotool.exe'), '--info', '-v', '-a', str(picture)], env=native.environment(runtime), capture_output=True, text=True).stdout
        for key in OUTPUTS:
            check('  the EXR holds %s' % key, key in info)
    print('files in', out)
    if failed:
        raise SystemExit('%d check(s) failed' % len(failed))


if __name__ == '__main__':
    main()
