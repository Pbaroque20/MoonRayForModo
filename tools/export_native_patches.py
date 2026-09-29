"""Preserve the actual source-port edits, pinned revisions, and dependency inventory."""
from pathlib import Path
import difflib
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[1]
repositories = {
    'cmake_modules': 'upstream/openmoonray/cmake_modules',
    'scene_rdl2': 'upstream/openmoonray/moonray/scene_rdl2',
    'moonray': 'upstream/openmoonray/moonray/moonray',
    'mcrt_denoise': 'upstream/openmoonray/moonray/mcrt_denoise',
    'moonshine': 'upstream/openmoonray/moonray/moonshine',
    'log4cplus': 'upstream/log4cplus',
    'random123': 'upstream/random123',
}
patchdir = root / 'patches/native-windows'
patchdir.mkdir(parents=True, exist_ok=True)
manifest = {'repositories': {}, 'ispc_runtime': {'tag': 'v1.31.0', 'files': {}}}
manifest['openmoonray_commit'] = subprocess.check_output([
    'git', '-C', str(root / 'upstream/openmoonray'), 'rev-parse', 'HEAD']).decode().strip()
manifest['toolchain_archive'] = {
    'url': 'https://github.com/msys2/msys2-installer/releases/download/nightly-x86_64/msys2-base-x86_64-latest.sfx.exe',
    'sha256': hashlib.sha256((root / 'downloads/msys2-base-x86_64.sfx.exe').read_bytes()).hexdigest(),
    'note': 'Nightly URL is mutable; this checksum identifies the local downloaded archive.'}
for name, relative in repositories.items():
    repo = root / relative
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    patch = git('diff', '--binary', '--no-ext-diff', 'HEAD').decode('utf-8')
    untracked = git('ls-files', '--others', '--exclude-standard').decode('utf-8').splitlines()
    for path in untracked:
        content = (repo / path).read_text(encoding='utf-8')
        patch += 'diff --git a/{0} b/{0}\nnew file mode 100644\n'.format(path)
        patch += ''.join(difflib.unified_diff([], content.splitlines(True), fromfile='/dev/null', tofile='b/' + path))
    entry = {'path': relative, 'commit': git('rev-parse', 'HEAD').decode().strip(),
             'origin': git('remote', 'get-url', 'origin').decode().strip()}
    if patch:
        destination = patchdir / (name + '.patch')
        destination.write_bytes(patch.encode('utf-8'))
        entry['patch'] = str(destination.relative_to(root)).replace('\\', '/')
        entry['patch_sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
        subprocess.run(['git', '-C', str(repo), 'apply', '--reverse', '--check', str(destination)], check=True)
    manifest['repositories'][name] = entry
for path in (root / 'upstream/ispc-runtime').rglob('*'):
    if path.is_file():
        relative = str(path.relative_to(root / 'upstream/ispc-runtime')).replace('\\', '/')
        manifest['ispc_runtime']['files'][relative] = hashlib.sha256(path.read_bytes()).hexdigest()
(patchdir / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
packages = subprocess.check_output([str(root / 'toolchain/msys64/usr/bin/pacman.exe'), '-Q']).decode()
(patchdir / 'installed-packages.txt').write_text(packages, encoding='utf-8')
print('Saved source-port patches, pinned commits, source checksums, and installed package versions.')
