"""Glass bias hunt: make_glass_scenes.py <folder>. The adaptive AOV scene uniform at 256 samples (pixel_samples 16),
beauty alone, and variants: white transmission, no key light, no clamping, deeper paths, the glass ball alone."""
import re
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
base = (here / 'aov2' / 'aov-adaptive.rdla').read_text(encoding='utf-8')
base = re.sub(r'\["sampling_mode"\]=\d+', '["sampling_mode"]=0', base)
base = re.sub(r'RenderOutput\("/(alpha|weight|aux|aaux)"\) \{[^}]*\}\n?', '', base)
base = re.sub(r'RenderOutput\("/(alpha|weight|aux|aaux)"\), ?', '', base)
cases = {
    'gl-base': base,
    'gl-white': base.replace('["transmission_color"]=Rgb(0.9,1.0,0.95)', '["transmission_color"]=Rgb(1,1,1)'),
    'gl-noclamp': base.replace('["russian_roulette_threshold"]=0', '["russian_roulette_threshold"]=0, ["sample_clamping_value"]=0'),
    'gl-deep': base.replace('["max_depth"]=4', '["max_depth"]=8'),
    'gl-nokey': base.replace('LightSet("/lights") { EnvLight("/fill"), RectLight("/key") }', 'LightSet("/lights") { EnvLight("/fill") }'),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases', 'nokey changed' if cases['gl-nokey'] != base else 'nokey UNCHANGED')
