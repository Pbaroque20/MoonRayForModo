"""Render scenes the probes packed for MoonLightIPR (<case>.mls, written with PROBE_MLS=1 by tools/probe_cl_light_images.py
and tools/probe_cl_ies_lights.py) outside Modo: the session from <runtime>/moonlightipr, as
tools/check_moonlightipr_session.py drives one. Writes moonlightipr_<case>.exr beside each.

render_snapshot_moonlightipr.py <runtime> <folder> <width> <height> <case> [case ...]"""
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402
from moonray_modo.shared_image import receive  # noqa: E402


def main():
    runtime, folder = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    width, height = int(sys.argv[3]), int(sys.argv[4])
    os.environ['MOONRAY_MODO_RUNTIME'] = str(runtime)
    session_folder = runtime / 'moonlightipr'
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    env['PATH'] = str(session_folder) + os.pathsep + env.get('PATH', '')
    process = subprocess.Popen([str(session_folder / 'moonlightipr_session.exe'), str(session_folder / 'MoonLightIPRKernel.ptx')],
                               cwd=str(session_folder), stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    generation = 0
    try:
        for case in sys.argv[5:]:
            generation += 1
            staged = folder / ('%s.mls' % case)
            process.stdin.write(('scene %d %s\n' % (generation, staged)).encode())
            process.stdin.flush()
            pixels, event = None, None
            for raw in process.stdout:
                line = raw.decode('utf-8', errors='replace').strip()
                if line.startswith('@@MODO_SHARED '):
                    got, _, w, h, data = receive(line, process.pid)
                    if got == generation and (w, h) == (width, height):
                        pixels = data
                elif line.startswith('@@MODO_SESSION '):
                    parts = line.split()
                    if parts[1] in ('DONE', 'FAILED') and int(parts[2]) == generation:
                        event = parts[1]
                        break
            if event != 'DONE' or pixels is None:
                print('%s: MoonLightIPR %s' % (case, event))
                continue
            # Frames arrive bottom row first: a PFM as the format has it, then an OpenEXR.
            pfm = folder / ('moonlightipr_%s.pfm' % case)
            pfm.write_bytes(('PF\n%d %d\n-1.0\n' % (width, height)).encode() + pixels)
            subprocess.run([str(runtime / 'oiiotool.exe'), str(pfm), '-d', 'float', '-o', str(folder / ('moonlightipr_%s.exr' % case))],
                           env=native.environment(runtime), check=True)
            pfm.unlink()
            print('%s: done' % case)
        process.stdin.write(b'quit\n')
        process.stdin.flush()
        process.wait(timeout=20)
    finally:
        if process.poll() is None:
            process.kill()


if __name__ == '__main__':
    main()
