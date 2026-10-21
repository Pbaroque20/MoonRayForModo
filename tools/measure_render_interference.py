"""How much a MoonRay render slows the rest of the machine (Modo, as a stand-in), with and without the low-latency
measures: MoonRay at below-normal priority, and two of the processor's threads left to everything else.

measure_render_interference.py <runtime> <scene.rdla> [<scene.rdlb>]

A stand-in for Modo's own work runs at normal priority: every 16 ms (a frame of a 60 Hz viewport) it does a fixed
amount of work and notes how late it finished. It is timed alone, then beside a render in each way. Small renders."""
import ctypes
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'kit/MoonRayForModo/python'))
from moonray_modo import native

BELOW_NORMAL = 0x4000
PROCESS_SET_INFORMATION = 0x0200


def lower(pid):
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    ctypes.windll.kernel32.SetPriorityClass(handle, BELOW_NORMAL)
    ctypes.windll.kernel32.CloseHandle(handle)


def frames(seconds, stop=None):
    """The stand-in's frames: how long each took past its 16 ms budget's work (ms)."""
    work = 0
    began = time.perf_counter()
    for _ in range(100000):
        work += 1
    unit = time.perf_counter() - began          # one burst, measured alone at start
    late = []
    end = time.perf_counter() + seconds
    while time.perf_counter() < end and not (stop and stop.is_set()):
        frame = time.perf_counter()
        for _ in range(100000):
            work += 1
        late.append((time.perf_counter() - frame) * 1000)
        rest = 0.016 - (time.perf_counter() - frame)
        if rest > 0:
            time.sleep(rest)
    return late


def summary(label, late):
    late = sorted(late)
    print('%-34s frames %4d  median %6.1f ms  p95 %6.1f ms  worst %6.1f ms' %
          (label, len(late), statistics.median(late), late[int(len(late) * .95)], late[-1]), flush=True)


def main():
    runtime, scenes = Path(sys.argv[1]), [Path(p).resolve() for p in sys.argv[2:]]
    summary('Modo stand-in alone', frames(8))
    cores = os.cpu_count() or 1
    for label, threads, low in (('render as today', 0, False), ('render below-normal', 0, True),
                                ('below-normal, %d of %d threads' % (max(1, cores - 2), cores), max(1, cores - 2), True)):
        out = root / 'test-results' / 'interference'
        out.mkdir(parents=True, exist_ok=True)
        args = [str(runtime / 'moonray.exe')]
        for scene in scenes:
            args += ['-in', str(scene)]
        args += ['-out', str(out / 'beauty.exr'), '-exec_mode', 'vectorized', '-res', '4',
                 '-scene_var', 'sampling_mode', '0', '-scene_var', 'pixel_samples', '256']
        if threads:
            args += ['-threads', str(threads)]
        process = subprocess.Popen(args, cwd=scenes[0].parent, env=native.environment(runtime), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
        if low:
            lower(process.pid)
        time.sleep(5)                         # past loading, into rendering
        done = threading.Event()
        late = frames(10, done) if process.poll() is None else []
        process.kill()
        process.wait()
        summary(label, late or [0])


if __name__ == '__main__':
    main()
