# python
"""Capture a supplied still image through Modo's real Shader Tree."""
import os
from pathlib import Path
root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
source_file = Path(os.environ['MOONRAY_TEST_IMAGE']).resolve()
assert source_file.is_file()
exec(compile((root/'tools/probe_image_textures.py').read_text(), 'probe_image_textures.py', 'exec'))
clip.channel('filename').set(str(source_file))
snapshot = host.snapshot()
exported = snapshot['materials']['texture_test']['layers'][0]
assert Path(exported['path']) == source_file
assert not snapshot['warnings'], snapshot['warnings']
output = root/'test-results/image-file'
output.mkdir(parents=True, exist_ok=True)
(output/'host-snapshot.json').write_text(json.dumps(snapshot, indent=2))
print('Supplied image exported through Modo Shader Tree:', source_file)
