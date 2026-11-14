# python
"""Command-line test: how long the Rhizome window's export of a scene takes, part by part (rhizome_window.export_job):
Modo's reading (host.snapshot), the scene text with every list as text (as before), and with the geometry's lists
binary (rdlb.py, as the preview hands them over), with a profile of what the binary export still spends.
PROBE_SCENE the .lxo, PROBE_OUT the folder (test-results/rhizome-export), PROBE_EVALUATED=1 for evaluated geometry,
PROBE_TEXT=0 to skip the all-text export. Writes report.json, profile.txt and the exported job."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\rhizome-export'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    start = time.perf_counter()
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    result['open_s'] = round(time.perf_counter() - start, 2)
    from moonray_modo import host, rdla, rdlb, scene_setup
    evaluated = os.environ.get('PROBE_EVALUATED') == '1'
    held = scene_setup.values()
    start = time.perf_counter()
    scene = host.snapshot(evaluated_geometry=evaluated)
    result['read_s'] = round(time.perf_counter() - start, 2)
    start = time.perf_counter()
    scene_setup.configure(scene, held)
    result['configure_s'] = round(time.perf_counter() - start, 2)
    result['meshes'] = len(scene.get('meshes', []))
    arguments = (scene, scene['width'], scene['height'], held['samples'], held['environment'], str(out / 'probe.exr'))
    save()
    if os.environ.get('PROBE_TEXT', '1') == '1':
        start = time.perf_counter()
        text = rdla.scene_text(*arguments)
        result['text_s'] = round(time.perf_counter() - start, 2)
        result['text_mb'] = round(len(text) / 1e6, 1)
        start = time.perf_counter()
        (out / 'text.rdla').write_text(text, encoding='utf-8')
        result['text_write_s'] = round(time.perf_counter() - start, 2)
        del text
        save()
    profile = cProfile.Profile()
    start = time.perf_counter()
    profile.enable()
    with rdlb.collecting(fingerprints=False) as sink:
        text = rdla.scene_text(*arguments)
    payload = sink.payload() if sink.objects else b''
    profile.disable()
    result['binary_s'] = round(time.perf_counter() - start, 2)
    result['binary_text_mb'] = round(len(text) / 1e6, 1)
    result['binary_mb'] = round(len(payload) / 1e6, 1)
    start = time.perf_counter()
    (out / 'split.rdla').write_text(text, encoding='utf-8')
    (out / 'split.rdlb').write_bytes(payload)
    result['binary_write_s'] = round(time.perf_counter() - start, 2)
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(45)
    stream.write('\n\n==== by own time\n')
    pstats.Stats(profile, stream=stream).sort_stats('tottime').print_stats(30)
    stream.write('\n\n==== who calls min and max\n')
    pstats.Stats(profile, stream=stream).sort_stats('tottime').print_callers('builtins.min|builtins.max')
    (out / 'profile.txt').write_text(stream.getvalue())
    # Again: the encoded lists kept from the first (rdlb's cache), as a second frame or a second export finds them.
    start = time.perf_counter()
    with rdlb.collecting(fingerprints=False) as sink:
        rdla.scene_text(*arguments)
    sink.payload()
    result['binary_again_s'] = round(time.perf_counter() - start, 2)
except Exception:
    result['error'] = traceback.format_exc()
save()
