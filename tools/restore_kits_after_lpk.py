"""Undo an .lpk that unpacked into the Kits folder itself, whose cleanup (stale_files) then took Kits for the kit's own folder
and moved every other kit's files into Kits/_replaced/<time>/.

Without --apply it changes nothing and says what it would do. With it, Modo closed:
1. The package's own files in Kits (those installed.txt names, and Python's caches beside them) go to a folder in the user's
   home, MoonRayForModo-lpk-unpacked-<time>.
2. Everything in Kits/_replaced/<time>/ goes back to where it was. A file already there is left in _replaced and named.
Nothing is deleted. A folder is removed only if it is empty, and only one the package's files or _replaced were in.

restore_kits_after_lpk.py [--apply] [--kits <folder>]"""
import argparse
import collections
import os
import shutil
import subprocess
import time
from pathlib import Path

LIST = 'installed.txt'
DONE = 'installed.tidied'
ASIDE = '_replaced'


def package_files(kits):
    """The package's files directly in Kits, as paths relative to it: what its list names, and Python's caches in those folders."""
    lines = (kits / LIST).read_text(encoding='utf-8').splitlines() if (kits / LIST).is_file() else []
    names = [line.strip().replace('\\', '/') for line in lines[1:] if line.strip()]
    found = {name for name in names if (kits / name).is_file()}
    if (kits / LIST).is_file():
        found.add(LIST)
    if (kits / DONE).is_file():
        found.add(DONE)
    folders = {name.rsplit('/', 1)[0] for name in names if '/' in name}
    for folder in sorted(folders):
        caches = kits / folder / '__pycache__'
        if caches.is_dir():
            found.update((Path(folder) / '__pycache__' / f.name).as_posix() for f in caches.iterdir() if f.is_file())
    return sorted(found)


def moved_files(kits):
    """(the file in _replaced, where it was) for everything the cleanup moved, the oldest first."""
    result = []
    aside = kits / ASIDE
    if aside.is_dir():
        for stamp in sorted(p for p in aside.iterdir() if p.is_dir()):
            for path in sorted(p for p in stamp.rglob('*') if p.is_file()):
                result.append((path, path.relative_to(stamp).as_posix()))
    return result


def counts(names):
    tally = collections.Counter(name.split('/', 1)[0] if '/' in name else '(in Kits itself)' for name in names)
    return ', '.join('%s %d' % item for item in sorted(tally.items()))


def remove_empty(start, stop):
    """Empty folders from start up to, not including, stop."""
    here = start
    while here != stop and stop in here.parents:
        try:
            here.rmdir()
        except OSError:
            return
        here = here.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--kits', default=str(Path(os.environ.get('APPDATA', '')) / 'Luxology/Kits'))
    args = parser.parse_args()
    kits = Path(args.kits).resolve()
    if not kits.is_dir():
        raise SystemExit('No Kits folder at %s' % kits)
    package, moved = package_files(kits), moved_files(kits)
    print('Kits folder: %s' % kits)
    print('Package files in Kits itself, to set aside: %d' % len(package))
    print('Files in _replaced, to put back: %d' % len(moved))
    if moved:
        print('  by folder: ' + counts([where for _, where in moved]))
    if not (kits / LIST).is_file() and not moved:
        print('Nothing to do: no package in Kits and nothing in _replaced.')
        return
    if not args.apply:
        print('Nothing changed. Close Modo and run again with --apply.')
        return
    tasks = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq modo.exe', '/NH'], capture_output=True, text=True).stdout
    if 'modo.exe' in tasks.lower():
        raise SystemExit('Close Modo first: nothing was changed.')
    # Outside Kits: Modo would load an index.cfg in there as a second kit of the same name.
    kept = Path.home() / ('MoonRayForModo-lpk-unpacked-' + time.strftime('%Y%m%d-%H%M%S'))
    failed = []
    for name in package:
        source, target = kits / name, kept / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            remove_empty(source.parent, kits)
        except OSError as error:
            failed.append('%s: %s' % (name, error))
    clashes = []
    back = 0
    for source, where in moved:
        target = kits / where
        if target.exists():
            clashes.append(where)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
            remove_empty(source.parent, kits)
            back += 1
        except OSError as error:
            failed.append('%s: %s' % (where, error))
    print('Put back: %d. Package files are now in %s.' % (back, kept))
    if clashes:
        print('Already there, so left in _replaced (%d):' % len(clashes))
        for where in clashes[:40]:
            print('  ' + where)
    if failed:
        print('Could not move (%d):' % len(failed))
        for line in failed[:40]:
            print('  ' + line)
    if not clashes and not failed:
        print('All done, with nothing left over.')


if __name__ == '__main__':
    main()
