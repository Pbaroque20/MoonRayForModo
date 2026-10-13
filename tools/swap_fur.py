"""Put what grows Modo's fur without a limit into a runtime folder: modo_fur_grow.exe (build/native-avx/bin, from
tools/build_fur_grower.py), which grows the fibres into a file, and ModoFurGeometry (build/native-renderer-avx/bin),
with which MoonRay reads that file. What is replaced is kept under backups/, and the hashes in build-manifest.json are
brought up to date. The kit uses the two only where a runtime has both.

swap_fur.py <runtime folder> [...]"""
import hashlib
import json
import pathlib
import shutil
import sys
import time

root = pathlib.Path(__file__).resolve().parents[1]
SOURCES = {'modo_fur_grow.exe': root / 'build/native-avx/bin/modo_fur_grow.exe',
           'ModoFurGeometry.dll': root / 'build/native-renderer-avx/bin/ModoFurGeometry.dll',
           'ModoFurGeometry.so.proxy': root / 'build/native-renderer-avx/bin/ModoFurGeometry.so.proxy'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    missing = [name for name, source in SOURCES.items() if not source.is_file()]
    if missing:
        raise SystemExit('Not built yet: ' + ', '.join(missing))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for target in (pathlib.Path(argument).resolve() for argument in sys.argv[1:]):
        if not (target / 'moonray.exe').is_file():
            raise SystemExit('Not a runtime: %s' % target)
        backup = root / 'backups' / ('fur-before-' + stamp) / (target.parent.name + '-' + target.name)
        backup.mkdir(parents=True)
        for name in tuple(SOURCES) + ('build-manifest.json',):
            if (target / name).is_file():
                shutil.copy2(target / name, backup / name)
        for name, source in SOURCES.items():
            shutil.copy2(source, target / name)
        manifest = target / 'build-manifest.json'
        if manifest.is_file():
            value = json.loads(manifest.read_text(encoding='utf-8'))
            for name in SOURCES:
                value[name.lower()] = {'sha256': digest(target / name), 'source': name}
            manifest.write_text(json.dumps(value, indent=2), encoding='utf-8')
        print('Fur grower and reader put into', target, '; what they replaced is in', backup)


if __name__ == '__main__':
    main()
