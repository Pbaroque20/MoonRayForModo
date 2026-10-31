"""What an older version of the kit left behind, moved aside after a newer one is installed from its package (.lpk).

Modo installs a package by adding and overwriting files: a module or runtime file an older version had and the new one
does not would stay, and could still be loaded. The package names those files (superseded.txt in the kit's folder: what
earlier releases installed and this one does not, tools/package_lpk.py); the first time the kit starts after, each that is
there is moved into _replaced/<time>/, under its own path, never deleted. Nothing else is looked at, so a file the package
does not name stays where it is, whoever put it there.

Only in the kit's own folder: a package once unpacked into Kits itself, and a walk from there took every other kit's files.
Done once for each version installed; nothing happens to a kit not installed from a package (no superseded.txt).
"""
import re
import time
from pathlib import Path

KIT = 'MoonRayForModo'
LIST = 'installed.txt'
SUPERSEDED = 'superseded.txt'
DONE = 'installed.tidied'
ASIDE = '_replaced'


def kit_root():
    return Path(__file__).resolve().parents[2]


def is_kit_folder(root):
    """Whether this folder is the kit's own: named for it, with the kit's own index.cfg."""
    if root.name != KIT:
        return False
    try:
        found = re.search(r'kit="([^"]+)"', (root / 'index.cfg').read_text(encoding='utf-8', errors='replace'))
    except OSError:
        return False
    return bool(found) and found.group(1) == KIT


def inside(name):
    """A plain path within the folder: nothing that climbs out of it, or names a drive."""
    parts = name.split('/')
    return bool(name) and '..' not in parts and not name.startswith('/') and ':' not in name


def tidy(root=None):
    """Move aside what the package says earlier releases left; returns the paths moved (relative to the kit's folder)."""
    root = Path(root) if root else kit_root()
    if not is_kit_folder(root):
        return []
    try:
        version = (root / LIST).read_text(encoding='utf-8').splitlines()[0].strip()
        names = (root / SUPERSEDED).read_text(encoding='utf-8').splitlines()
    except (OSError, IndexError):
        return []
    try:
        if (root / DONE).read_text(encoding='utf-8').strip() == version:
            return []
    except OSError:
        pass
    aside = root / ASIDE / time.strftime('%Y%m%d-%H%M%S')
    moved = []
    for name in names:
        name = name.strip().replace('\\', '/')
        if not inside(name) or not (root / name).is_file():
            continue
        target = aside / name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            (root / name).replace(target)
            moved.append(name)
        except OSError:
            pass  # in use (a library Modo has loaded): left, and tried again at the next version
    try:
        (root / DONE).write_text(version, encoding='utf-8')
    except OSError:
        pass
    return moved
