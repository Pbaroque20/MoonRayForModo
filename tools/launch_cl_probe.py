"""Run a probe script in Modo's command-line version (modo_cl.exe), with no window.

For probes that only read the scene or call the plugin's own modules: what the kit hands to the renderers, how long
that takes, the geometry adapter. The preview window is not there (it is a Qt view of Modo's interface), so probes that
press its buttons or look at its picture need tools/launch_gui_probe.py.

launch_cl_probe.py <probe in tools/> [--timeout seconds]

The probe runs once from top to bottom; it has no event loop and must not wait on timers. It uses the same test
profile as the GUI probes (test-results/gui-profile), so run one at a time."""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('probe')
parser.add_argument('--timeout', type=int, default=300)
parser.add_argument('--profile', default='gui-profile')
args = parser.parse_args()
probe = root / 'tools' / args.probe
assert probe.resolve().parent == root / 'tools' and probe.is_file()
profile = root / 'test-results' / args.profile
config = profile / 'Configs'
if not (config / 'MoonRayForModo').is_dir():
    raise SystemExit('Run a GUI probe once first: it sets the test profile up (%s).' % profile)
# The kit as it now is, over the copy in the profile; what only lives there (the geometry adapter) is left.
shutil.copytree(root / 'kit/MoonRayForModo', config / 'MoonRayForModo', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
environment = dict(os.environ)
environment['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
commands = '@{%s}\napp.quit\n' % probe
try:
    done = subprocess.run([r'C:\Program Files\Modo16.1v9\modo\modo_cl.exe', '-path:user=' + str(profile), '-config:' + str(config)],
                          input=commands.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment, timeout=args.timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW)
except subprocess.TimeoutExpired:
    raise SystemExit('Timed out after %d seconds' % args.timeout)
(root / 'test-results/cl-console.log').write_bytes(done.stdout)
print('modo_cl exit:', done.returncode)
print(done.stdout.decode('utf-8', errors='replace')[-1500:])
