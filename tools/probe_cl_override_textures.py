# python
"""Command line: PROBE_SCENE written for MoonRay as it is, then with a plain grey material put at the top of its Shader
Tree with no mask (covering every material below it, as a tester did): how many textures each MoonRay scene asks for,
and each material's stack. A material covering everything should leave no texture to load. Writes
PROBE_OUT/report.json (test-results/override-textures)."""
import json
import os
import pathlib
import re
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\override-textures'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE')}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def written(name):
    from moonray_modo import host, rdla
    scene = host.snapshot()
    text = rdla.scene_text(scene, 320, 180, 1, 0.2)
    (out / (name + '.rdla')).write_text(text, encoding='utf-8')
    textures = sorted(set(re.findall(r'"([^"]+\.tx)"', text)))
    stacks = {tag: [[(l.get('kind'), l.get('effect')) for l in row.get('layers', [])] for row in m.get('material_stack', [])]
              for tag, m in (scene.get('materials') or {}).items()}
    return {'textures': len(textures), 'stacks': stacks}


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    result['as_it_is'] = written('as_it_is')
    save()
    document = modo.Scene()
    grey = document.addItem('advancedMaterial', name='Grey override')
    grey.setParent(document.renderItem, len(document.renderItem.children()))
    grey.channel('diffCol.R').set(.5)
    grey.channel('diffCol.G').set(.5)
    grey.channel('diffCol.B').set(.5)
    result['top_children'] = [(c.name, c.type) for c in document.renderItem.children()][-4:]
    result['with_grey_on_top'] = written('with_grey_on_top')
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
