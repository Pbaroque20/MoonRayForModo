"""catch_modo_crash.py [--launch]: attach the toolchain's gdb to the running Modo (or start Modo, then attach) and wait;
on an access violation, write the call stack of the faulting thread and of every thread to
test-results/xpu2-cl/modo-crash-<time>.log, then let Modo go on (a handled one) or crash as it would. Read only: it
changes nothing in Modo or the kit. Ctrl+C or closing Modo ends it."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GDB = Path(r'C:\Users\Raphael Tobar\MoonRayForModo\toolchain\msys64\ucrt64\bin\gdb.exe')
MODO = Path(r'C:\Program Files\Modo16.1v9\modo\modo.exe')
p = argparse.ArgumentParser()
p.add_argument('--launch', action='store_true', help='start Modo first')
a = p.parse_args()


def modo_pid():
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq modo.exe', '/FO', 'CSV', '/NH'], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if parts and parts[0].lower() == 'modo.exe':
            return int(parts[1])
    return None


if a.launch and modo_pid() is None:
    subprocess.Popen([str(MODO)], cwd=str(MODO.parent))
    for _ in range(120):
        time.sleep(1)
        if modo_pid():
            break
pid = modo_pid()
if pid is None:
    sys.exit('Modo is not running')
log = HERE / ('modo-crash-%s.log' % time.strftime('%Y%m%d-%H%M%S'))
script = HERE / 'catch_modo_crash.gdb'
script.write_text('\n'.join([
    'set pagination off',
    'set confirm off',
    'set print thread-events off',
    'handle SIGSEGV stop print pass',
    'handle SIGILL stop print pass',
    # A breakpoint is how Windows' heap reports a corrupted heap to a debugger (Modo ended with 0x80000003 when the
    # catcher passed it on unseen): stop on it too, write the stacks, then pass it on as before.
    'handle SIGTRAP stop print pass',
    'catch signal SIGSEGV',
    'commands',
    '  echo \\n==== access violation ====\\n',
    '  bt 40',
    '  info registers rip',
    '  thread apply all bt 16',
    '  info sharedlibrary',
    '  continue',
    'end',
    'catch signal SIGTRAP',
    'commands',
    '  echo \\n==== breakpoint ====\\n',
    '  bt 40',
    '  info registers rip',
    '  thread apply all bt 16',
    '  info sharedlibrary',
    '  continue',
    'end',
    'continue',
]) + '\n', encoding='utf-8')
env = {k: v for k, v in os.environ.items() if k not in ('PYTHONHOME', 'PYTHONPATH')}
env['PATH'] = str(GDB.parent) + os.pathsep + env.get('PATH', '')
print('attaching gdb to Modo', pid, '->', log)
with log.open('w', encoding='utf-8') as out:
    subprocess.run([str(GDB), '-q', '-batch', '-p', str(pid), '-x', str(script)], stdout=out, stderr=subprocess.STDOUT, env=env)
print('gdb ended; log at', log)
