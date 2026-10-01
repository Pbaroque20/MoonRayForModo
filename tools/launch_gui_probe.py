"""Start a separate graphical Modo instance with a project-local test profile."""
import pathlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

root = pathlib.Path(__file__).resolve().parents[1]
profile = root / 'test-results/gui-profile'
profile.mkdir(parents=True, exist_ok=True)
# An early viewport.restore experiment replaced the welcome pane's contents.
# Remove only those exact test-owned layout overrides before future launches.
saved_frame=profile/'MODO16.1.CFG/MODO16.1.CFG/Frame.cfg'
if saved_frame.is_file():
    tree=ET.parse(str(saved_frame))
    changed=False
    for atom in tree.getroot().findall('atom'):
        for entry in list(atom):
            misplaced_intro=(entry.get('key')=='edit.modoIntro' and
                any('MoonRayNativeViewport' in (port.text or '') for port in entry.findall('list')))
            if misplaced_intro or entry.get('key')=='edit.MoonRayNativeViewport':
                atom.remove(entry); changed=True
    if changed:
        backup=root/'backups/native-preview-window'
        backup.mkdir(parents=True,exist_ok=True)
        shutil.copy2(saved_frame,backup/'Frame.before-repair.cfg')
        tree.write(str(saved_frame),encoding='utf-8',xml_declaration=True)
shutil.copytree(root / 'kit/MoonRayForModo', profile / 'Configs/MoonRayForModo', dirs_exist_ok=True)
imports = ET.Element('configuration')
for location in ('resource:', 'module:Scripts', 'user:Configs', 'user:Scripts'):
    ET.SubElement(imports, 'import').text = location
config = profile / 'MODO16.1.CFG'
config.mkdir(exist_ok=True)
ET.ElementTree(imports).write(str(config / 'Imports.cfg'), encoding='utf-8', xml_declaration=True)
log = (root / 'test-results/gui-console.log').open('w', encoding='utf-8')
probe=root/'tools'/(sys.argv[1] if len(sys.argv)>1 else 'probe_gui.py')
assert probe.resolve().parent==root/'tools' and probe.is_file()
if probe.name.startswith('probe_native_preview'):
    bridge=root/'build/modo-bridge/MoonRayPreview.lx'
    if not bridge.is_file():
        raise SystemExit('Build the native preview adapter before launching this test.')
    extension=ET.Element('configuration')
    atom=ET.SubElement(extension,'atom',{'type':'Extensions64'})
    ET.SubElement(atom,'list',{'type':'AutoScan'}).text=bridge.parent.as_posix()
    ET.ElementTree(extension).write(str(profile/'Configs/native-preview.cfg'),
                                   encoding='utf-8',xml_declaration=True)
process = subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo.exe',
    '-path:user=' + str(profile), '-config:' + str(config),
    '-cmdlate:@{' + str(probe) + '}'], stdout=log, stderr=subprocess.STDOUT)
(root / 'test-results/gui-process.txt').write_text(str(process.pid))
print('Started isolated Modo GUI test, PID', process.pid)
if '--wait' in sys.argv:
    try:
        print('Modo exit:', process.wait(timeout=180))
    except subprocess.TimeoutExpired:
        process.kill()
        print('Isolated test timed out; stopped PID', process.pid)
