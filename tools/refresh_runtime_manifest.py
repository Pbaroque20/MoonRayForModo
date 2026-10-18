"""Bring a runtime folder's build-manifest.json up to date with the files it holds, for packaging a release from it.

The packer checks every file the manifest names against its checksum, and refuses a runtime where one differs: after
files have been swapped in (tools/swap_*.py) or added by an install (rdl2_convert.exe and the plugin's helpers), the
manifest is behind. Each entry whose file differs is given the file's checksum, and each program or library in the
runtime's top folder that the manifest does not name is added. What changed is printed; nothing is written with
--dry-run. Usage: refresh_runtime_manifest.py <runtime> [--dry-run]"""
import argparse
import hashlib
import json
from pathlib import Path

ADDED = ('.exe', '.dll', '.so', '.proxy')


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    path = args.runtime / 'build-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    missing = [name for name in manifest if not (args.runtime / name).is_file()]
    if missing:
        raise SystemExit('The manifest names files the runtime does not hold: ' + ', '.join(missing))
    changed = []
    for name, entry in manifest.items():
        held = digest(args.runtime / name)
        if held != entry['sha256']:
            entry['sha256'] = held
            changed.append(name)
    named = {name.lower() for name in manifest}
    added = []
    for file in sorted(args.runtime.iterdir()):
        if file.is_file() and file.suffix.lower() in ADDED and file.name.lower() not in named:
            manifest[file.name.lower()] = {'sha256': digest(file), 'source': file.name}
            added.append(file.name)
    print('Checksums brought up to date: %s' % (', '.join(changed) or 'none'))
    print('Added: %s' % (', '.join(added) or 'none'))
    if not args.dry_run and (changed or added):
        path.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
