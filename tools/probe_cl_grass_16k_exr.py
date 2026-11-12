# python
"""Command-line: Grass with its ground's 8K albedo swapped for a 16K float EXR (test-results/volcano/diffuse16k.exr), as
a tester's volcano had a 16K EXR diffuse map, saved as test-results/volcano/grass16k.lxo (the original untouched).
Writes grass16k.json beside it."""
import json
import pathlib
import traceback
import lx
import modo

folder = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\volcano')
result = {}
try:
    lx.eval('!scene.open {%s} normal' % r'C:\Users\Raphael Tobar\Downloads\Grass\wildGreen_Patches_bundled.lxo')
    scene = modo.Scene()
    for clip in scene.items('videoStill'):
        name = clip.channel('filename').get()
        if 'vckmabus_8K_Albedo' in name:
            clip.channel('filename').set(str(folder / 'diffuse16k.exr'))
            result['swapped'] = [name, clip.channel('filename').get()]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (folder / 'grass16k.lxo'))
    result['saved'] = (folder / 'grass16k.lxo').is_file()
except Exception:
    result['error'] = traceback.format_exc()[-2000:]
(folder / 'grass16k.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
