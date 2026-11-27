"""Run probes and Modo commands one after another in one Modo command-line session (modo_cl.exe), with no window: for
probes that need commands a script may not run (app.undo, app.redo) between their steps.

launch_cl_steps.py [--profile NAME] [--timeout seconds] step ...

A step ending in .py is a probe in tools/, run as tools/launch_cl_probe.py runs one; any other step is a Modo command
line, given as it is (quote it). The kit is copied into the test profile first, as launch_cl_probe.py does."""
import argparse
import os
import pathlib
import shutil
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('steps', nargs='+')
parser.add_argument('--timeout', type=int, default=600)
parser.add_argument('--profile', default='gui-profile')
args = parser.parse_args()
profile = root / 'test-results' / args.profile
config = profile / 'Configs'
if not (config / 'MoonRayForModo').is_dir():
    raise SystemExit('Run a GUI probe once first: it sets the test profile up (%s).' % profile)
shutil.copytree(root / 'kit/MoonRayForModo', config / 'MoonRayForModo', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
lines = []
for step in args.steps:
    if step.endswith('.py'):
        probe = root / 'tools' / step
        assert probe.resolve().parent == root / 'tools' and probe.is_file(), step
        lines.append('@{%s}' % probe)
    else:
        lines.append(step)
lines.append('app.quit')
environment = dict(os.environ, MOONRAY_MODO_PREFERENCES='TestPreview')
try:
    done = subprocess.run([r'C:\Program Files\Modo16.1v9\modo\modo_cl.exe', '-path:user=' + str(profile), '-config:' + str(config)],
                          input=('\n'.join(lines) + '\n').encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment,
                          timeout=args.timeout, creationflags=subprocess.CREATE_NO_WINDOW)
except subprocess.TimeoutExpired:
    raise SystemExit('Timed out after %d seconds' % args.timeout)
(root / 'test-results/cl-console.log').write_bytes(done.stdout)
print('modo_cl exit:', done.returncode)
print(done.stdout.decode('utf-8', errors='replace')[-1500:])
