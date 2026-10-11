"""Package MoonRay's example scenes as the content that goes with a release.

Usage: package_content.py <version> [<moonray-runtime>]
Reads downloads/moonray-example-scenes/scenes (the scenes curated by Benedikt Bitterli that MoonRay publishes, each
with its own LICENSE.txt, all CC0 or CC-BY) and writes dist/release-<version>/MoonRayForModo-<version>-content.zip.
Like the kit and the runtime, it unpacks to a MoonRayForModo folder to be merged with theirs: the scenes go into the
kit's own assets/library, where the asset library looks without being told. Each scene is given a small picture of
itself, made from the render that comes with it, for the asset library to show; the reference render itself is left
out, being a tenth of the size for nothing the plugin uses.
"""
import pathlib
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
SCENES = ROOT / 'downloads/moonray-example-scenes/scenes'
FOLDER = 'MoonRayForModo/assets/library/MoonRay scenes'
README = '''MoonRay Content for MoonRay for Modo %s

Example scenes for MoonRay, curated by Benedikt Bitterli and published with MoonRay
(https://docs.openmoonray.org/getting-started/test-scenes/). Each scene's folder holds its own LICENSE.txt, which
names its author and its terms: every one is CC0 or CC-BY. Keep each LICENSE.txt with its scene.

They are part of the kit: this ZIP's MoonRayForModo folder is merged with the kit's, as the runtime's is. Open
MoonRay > Asset Library in Modo: the scenes are listed under Example scenes. Double-click one to open it in the
import dialog.

Each scene is two files that belong together, scene.rdlb and scene.rdla, and a folder of textures.
'''


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    version = sys.argv[1]
    from moonray_modo import native
    runtime = native.find_runtime(sys.argv[2] if len(sys.argv) > 2 else str(ROOT / 'runtime/steady-0350-pool'))
    scenes = sorted(path for path in SCENES.iterdir() if path.is_dir() and (path / 'scene.rdla').is_file())
    if not scenes:
        raise SystemExit('No scenes in %s' % SCENES)
    target = ROOT / 'dist' / ('release-' + version) / ('MoonRayForModo-%s-content.zip' % version)
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_suffix('.tmp')
    total = 0
    with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(FOLDER + '/README.txt', README % version)
        for scene in scenes:
            if not (scene / 'LICENSE.txt').is_file():
                raise SystemExit('%s has no LICENSE.txt and is not packaged without one.' % scene.name)
            picture = scene / 'scene.png'
            render = scene / 'scene.exr'
            if render.is_file() and (not picture.is_file() or picture.stat().st_mtime < render.stat().st_mtime):
                # The scene as MoonRay rendered it, small, for the asset library to show.
                done = subprocess.run([str(runtime / 'oiiotool.exe'), str(render), '--ch', 'R,G,B', '--resize', '512x0', '--colorconvert', 'linear', 'sRGB', '-o', str(picture)],
                                      env=native.environment(runtime), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                if done.returncode:
                    print('No picture for %s: %s' % (scene.name, done.stdout.decode(errors='replace')[-200:]))
            for path in sorted(scene.rglob('*')):
                if path.is_file() and path != render:
                    archive.write(str(path), '%s/%s/%s' % (FOLDER, scene.name, path.relative_to(scene).as_posix()))
                    total += path.stat().st_size
            print('%-24s packed' % scene.name, flush=True)
    if target.exists():
        target.unlink()
    staged.rename(target)
    print('%s: %d scenes, %.0f MB of files, %.0f MB packed' % (target, len(scenes), total / 1e6, target.stat().st_size / 1e6))


if __name__ == '__main__':
    main()
