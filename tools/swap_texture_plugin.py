"""Put the texture plugin just built (ModoTextureMap.so and its proxy from build/native-renderer-avx/bin) into a
runtime folder, keeping what it replaces under backups/, and bring the folder's records up to date: the hashes in
build-manifest.json, and in modo-session.json that this plugin reads a tiled bump image finely ("bump_step"), which
the kit asks of no runtime that does not say so.

swap_texture_plugin.py <runtime folder> [...]"""
import hashlib
import json
import pathlib
import shutil
import sys
import time

root = pathlib.Path(__file__).resolve().parents[1]
built = root / 'build/native-renderer-avx/bin'
NAMES = ('ModoTextureMap.so', 'ModoTextureMap.so.proxy')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for target in (pathlib.Path(argument).resolve() for argument in sys.argv[1:]):
        if not (target / 'ModoTextureMap.so').is_file():
            raise SystemExit('Not a runtime: %s' % target)
        backup = root / 'backups' / ('texture-plugin-before-' + stamp) / (target.parent.name + '-' + target.name)
        backup.mkdir(parents=True)
        for name in NAMES + ('modo-session.json', 'build-manifest.json'):
            if (target / name).is_file():
                shutil.copy2(target / name, backup / name)
        for name in NAMES:
            if digest(built / name) != digest(target / name):
                shutil.copy2(built / name, target / name)
        session = target / 'modo-session.json'
        if session.is_file():
            value = json.loads(session.read_text(encoding='utf-8'))
            value['bump_step'] = True
            session.write_text(json.dumps(value, indent=2), encoding='utf-8')
        manifest = target / 'build-manifest.json'
        if manifest.is_file():
            value = json.loads(manifest.read_text(encoding='utf-8'))
            for entry in value.values():
                if isinstance(entry, dict) and entry.get('source') in NAMES and 'sha256' in entry:
                    entry['sha256'] = digest(target / entry['source'])
            manifest.write_text(json.dumps(value, indent=2), encoding='utf-8')
        print('Texture plugin put into', target, '; what it replaced is in', backup)


if __name__ == '__main__':
    main()
