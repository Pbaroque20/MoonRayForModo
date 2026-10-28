"""The kit's caches under the Cache folder (cache_folder.root): each Path(os.environ.get('LOCALAPPDATA', ...)) /
'MoonRayForModo/<what>' in the kit's modules made cache_root() / '<what>', with the import it needs. Run on a kit's
python/moonray_modo folder: by hand on the main repo's, and by build_xpu2_kit.py on the private kit's."""
import re
import sys
from pathlib import Path

SITE = re.compile(r"Path\(\s*os\.environ\.get\(\s*'LOCALAPPDATA'\s*,\s*tempfile\.gettempdir\(\)\s*\)\s*\)\s*/\s*'MoonRayForModo/")
IMPORT = 'from .cache_folder import root as cache_root\n'


def apply(folder):
    changed = []
    for path in sorted(Path(folder).glob('*.py')):
        if path.name == 'cache_folder.py':
            continue
        raw = path.read_bytes()
        crlf = b'\r\n' in raw
        text = raw.decode('utf-8').replace('\r\n', '\n')
        if not SITE.search(text):
            continue
        text = SITE.sub("cache_root() / '", text)
        if IMPORT not in text:
            # After the module's first top-level import.
            lines = text.split('\n')
            at = next(i for i, line in enumerate(lines) if line.startswith(('import ', 'from ')))
            lines.insert(at, IMPORT.rstrip('\n'))
            text = '\n'.join(lines)
        path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
        changed.append(path.name)
    return changed


if __name__ == '__main__':
    print(apply(sys.argv[1]))
