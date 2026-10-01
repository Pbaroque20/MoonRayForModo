# python
import json
from pathlib import Path
import modo
from moonray_modo import evaluated, host
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
data=evaluated.capture(0,path=root/'build/modo-geometry/MoonRayPreview.lx')
(root/'test-results/render-cache/after-command.json').write_text(json.dumps(data,indent=2))
ordinary=host.snapshot()
print('Ordinary faces:',sum(len(m['faces']) for m in ordinary['meshes']))
print('Cache faces:',sum(len(s['faces']) for p in data['prototypes'].values() for s in p['segments']))
