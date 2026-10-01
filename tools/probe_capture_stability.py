# python
"""Check that repeated exports of the same scene are identical."""
import json
import hashlib
from pathlib import Path
import lx
from moonray_modo import host,properties
root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
lx.eval('!scene.open {%s}' % (root/'test-results/pview-kit/MoonRay Preview Test.lxo'))
digests=[]
for index in range(8):
    value=[host.snapshot(),properties.scene_settings()]
    encoded=json.dumps(value,sort_keys=True,indent=2)
    digests.append(hashlib.sha256(encoded.encode()).hexdigest())
    (root/('test-results/pview-kit/stability-%d.json' % index)).write_text(encoded)
(root/'test-results/pview-kit/stability-report.json').write_text(json.dumps({
    'app_version':lx.eval('query platformservice appversion ?'),
    'passed':len(set(digests))==1,'digests':digests},indent=2))
assert len(set(digests))==1, 'Unchanged scene exports differ'
