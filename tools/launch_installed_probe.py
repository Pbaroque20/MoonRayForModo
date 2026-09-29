"""Open the user's Modo 16.1v9 with the installed kit and run the live test."""
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
installation = root / 'test-results/kit-install.json'
if not installation.is_file():
    raise SystemExit('Install the validated kit first.')
manifest = json.loads(installation.read_text(encoding='utf-8'))
executable = Path(r'C:\Program Files\Modo16.1v9\modo\modo.exe')
if Path(manifest['modo_executable']) != executable:
    raise SystemExit('The kit installation does not target Modo 16.1v9.')
with (root / 'test-results/installed-modo-console.log').open('w', encoding='utf-8') as log:
    process = subprocess.Popen([str(executable), '-cmdlate:@{' + str(root / 'tools/probe_live.py') + '}'],
                               stdout=log, stderr=subprocess.STDOUT)
(root / 'test-results/installed-modo-process.json').write_text(
    json.dumps({'pid': process.pid, 'executable': str(executable)}, indent=2), encoding='utf-8')
print('Opened Modo 16.1v9; PID', process.pid)
