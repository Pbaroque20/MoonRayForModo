"""Start a separate graphical Modo instance with a project-local test profile."""
import pathlib
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
import argparse
import json

root = pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('probe',nargs='?',default='probe_gui.py')
parser.add_argument('--profile',default='gui-profile')
parser.add_argument('--wait',action='store_true')
parser.add_argument('--without-native',action='store_true')
parser.add_argument('--without-controller',action='store_true')
args=parser.parse_args()
if not args.profile.replace('-','').replace('_','').isalnum():
    raise SystemExit('Profile must be a simple directory name.')
profile = root / 'test-results' / args.profile
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
shutil.copytree(root / 'kit/MoonRayForModo', profile / 'Configs/MoonRayForModo', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('bin') if args.without_native else None)
if args.without_controller:
    kit_index=profile/'Configs/MoonRayForModo/index.cfg'
    tree=ET.parse(str(kit_index))
    for atom in list(tree.getroot()):
        if atom.get('type')=='StartupCommands': tree.getroot().remove(atom)
    tree.write(str(kit_index),encoding='utf-8',xml_declaration=True)
imports = ET.Element('configuration')
for location in ('resource:', 'module:Scripts', 'user:Configs', 'user:Scripts'):
    ET.SubElement(imports, 'import').text = location
config = profile / 'MODO16.1.CFG'
config.mkdir(exist_ok=True)
ET.ElementTree(imports).write(str(config / 'Imports.cfg'), encoding='utf-8', xml_declaration=True)
log = (root / 'test-results/gui-console.log').open('w', encoding='utf-8')
probe=root/'tools'/args.probe
assert probe.resolve().parent==root/'tools' and probe.is_file()
if probe.name.startswith('probe_native_preview') and not (root/'kit/MoonRayForModo/bin/MoonRayPreview.lx').is_file():
    bridge=root/'build/modo-bridge/MoonRayPreview.lx'
    if not bridge.is_file():
        raise SystemExit('Build the native preview adapter before launching this test.')
    extension=ET.Element('configuration')
    atom=ET.SubElement(extension,'atom',{'type':'Extensions64'})
    ET.SubElement(atom,'list',{'type':'AutoScan'}).text=bridge.parent.as_posix()
    ET.ElementTree(extension).write(str(profile/'Configs/native-preview.cfg'),
                                   encoding='utf-8',xml_declaration=True)
startup=subprocess.STARTUPINFO()
startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow=1  # This is an explicitly interactive GUI probe, not a hidden worker.
process = subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo.exe',
    '-path:user=' + str(profile), '-config:' + str(config),
    '-cmdlate:@{' + str(probe) + '}'], stdout=log, stderr=subprocess.STDOUT,startupinfo=startup)
(root / 'test-results/gui-process.txt').write_text(str(process.pid))
print('Started isolated Modo GUI test, PID', process.pid)
if args.wait:
    try:
        exit_code=process.wait(timeout=180)
        print('Modo exit:', exit_code)
        # Modo's GUI also returns 1 for a normal scripted quit in the no-plugin
        # control profile. Windows exception codes are never accepted.
        clean=exit_code in (0,1)
        (profile/'process-result.json').write_text(json.dumps({'pid':process.pid,
            'exit_code':exit_code,'clean_shutdown':clean},indent=2))
        if probe.name=='probe_pview_kit.py':
            report_path=root/'test-results/pview-kit/report.json'
            report=json.loads(report_path.read_text())
            if report.get('pid')==process.pid:
                report['clean_shutdown']=clean
                report['passed']=bool(report.get('render_cycle_passed') and clean)
                report_path.write_text(json.dumps(report,indent=2))
        if not clean: raise SystemExit(1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        print('Isolated test timed out; stopped PID', process.pid)
        raise SystemExit(1)
