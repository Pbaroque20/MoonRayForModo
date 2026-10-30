"""make_variants.py <fixtures report.json> <output folder> <new case>=<base case>:<extra rdla line> ...: copies of fixture
cases with a line of RDLA appended to each scene (a scene variables override), and their report."""
import json
import shutil
import sys
from pathlib import Path

base = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
out = Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=False)
report = {'cases': {}}
for spec in sys.argv[3:]:
    name, rest = spec.split('=', 1)
    case, line = rest.split(':', 1)
    entry = dict(base['cases'][case])
    entry['scenes'] = {}
    for grid, path in base['cases'][case]['scenes'].items():
        src = Path(path).parent
        dst = out / name / f'grid-{grid}' / 'frozen'
        shutil.copytree(src, dst)
        scene = dst / 'scene.rdla'
        text = scene.read_text(encoding='utf-8')
        # Texture paths into the copied folder (forward, back and escaped back slashes).
        for a, b in ((str(src), str(dst)), (src.as_posix(), dst.as_posix()),
                     (str(src).replace('\\', '\\\\'), str(dst).replace('\\', '\\\\'))):
            text = text.replace(a, b)
        scene.write_text(text + line + '\n', encoding='utf-8')
        entry['scenes'][grid] = str(scene)
    report['cases'][name] = entry
(out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(out / 'report.json')
