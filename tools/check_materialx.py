"""Read MaterialX files with the plugin's importer and say what became of each.

Usage: check_materialx.py <file.mtlx or folder> ..."""
import sys
import types
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import materialx


def main():
    files = []
    for given in sys.argv[1:]:
        given = Path(given)
        files += sorted(given.rglob('*.mtlx')) if given.is_dir() else [given]
    read = 0
    for path in files:
        try:
            graph = materialx.read(path)
            kinds = {}
            for node in graph['nodes'].values():
                kinds[node['type']] = kinds.get(node['type'], 0) + 1
            read += 1
            print('%-40s read: %d nodes (%s)' % (path.name, len(graph['nodes']), ', '.join('%s %d' % kv for kv in sorted(kinds.items()))))
        except Exception as exc:
            print('%-40s NOT READ: %s' % (path.name, str(exc)[:200]))
    print('%d of %d read' % (read, len(files)))


if __name__ == '__main__':
    main()
