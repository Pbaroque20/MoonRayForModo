"""Launch an isolated, hidden Modo command-line instance for API checks."""
import pathlib
import subprocess
import shutil
import xml.etree.ElementTree as ET
import json

root = pathlib.Path(__file__).resolve().parent
profile = root.parent / 'test-results/host-profile'
profile.mkdir(parents=True, exist_ok=True)
shutil.copytree(root.parent / 'kit/MoonRayForModo', profile / 'Configs/MoonRayForModo', dirs_exist_ok=True)
config = profile / 'MODO_CL16.1.CFG'
config.mkdir(exist_ok=True)
imports = ET.Element('configuration')
for item in ('resource:', 'module:Scripts', 'user:Configs', 'user:Scripts', str(root.parent / 'kit')):
    ET.SubElement(imports, 'import').text = item
ET.ElementTree(imports).write(str(config / 'Imports.cfg'), encoding='utf-8', xml_declaration=True)
result = root / 'probe_result.json'
if result.exists():
    result.unlink()
commands = '@{%s}\n!app.quit\n' % (root / 'probe_modo.py')
proc = subprocess.Popen(
    [r'C:\Program Files\Modo16.1v9\modo\modo_cl.exe', '-path:user=' + str(profile), '-config:' + str(config)],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, creationflags=subprocess.CREATE_NO_WINDOW)
try:
    output, _ = proc.communicate(commands, timeout=120)
except subprocess.TimeoutExpired:
    proc.kill()
    output, _ = proc.communicate()
(root / 'probe_console.log').write_text(output, encoding='utf-8')
print(output)
print('Exit:', proc.returncode)
if proc.returncode:
    raise SystemExit(proc.returncode)
report = json.loads(result.read_text(encoding='utf-8'))
if report.get('error') or not report.get('tests', {}).get('passed'):
    raise SystemExit('Modo host probe failed; see tools/probe_result.json')
