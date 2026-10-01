# python
"""Regress real Shader Tree effect names and overridden-layer diagnostics."""
from pathlib import Path
root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
exec(compile((root/'tools/probe_image_textures.py').read_text(), 'probe_image_textures.py', 'exec'))
from moonray_modo import textures
from moonray_modo import properties
properties.write(material, {'shader':'DwaBaseMaterial'})
for external, internal in dict(textures.EFFECT_ALIASES, dissolve='dissolve').items():
    layer.channel('effect').set(external)
    data = host.snapshot()
    node = data['materials']['texture_test']['layers'][0]
    assert node['effect'] == internal, (external, node)
    assert node['srgb'] == (internal in textures.COLOR_EFFECTS), external
properties.write(material, {'shader':''})
layer.channel('effect').set('specAmount')
standard = host.snapshot()
assert standard['materials']['texture_test']['layers'][0]['effect'] == 'specAmt'
assert not standard['warnings'], standard['warnings']
properties.write(material, {'shader':'DwaBaseMaterial'})
layer.channel('effect').set('diffColor')
layer.setParent(mask, len(mask.children()))
below = host.snapshot()
assert not below['materials']['texture_test'].get('layers')
assert any('below its material' in w for w in below['warnings']), below['warnings']
layer.setParent(mask, 0)
above = host.snapshot()
assert above['materials']['texture_test']['layers'][0]['effect'] == 'diffCol'
assert not above['warnings'], above['warnings']
(root/'test-results/textures/effects.json').write_text(json.dumps({'passed': True,
    'effects': textures.EFFECT_ALIASES, 'below_material_warning': True}, indent=2))
print('Real Modo effect names and layer placement regression passed')
