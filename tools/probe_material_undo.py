# python
import json
from pathlib import Path
import modo
from moonray_modo import properties
scene=modo.Scene()
materials=[i for i in scene.items('advancedMaterial') if properties.read(i).get('shader')=='DwaBaseMaterial']
assert len(materials)==1, 'Assignment Undo did not remove the new shader'
mesh=scene.item('MoonShine assignment test')
assert mesh.geometry.polygons[0].materialTag==materials[0].parent.channel('ptag').get(), 'Assignment Undo did not restore polygon tags'
path=Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\material-host.json')
report=json.loads(path.read_text()); report['assignment_undo']=True
path.write_text(json.dumps(report,indent=2))
print('MoonShine assignment Undo passed')
