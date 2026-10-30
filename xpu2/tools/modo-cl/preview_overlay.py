"""preview_overlay.py <live.rdla> <scene folder> <width> <height> [pixel samples]: the preview's outputs (the
/modo/preview RenderOutputs a live kit preview scene names) and its XPU2 generations UserData, written as an overlay
for an exported scene, with the outputs' files moved into <scene folder>/pv."""
import re
import sys
from pathlib import Path

live, folder = Path(sys.argv[1]), Path(sys.argv[2])
width, height = int(sys.argv[3]), int(sys.argv[4])
samples = int(sys.argv[5]) if len(sys.argv) > 5 else 8
text = live.read_text(encoding='utf-8')
start = text.index('RenderOutput("/modo/preview/')
end = text.index('\n}', text.index('UserData("/modo/xpu2/generations")')) + 2
block = text[start:end]
out = folder / 'pv'
out.mkdir(exist_ok=True)
target = str(out / 'pv').replace('\\', '\\\\')


def moved(m):
    name = m.group(1)
    suffix = name[name.rfind('\\') + 1:]
    suffix = suffix[suffix.find('.'):] if '.' in suffix else '.exr'
    return '["file_name"] = "%s%s"' % (target, suffix)


block = re.sub(r'\["file_name"\] = "([^"]*)"', moved, block)
overlay = ('SceneVariables { ["image_width"] = %d, ["image_height"] = %d, ["pixel_samples"] = %d, ["sampling_mode"] = 0 }\n'
           % (width, height, samples)) + block + '\n'
(out / 'preview-outputs.rdla').write_text(overlay, encoding='utf-8')
print(overlay.count('RenderOutput('), 'outputs ->', out / 'preview-outputs.rdla')
