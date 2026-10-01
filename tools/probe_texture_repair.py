# python
"""Exercise the running-session repair on a disposable textured scene."""
from pathlib import Path
root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
exec(compile((root/'tools/probe_image_textures.py').read_text(), 'probe_image_textures.py', 'exec'))
layer.setParent(mask, len(mask.children()))
scene.select(layer)
exec(compile((root/'tools/refresh_texture_fix.py').read_text(), 'refresh_texture_fix.py', 'exec'))
assert host.snapshot()['materials']['texture_test']['textures']['diffCol']['path']
assert list(mask.children())[0].type == 'imageMap'
print('Running-session texture repair passed')
