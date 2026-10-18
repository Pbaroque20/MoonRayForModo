"""Run a saved scene through MoonRay's loaded preview session (MOONRAY_MODO_SESSION) again and again, to catch a crash
that comes only now and then. Each run starts a session on the scene, waits for its frame to finish, and ends it.
Printed: each run's outcome, and the session log's last lines for a run that fails.
Usage: stress_persistent_scene.py <runtime> <scene.rdla> [--runs N] [--mode xpu|vectorized|scalar]"""
import argparse
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402


def run_once(runtime, scene, out, mode):
    out.mkdir(parents=True, exist_ok=True)
    env = native.environment(runtime)
    env['MOONRAY_MODO_SESSION'] = str(out)
    env['MOONRAY_MODO_GENERATION'] = '1'
    process = subprocess.Popen([str(runtime / 'moonray.exe')] + native.arguments(scene, out / 'main.exr', 0, mode), cwd=out, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    messages = queue.Queue()

    def reader():
        with (out / 'session.log').open('wb') as log:
            for line in iter(process.stdout.readline, b''):
                log.write(line)
                log.flush()
                messages.put(line.decode('utf-8', errors='replace').strip())
        messages.put('EXIT')
    threading.Thread(target=reader, daemon=True).start()
    started = time.monotonic()
    try:
        while time.monotonic() - started < 600:
            try:
                line = messages.get(timeout=1)
            except queue.Empty:
                continue
            if line == '@@MODO_SESSION DONE 1':
                command = out / 'command.tmp'
                command.write_text('2\nquit\n-\n-\n', encoding='utf-8')
                command.replace(out / 'command.txt')
                code = process.wait(timeout=60)
                return 'done in %.0f s, exit 0x%08x' % (time.monotonic() - started, code & 0xffffffff), code == 0
            if line == 'EXIT':
                code = process.wait(timeout=30)
                return 'EXITED before finishing, 0x%08x' % (code & 0xffffffff), False
        return 'TIMED OUT', False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    parser.add_argument('scene', type=Path)
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--mode', default='xpu')
    args = parser.parse_args()
    runtime = native.find_runtime(args.runtime)
    scene = args.scene.resolve()
    base = scene.parent / ('stress_' + scene.stem + '_' + args.mode)
    failed = 0
    for index in range(1, args.runs + 1):
        out = base / str(index)
        said, ok = run_once(runtime, scene, out, args.mode)
        print('run %2d: %s' % (index, said), flush=True)
        if not ok:
            failed += 1
            lines = (out / 'session.log').read_text(encoding='utf-8', errors='replace').splitlines()
            print('    ' + '\n    '.join(lines[-10:]), flush=True)
    print('%d of %d runs failed' % (failed, args.runs))


if __name__ == '__main__':
    main()
