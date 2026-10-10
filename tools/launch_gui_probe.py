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
parser.add_argument('--timeout',type=int,default=180)
parser.add_argument('--without-native',action='store_true')
parser.add_argument('--without-controller',action='store_true')
parser.add_argument('--kit-source',type=pathlib.Path)
parser.add_argument('--user-settings',action='store_true',help='Copy user UI preferences into the disposable profile')
parser.add_argument('--user-kits',action='store_true',help='Read other installed kit definitions without copying or modifying them')
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
shutil.copytree(args.kit_source.resolve() if args.kit_source else root / 'kit/MoonRayForModo', profile / 'Configs/MoonRayForModo', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('bin') if args.without_native else None)
startup_config=ET.Element('configuration')
startup_preferences=ET.SubElement(startup_config,'atom',{'type':'Preferences'})
ET.SubElement(startup_preferences,'atom',{'type':'application.modoIntroShowStartup'}).text='false'
# Preserve the user's existing 16.1 choices in the isolated profile. Leaving
# these unset opens the first-run modal on top of PView and invalidates tests.
preferences=pathlib.Path.home()/'AppData/Roaming/Luxology/MODO16.1.CFG/Preferences.cfg'
if preferences.is_file():
    existing=ET.parse(str(preferences))
    for key in ('application.autoCheckForUpdates','application.autoPostUsageStats'):
        value=existing.getroot().find(".//atom[@type='%s']"%key)
        if value is not None:
            ET.SubElement(startup_preferences,'atom',{'type':key}).text=value.text
ET.ElementTree(startup_config).write(str(profile/'Configs/probe-startup.cfg'),
    encoding='utf-8',xml_declaration=True)
if args.without_controller:
    kit_index=profile/'Configs/MoonRayForModo/index.cfg'
    tree=ET.parse(str(kit_index))
    for atom in list(tree.getroot()):
        if atom.get('type')=='StartupCommands': tree.getroot().remove(atom)
    tree.write(str(kit_index),encoding='utf-8',xml_declaration=True)
imports = ET.Element('configuration')
for location in ('resource:', 'module:Scripts', 'user:Configs', 'user:Scripts'):
    ET.SubElement(imports, 'import').text = location
if args.user_kits:
    user_kits=pathlib.Path.home()/'AppData/Roaming/Luxology/Kits'
    for directory in sorted(user_kits.iterdir()):
        if not directory.is_dir() or directory.name=='MoonRayForModo':continue
        for path in directory.glob('*.cfg'):
            try:definition=ET.parse(str(path)).getroot()
            except ET.ParseError:continue
            if definition.get('kit'):ET.SubElement(imports,'import').text=path.as_posix()
config = profile / 'MODO16.1.CFG'
config.mkdir(exist_ok=True)
if args.user_settings:
    saved=pathlib.Path.home()/'AppData/Roaming/Luxology/MODO16.1.CFG'
    for path in saved.glob('*.cfg'):
        if path.name.lower() not in ('imports.cfg','extensions64.cfg'):
            shutil.copy2(path,config/path.name)

ET.ElementTree(imports).write(str(config / 'Imports.cfg'), encoding='utf-8', xml_declaration=True)
log = (root / 'test-results/gui-console.log').open('w', encoding='utf-8')
probe=root/'tools'/args.probe
assert probe.resolve().parent==root/'tools' and probe.is_file()
# The test Modo previews with the MoonLightIPR that is built now, not with one an earlier test left in its profile:
# an older session refuses the scenes a newer plugin sends it.
import os,sys
environment=dict(os.environ)
if (root/'build/moonlightipr/bin/moonlightipr_session.exe').is_file() and not environment.get('MOONRAY_MODO_MOONLIGHTIPR'):
    subprocess.run([sys.executable,str(root/'tools/stage_moonlightipr.py'),'--destination',str(root/'build/moonlightipr/stage')],check=True,stdout=subprocess.DEVNULL)
    environment['MOONRAY_MODO_MOONLIGHTIPR']=str(root/'build/moonlightipr/stage')
startup=subprocess.STARTUPINFO()
startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow=1  # This is an explicitly interactive GUI probe, not a hidden worker.
process = subprocess.Popen([r'C:\Program Files\Modo16.1v9\modo\modo.exe',
    '-path:user=' + str(profile), '-config:' + str(config),
    '-cmdlate:@{' + str(probe) + '}'], stdout=log, stderr=subprocess.STDOUT,startupinfo=startup,env=environment)
(root / 'test-results/gui-process.txt').write_text(str(process.pid))
print('Started isolated Modo GUI test, PID', process.pid)
if args.wait:
    try:
        exit_code=process.wait(timeout=args.timeout)
        print('Modo exit:', exit_code)
        # Modo's GUI also returns 1 for a normal scripted quit in the no-plugin
        # control profile. Windows exception codes are never accepted.
        clean=exit_code in (0,1)
        (profile/'process-result.json').write_text(json.dumps({'pid':process.pid,
            'exit_code':exit_code,'clean_shutdown':clean},indent=2))
        if not clean: raise SystemExit(1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        print('Isolated test timed out; stopped PID', process.pid)
        raise SystemExit(1)
