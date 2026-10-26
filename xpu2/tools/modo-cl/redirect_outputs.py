"""redirect_outputs.py <scene.rdla> <out.rdla> <folder>: a copy of a live preview scene with every RenderOutput's file
moved into <folder> (so a test never writes into the running Modo's session files)."""
import re
import sys
from pathlib import Path

source, target, folder = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
folder.mkdir(parents=True, exist_ok=True)
text = source.read_text(encoding='utf-8')
base = str(folder / 'out').replace('\\', '\\\\')


def moved(m):
    name = m.group(1)
    leaf = name.replace('\\\\', '\\').split('\\')[-1]
    suffix = leaf[leaf.find('.'):] if '.' in leaf else '.exr'
    return '["file_name"] = "%s%s"' % (base, suffix)


text, n = re.subn(r'\["file_name"\] = "([^"]*)"', moved, text)
target.write_text(text, encoding='utf-8')
print(n, 'outputs moved; Temp left:', 'MoonRayForModo-m1ycz20c' in text)
