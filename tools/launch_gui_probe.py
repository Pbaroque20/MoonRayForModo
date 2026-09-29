"""Start a separate graphical Modo instance with a project-local test profile."""
import pathlib
import shutil
import subprocess
import xml.etree.ElementTree as ET

root = pathlib.Path(__file__).resolve().parents[1]
profile = root / 'test-results/gui-profile'
profile.mkdir(parents=True, exist_ok=True)
shutil.copytree(root / 'kit/MoonRayForModo', profile / 'Configs/MoonRayForModo', dirs_exist_ok=True)
imports = ET.Element('configuration')
for location in ('resource:', 'module:Scripts', 'user:Configs', 'user:Scripts'):
    ET.SubElement(imports, 'import').text = location
config = profile / 'MODO16.1.CFG'
config.mkdir(exist_ok=True)
ET.ElementTree(imports).write(str(config / 'Imports.cfg'), encoding='utf-8', xml_declaration=True)
log = (root / 'test-results/gui-console.log').open('w', encoding='utf-8')
process = subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo.exe',
    '-path:user=' + str(profile), '-config:' + str(config),
    '-cmdlate:@{' + str(root / 'tools/probe_gui.py') + '}'], stdout=log, stderr=subprocess.STDOUT)
(root / 'test-results/gui-process.txt').write_text(str(process.pid))
print('Started isolated Modo GUI test, PID', process.pid)
