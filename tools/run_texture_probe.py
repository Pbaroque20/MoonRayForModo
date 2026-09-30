"""Run the texture fixture with a bounded lifetime and checked result."""
import json
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[1]
profile = root / 'test-results/host-profile'
report = root / 'test-results/textures/host.json'
if report.exists():
    report.unlink()
process = subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo_cl.exe',
    '-path:user=' + str(profile), '-config:' + str(profile/'MODO_CL16.1.CFG')],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    output, _ = process.communicate('@{%s}\n!app.quit\n' % (root/'tools/probe_image_textures.py'), timeout=120)
except subprocess.TimeoutExpired:
    process.kill()
    output, _ = process.communicate()
    raise SystemExit('Texture probe timed out: ' + output[-2000:])
if process.returncode or not report.is_file() or not json.loads(report.read_text()).get('passed'):
    raise SystemExit('Texture probe failed: ' + output[-2000:])
print(report.read_text())
