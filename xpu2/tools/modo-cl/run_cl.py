"""run_cl.py <probe.py> [--timeout s] [--env KEY=VALUE ...]: run a probe in headless Modo (modo_cl.exe) with the XPU2
test profile (setup_profile.py) and the TestPreview settings key. Refuses while Modo runs."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = HERE / 'profile'
p = argparse.ArgumentParser()
p.add_argument('probe', type=Path)
p.add_argument('--timeout', type=int, default=900)
p.add_argument('--env', action='append', default=[])
a = p.parse_args()
listed = subprocess.run(['tasklist'], capture_output=True, text=True).stdout.lower()
if 'modo.exe' in listed:
    raise SystemExit("Modo is running: close it first (the user's Modo).")
environment = dict(os.environ)
environment['MOONRAY_MODO_PREFERENCES'] = 'TestPreview'
environment.update(dict(v.split('=', 1) for v in a.env))
commands = '@{%s}\napp.quit\n' % a.probe.resolve()
try:
    done = subprocess.run([r'C:\Program Files\Modo16.1v9\modo\modo_cl.exe', '-path:user=' + str(PROFILE), '-config:' + str(PROFILE / 'Configs')],
                          input=commands.encode('utf-8'), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=environment,
                          timeout=a.timeout, creationflags=subprocess.CREATE_NO_WINDOW)
except subprocess.TimeoutExpired:
    raise SystemExit('Timed out after %d seconds' % a.timeout)
(HERE / 'cl-console.log').write_bytes(done.stdout)
print('modo_cl exit:', done.returncode)
print(done.stdout.decode('utf-8', errors='replace')[-2000:])
