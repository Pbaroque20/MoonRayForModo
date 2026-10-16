"""Put the renderer just built (moonray.exe, librendering_rndr.dll and libscene_rdl2.dll from build/native-renderer-avx)
into a runtime
folder, keeping what it replaces under backups/, and bring the folder's records of their hashes up to date.

swap_renderer.py [--files a,b,...] <runtime folder> [...]

--files names the built files to put in, in place of those three (the toon terminator, for one, rebuilt the shading,
geometry and application libraries and left libscene_rdl2.dll alone)."""
import hashlib
import json
import pathlib
import shutil
import sys
import time

root = pathlib.Path(__file__).resolve().parents[1]
built = root / 'build/native-renderer-avx/bin'
NAMES = ('moonray.exe', 'librendering_rndr.dll', 'libscene_rdl2.dll')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    global NAMES
    arguments = sys.argv[1:]
    if arguments[:1] == ['--files']:
        NAMES = tuple(arguments[1].split(','))
        arguments = arguments[2:]
    stamp = time.strftime('%Y%m%d-%H%M%S')
    executable = (built / 'moonray.exe').read_bytes()
    for target in (pathlib.Path(argument).resolve() for argument in arguments):
        if not (target / 'moonray.exe').is_file():
            raise SystemExit('Not a runtime: %s' % target)
        backup = root / 'backups' / ('renderer-before-' + stamp) / (target.parent.name + '-' + target.name)
        backup.mkdir(parents=True)
        records = [name for name in ('modo-session.json', 'modo-crypto-categories.json', 'build-manifest.json') if (target / name).is_file()]
        for name in NAMES + tuple(records):
            shutil.copy2(target / name, backup / name)
        for name in NAMES:
            shutil.copy2(built / name, target / name)
        session = json.loads((target / 'modo-session.json').read_text(encoding='utf-8'))
        session.update(executable_sha256=digest(target / 'moonray.exe'), saves=b'Modo session: saving the picture as it renders' in executable, drains=b'drain.txt' in executable, important=b'important.txt' in executable, holds=b'Modo held snapshot' in executable,
                       pixel_filters=b'blackman-harris' in (target / 'libscene_rdl2.dll').read_bytes())
        (target / 'modo-session.json').write_text(json.dumps(session, indent=2), encoding='utf-8')
        crypto = target / 'modo-crypto-categories.json'
        if crypto.is_file():
            value = json.loads(crypto.read_text(encoding='utf-8'))
            for name in NAMES:
                if name in value.get('sha256', {}):
                    value['sha256'][name] = digest(target / name)
            crypto.write_text(json.dumps(value, indent=2), encoding='utf-8')
        manifest = target / 'build-manifest.json'
        if manifest.is_file():
            value = json.loads(manifest.read_text(encoding='utf-8'))
            for name in NAMES + ('modo-session.json', 'modo-crypto-categories.json'):
                if name in value and (target / name).is_file():
                    value[name]['sha256'] = digest(target / name)
            manifest.write_text(json.dumps(value, indent=2), encoding='utf-8')
        print('Renderer put into', target, '; what it replaced is in', backup)


if __name__ == '__main__':
    main()
