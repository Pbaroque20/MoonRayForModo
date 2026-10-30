"""What an older version of the kit left behind, moved aside after a newer one is installed from its package (.lpk).

Modo installs a package by adding and overwriting files: a module or runtime file an older version had and the new one
does not would stay, and could still be loaded. The package lists its own files (installed.txt in the kit's folder,
tools/package_lpk.py); the first time the kit starts after, every file of the kit's folder the list does not name is
moved into _replaced/<time>/, under its own path, never deleted. The user's own files stay where they are: the chosen
runtime (runtime.json), Modo's layout (layout.cfg), a development install's note, and Python's compiled caches.
Done once for each version installed; nothing happens to a kit not installed from a package (no installed.txt).
"""
import os
import time
from pathlib import Path

LIST = 'installed.txt'
DONE = 'installed.tidied'
ASIDE = '_replaced'
# Kept wherever they are: the user's, Modo's, or made by the kit as it runs.
KEPT_NAMES = {LIST, DONE, 'runtime.json', 'layout.cfg', 'development-install.json'}
KEPT_FOLDERS = {ASIDE, '__pycache__', 'backups'}


def kit_root():
    return Path(__file__).resolve().parents[2]


def tidy(root=None):
    """Move aside what the installed package does not list; returns the paths moved (relative to the kit's folder)."""
    root = Path(root) if root else kit_root()
    try:
        listed = (root / LIST).read_text(encoding='utf-8').splitlines()
    except OSError:
        return []
    if not listed:
        return []
    version, names = listed[0].strip(), {line.strip().replace('\\', '/') for line in listed[1:] if line.strip()}
    try:
        if (root / DONE).read_text(encoding='utf-8').strip() == version:
            return []
    except OSError:
        pass
    aside = root / ASIDE / time.strftime('%Y%m%d-%H%M%S')
    moved = []
    for folder, folders, files in os.walk(root):
        here = Path(folder)
        folders[:] = [f for f in folders if f not in KEPT_FOLDERS]
        for name in files:
            if name in KEPT_NAMES or name.endswith('.pyc'):
                continue
            relative = (here / name).relative_to(root).as_posix()
            if relative in names:
                continue
            target = aside / relative
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(here / name, target)
                moved.append(relative)
            except OSError:
                pass  # in use (a library Modo has loaded): left, and tried again at the next version
    try:
        (root / DONE).write_text(version, encoding='utf-8')
    except OSError:
        pass
    return moved
