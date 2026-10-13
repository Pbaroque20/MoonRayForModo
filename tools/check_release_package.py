"""Unpack a packaged release into an empty folder and run it from there, with nothing of this machine on the path.

Usage: check_release_package.py <version> [folder to unpack into]
Pass --no-render to check packaging and asset discovery without starting a renderer.
Checks that the three ZIPs merge into one kit with what it needs, that MoonRay renders from the unpacked runtime in GPU
and CPU modes with a bare environment, that the scene reader, the VDB reader, the hair grower and the MoonLightIPR session start, that the kit finds its
own runtime, and that the unpacked kit writes a scene MoonRay accepts for a mesh one part of which holds a volume."""
import argparse
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
NEED = ['index.cfg', 'layout.cfg', 'bin/MoonRayGeometry.lx', 'runtime/moonray.exe', 'runtime/modo_rdl_import.exe', 'runtime/modo_vdb_grid.exe', 'runtime/modo_hair_grow.exe', 'runtime/denoise.exe', 'runtime/oiiotool.exe', 'runtime/modo_fur_grow.exe', 'runtime/ModoFurGeometry.dll', 'runtime/ModoFurGeometry.so.proxy', 'runtime/ModoTextureMap.so',
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


def unpack(archive_path, destination):
    """Extract only relative kit paths; an archive cannot escape the disposable installation."""
    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            name=info.filename
            path=Path(name)
            if (path.is_absolute() or '..' in path.parts or ':' in name or '\\' in name
                    or not path.parts or path.parts[0]!='MoonRayForModo'
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ValueError('Unsafe release entry: '+name)
            (destination/path).resolve().relative_to(destination.resolve())
        bad=archive.testzip()
        if bad:raise ValueError('Corrupt archive member: '+bad)
        archive.extractall(destination)
        return [info.filename for info in archive.infolist() if not info.is_dir()]


LIBRARY = r"""
import json,sys
from pathlib import Path
kit=Path(sys.argv[1]);sys.path.insert(0,str(kit/'python'))
from moonray_modo import asset_library
folder=asset_library.bundled()
entries=[row for batch in asset_library.scan([folder]) for row in batch]
scenes=folder/'MoonRay scenes'
assert scenes.is_dir(), 'Content archive was not merged into the kit'
expected=sorted(scenes.glob('*/scene.rdla'))
assert expected, 'Content archive has no example scenes'
indexed={str(Path(row['path']).resolve()) for row in entries if row.get('path')}
for scene in expected:
    assert str(scene.resolve()) in indexed, 'Library did not find '+str(scene)
    assert scene.with_suffix('.rdlb').is_file(), 'Missing paired scene.rdlb: '+str(scene)
    assert (scene.parent/'LICENSE.txt').is_file(), 'Missing scene license: '+str(scene)
print(json.dumps({'scenes':len(expected),'indexed_assets':len(entries),'library':str(folder)}))
"""


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('folder',nargs='?',type=Path)
    parser.add_argument('--no-render',action='store_true')
    args=parser.parse_args();version=args.version
    root=args.folder.resolve() if args.folder else Path(tempfile.mkdtemp(prefix='MoonRayForModo-release-check-'))
    if root.exists() and any(root.iterdir()):
        raise ValueError('Choose an empty or new check folder; existing files are never removed: '+str(root))
    kits=root/'Kits';kits.mkdir(parents=True)
    release=ROOT/'dist'/('release-'+version)
    for suffix in ('kit','windows-runtime','content'):
        unpack(release/('MoonRayForModo-%s-%s.zip'%(version,suffix)),kits)
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
    # Import the installed kit's own library code: not the development tree or the original downloads.
    found=subprocess.run([sys.executable,'-c',LIBRARY,str(kit)],capture_output=True,text=True,timeout=120)
    check('the merged content appears in the asset library',found.returncode==0,found.stdout.strip() or found.stderr.strip()[-500:])
    if args.no_render:
        print('Packaging checks only; no render or Modo UI tests run. Unpacked in',root)
        if failed:raise SystemExit('%d check(s) failed'%len(failed))
        return
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
