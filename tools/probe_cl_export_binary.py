# python
"""Command line: PROBE_SCENE written as a MoonRay scene (RDLB unless PROBE_FORMAT names another) by the kit's own export script (scripts/export_moonray.py, what
Convert LXO to RDL runs), as PROBE_FORMAT (rdlb unless named: rdla, rdlb or split) into PROBE_TARGET, timed. Writes
PROBE_OUT/report.json with what the script reported (opened in, written in) and the files' sizes."""
import json
import os
import pathlib
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\export-scene'))
out.mkdir(parents=True, exist_ok=True)
kind = os.environ.get('PROBE_FORMAT', 'rdlb')
target = pathlib.Path(os.environ['PROBE_TARGET'])
target.parent.mkdir(parents=True, exist_ok=True)
said = out / 'export-report.txt'
result = {'scene': os.environ.get('PROBE_SCENE'), 'format': kind, 'target': str(target)}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


began = time.perf_counter()
if os.environ.get('PROBE_NO_CRYPTO'):
    # The scene's Cryptomatte outputs left out (for a scene whose categories need a category-enabled runtime, where
    # the export is wanted for something else: a crash report's scene).
    import moonray_modo.cryptomatte as _crypto
    _crypto.enabled = lambda scene: False
    _crypto.multiple = lambda scene: False
    result['cryptomatte'] = 'left out'
try:
    lx.eval('@{kit_MoonRayForModo:scripts/export_moonray.py} "%s" "%s" format=%s "report=%s"' % (os.environ['PROBE_SCENE'], target, kind, said))
except Exception:
    result['error'] = traceback.format_exc()
result['seconds'] = round(time.perf_counter() - began, 1)
if said.is_file():
    result['said'] = said.read_text(encoding='utf-8', errors='replace').splitlines()
result['files'] = {p.name: p.stat().st_size for p in target.parent.iterdir() if p.is_file() and p.name.startswith(target.stem)}
save()
