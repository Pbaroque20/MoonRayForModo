"""Put MoonRay's display filters and its switch displacement, as built (build/native-renderer-avx/bin), into a runtime
folder, keeping whatever they replace under backups/, and record them in the folder's build-manifest.json. The kit
finds which display filters a runtime has by their plugins (native.display_filter_classes), so nothing else changes.
ImageDisplayFilter, which every runtime already has, is left as it is.

swap_display_filters.py <runtime folder> [...]"""
import hashlib
import json
import pathlib
import shutil
import sys
import time

root = pathlib.Path(__file__).resolve().parents[1]
built = root / 'build/native-renderer-avx/bin'
PLUGINS = sorted(p.name for p in built.glob('*DisplayFilter.so') if p.name != 'ImageDisplayFilter.so') + ['SwitchDisplacement.so']
NAMES = [name for plugin in PLUGINS for name in (plugin, plugin + '.proxy')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if len(PLUGINS) != 18 or not all((built / name).is_file() for name in NAMES):
        raise SystemExit('Build moonshine_displayfilter_library first: %d plugins found' % len(PLUGINS))
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for target in (pathlib.Path(argument).resolve() for argument in sys.argv[1:]):
        if not (target / 'moonray.exe').is_file():
            raise SystemExit('Not a runtime: %s' % target)
        backup = root / 'backups' / ('display-filters-before-' + stamp) / (target.parent.name + '-' + target.name)
        backup.mkdir(parents=True)
        for name in NAMES + ['build-manifest.json']:
            if (target / name).is_file():
                shutil.copy2(target / name, backup / name)
        manifest_path = target / 'build-manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.is_file() else None
        for name in NAMES:
            shutil.copy2(built / name, target / name)
            if manifest is not None:
                manifest[name.lower()] = {'sha256': digest(target / name), 'source': name}
        if manifest is not None:
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
        print('%s: %d files in; backup %s' % (target, len(NAMES), backup))


if __name__ == '__main__':
    main()
