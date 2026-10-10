"""Unpack a packaged release into an empty folder and run it from there, with nothing of this machine on the path.

Usage: check_release_package.py <version> [folder to unpack into]
Checks that the two ZIPs merge into one kit with what it needs, that MoonRay renders from the unpacked runtime in GPU
and CPU modes with a bare environment, that the scene reader, the VDB reader, the hair grower and the MoonLightIPR session start, that the kit finds its
own runtime, and that the unpacked kit writes a scene MoonRay accepts for a mesh one part of which holds a volume."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEED = ['index.cfg', 'layout.cfg', 'bin/MoonRayGeometry.lx', 'runtime/moonray.exe', 'runtime/modo_rdl_import.exe', 'runtime/modo_vdb_grid.exe', 'runtime/modo_hair_grow.exe', 'runtime/denoise.exe', 'runtime/oiiotool.exe',
        'runtime/moonlightipr/moonlightipr_session.exe', 'runtime/moonlightipr/MoonLightIPRKernel.ptx', 'runtime/moonlightipr/cudart64_12.dll', 'runtime/shaders/OptixGPUPrograms.ptx',
        'python/moonray_modo/mesh_reader.py', 'python/moonray_modo/primitive_attributes.py', 'python/moonray_modo/rdl_import.py', 'INSTALLATION.md', 'LICENSE.txt']
VOLUME = '''
import subprocess, sys
from pathlib import Path
kit, tools, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
sys.path[:0] = [tools, str(kit / 'python')]
import check_moonlightipr_session as fixture
from moonray_modo import native, rdla
rt = native.find_runtime(kit / 'runtime')
base = fixture.snapshot()
ground, ball, cube = (dict(mesh) for mesh in base['meshes'])
count = len(ball['faces'])
materials = dict(base['materials'], glass={'color': [.9, .9, .9], 'roughness': .05, 'transmission': 1.0, 'transmission_color': [.3, .8, .5], 'absorption_distance': .5, 'ior': 1.5},
                 plain={'color': [.7, .2, .2], 'roughness': .5})
scene = dict(base, materials=materials, meshes=[ground, dict(ball, material='', face_materials=['glass' if i < count // 2 else 'plain' for i in range(count)]), cube])
path = out / 'volume.rdla'
path.write_text(rdla.scene_text(scene, 160, 90, 2, 0.5, str(out / 'volume.exr')), encoding='utf-8')
done = subprocess.run([str(rt / 'moonray.exe'), '-in', str(path), '-out', str(out / 'volume.exr'), '-exec_mode', 'vectorized'], env=native.environment(rt), capture_output=True, timeout=300)
print(hex(done.returncode & 0xffffffff), (out / 'volume.exr').is_file())
'''


def main():
    version = sys.argv[1]
    root = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(tempfile.mkdtemp(prefix='MoonRayForModo-release-check-'))
    if root.exists():
        shutil.rmtree(root)
    kits = root / 'Kits'
    kits.mkdir(parents=True)
    for name in ('MoonRayForModo-%s-kit.zip' % version, 'MoonRayForModo-%s-windows-runtime.zip' % version):
        zipfile.ZipFile(ROOT / 'dist' / ('release-' + version) / name).extractall(kits)
    kit = kits / 'MoonRayForModo'
    runtime = kit / 'runtime'
    failed = []

    def check(what, passed, detail=''):
        print('%-52s %s %s' % (what, 'ok' if passed else 'FAILED', detail), flush=True)
        if not passed:
            failed.append(what)

    missing = [name for name in NEED if not (kit / name).is_file()]
    check('the kit holds what it needs', not missing, ', '.join(missing))
    held = (kit / 'index.cfg').read_text(encoding='utf-8').split('<configuration', 1)[1].split('version="', 1)[1].split('"', 1)[0]
    check('the kit says it is %s' % version, held == version, held)
    check('Import MoonRay Scene is in the menu', 'moonray.rdl.import' in (kit / 'layout.cfg').read_text(encoding='utf-8'))
    # A bare environment: nothing of this machine's toolchain or project on the path.
    bare = {key: os.environ[key] for key in ('SystemRoot', 'SystemDrive', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE') if key in os.environ}
    bare['PATH'] = os.path.join(os.environ['SystemRoot'], 'System32')
    work = root / 'work'
    work.mkdir()
    shutil.copy(ROOT / 'upstream/openmoonray/testdata/sphere.rdla', work / 'sphere.rdla')
    for mode in ('xpu', 'vectorized'):
        done = subprocess.run([str(runtime / 'moonray.exe'), '-in', 'sphere.rdla', '-out', mode + '.exr', '-exec_mode', mode, '-size', '160', '160', '-info'],
                              cwd=str(work), env=bare, capture_output=True, timeout=300)
        log = done.stdout.decode(errors='replace') + done.stderr.decode(errors='replace')
        check('MoonRay renders, %s' % mode, done.returncode == 0 and (work / (mode + '.exr')).is_file() and (mode != 'xpu' or 'GPU: Setup complete' in log),
              'fell back to the CPU' if 'alling back' in log else '')
    done = subprocess.run([str(runtime / 'modo_rdl_import.exe'), 'sphere.rdla', str(runtime)], cwd=str(work), env=dict(bare, PATH=str(runtime) + ';' + bare['PATH']), capture_output=True, timeout=120)
    at = done.stdout.rfind(b'@@MODO_RDL_JSON')
    check('the scene reader reads a scene', done.returncode == 0 and at >= 0 and len(json.loads(done.stdout[at + 15:])['objects']) > 0)
    # What reads a VDB file for MoonLightIPR: it writes a small grid of its own, then reads it back as a block.
    reads = dict(bare, PATH=str(runtime) + ';' + bare['PATH'])
    made = subprocess.run([str(runtime / 'modo_vdb_grid.exe'), '--ball', 'ball.vdb'], cwd=str(work), env=reads, capture_output=True, timeout=120)
    done = subprocess.run([str(runtime / 'modo_vdb_grid.exe'), 'ball.vdb', 'density', '32', 'ball.mlv'], cwd=str(work), env=reads, capture_output=True, timeout=120)
    check('the VDB reader reads a grid', made.returncode == 0 and done.returncode == 0 and (work / 'ball.mlv').is_file() and (work / 'ball.mlv').read_bytes()[:4] == b'MLV1',
          (made.stderr + done.stderr).decode(errors='replace').strip()[-200:])
    # What grows hair: from the unpacked kit's own module, with the unpacked runtime's program.
    grown = subprocess.run([sys.executable, '-c', 'import sys;sys.path.insert(0,sys.argv[1]);from moonray_modo import hair_native;'
                            'made=hair_native.grow([[(0,0,0),(0,.1,0),(0,.2,0)]],None,0,25,.01,.5,.1,1,None,sys.argv[2]);print(len(made[0]) if made else "none")',
                            str(kit / 'python'), str(runtime)], env=dict(os.environ, MOONRAY_MODO_RUNTIME=''), capture_output=True, text=True, timeout=120)
    check('the hair grower grows hair', grown.stdout.strip() == '25', grown.stdout.strip() or grown.stderr.strip()[-200:])
    session = subprocess.Popen([str(runtime / 'moonlightipr' / 'moonlightipr_session.exe'), str(runtime / 'moonlightipr' / 'MoonLightIPRKernel.ptx')], cwd=str(work),
                               env=dict(bare, PATH=str(runtime / 'moonlightipr') + ';' + bare['PATH']), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(6)
    alive = session.poll() is None
    try:
        session.stdin.write(b'quit\n')
        session.stdin.flush()
        session.wait(timeout=15)
    except Exception:
        session.kill()
    check('the MoonLightIPR session starts and quits', alive and session.returncode == 0)
    done = subprocess.run([sys.executable, '-c', 'import sys;sys.path.insert(0,sys.argv[1]);from moonray_modo import native;print(native.default_runtime())', str(kit / 'python')],
                          env=dict(os.environ, MOONRAY_MODO_RUNTIME=''), capture_output=True, text=True)
    check('the kit finds its own runtime', Path(done.stdout.strip() or '.').resolve() == runtime.resolve(), done.stdout.strip())
    done = subprocess.run([sys.executable, '-c', VOLUME, str(kit), str(ROOT / 'tools'), str(work)], env=dict(os.environ, MOONRAY_MODO_RUNTIME=''), capture_output=True, text=True, timeout=400)
    check('a volume on one part of a mesh renders', done.stdout.strip() == '0x0 True', done.stdout.strip() or done.stderr.strip()[-200:])
    print('unpacked in', root)
    if failed:
        raise SystemExit('%d check(s) failed' % len(failed))


if __name__ == '__main__':
    main()
