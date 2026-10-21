# python
"""Command-line test: reading Modo's evaluated meshes (MOONRAY_PROBE_SCENE) before and after a mesh is added and
moved with the Transform tool held open, as an artist does while MoonLightIPR renders: each reading's time and the
pieces the adapter left out. Writes test-results/cl-export/prep/added_geometry.json."""
import json
import os
import pathlib
import time
import traceback
import lx

result = {'steps': []}
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\added_geometry.json')


def read(label):
    from moonray_modo import evaluated
    began = time.perf_counter()
    try:
        data = evaluated.capture(lx.service.Selection().GetTime())
        step = {'step': label, 'seconds': round(time.perf_counter() - began, 3), 'skipped': data.get('skipped'), 'fur_debug': data.get('fur_debug'),
                'surfaces': len(data.get('surfaces', [])), 'segments': sum(len(p['segments']) for p in data['prototypes'].values()), 'curves': [len(g.get('counts', [])) for g in evaluated.extra_geometry(data, [])], 'where': [(w, sorted({s['source_item'] for s in data['surfaces'] if s['source_id'] == w[0]})) for w in data.get('skipped_where', [])], 'timing': data.get('timing'), 'handing': data.get('handing')}
    except Exception as error:
        step = {'step': label, 'seconds': round(time.perf_counter() - began, 3), 'error': str(error)}
    result['steps'].append(step)
    out.write_text(json.dumps(result, indent=1))


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    read('opened')
    read('again')
    lx.eval('layer.new')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.attr prim.cube sizeX 0.5')
    lx.eval('tool.attr prim.cube sizeY 0.5')
    lx.eval('tool.attr prim.cube sizeZ 0.5')
    lx.eval('tool.doApply')
    read('cube tool open')
    lx.eval('tool.attr prim.cube sizeX 0.8')
    lx.eval('tool.doApply')
    read('cube resized, tool open')
    lx.eval('tool.set prim.cube off')
    read('cube tool dropped')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('tool.set xfrm.transform on')
    for n in range(4):
        lx.eval('tool.setAttr xfrm.transform TX %g' % (-0.1 * (n + 1)))
        lx.eval('tool.doApply')
        read('transform step %d, tool open' % n)
    lx.eval('tool.set xfrm.transform off')
    read('transform dropped')
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1))
