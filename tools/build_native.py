"""Native Windows/AVX source-build experiment, with reproducible command logs."""
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BIN = ROOT / 'toolchain/msys64/ucrt64/bin'
renderer = '--renderer' in sys.argv
scene = '--scene' in sys.argv or renderer
BUILD = ROOT / ('build/native-renderer-avx' if renderer else 'build/native-avx')
env = os.environ.copy()
env['PATH'] = os.pathsep.join([str(BIN), str(BUILD / 'bin'), str(BUILD / 'log4cplus/bin'), env.get('PATH', '')])
for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
    env.pop(key, None)
BUILD.mkdir(parents=True, exist_ok=True)

def run(args, name):
    with (BUILD / (name + '.log')).open('w', encoding='utf-8') as log:
        log.write(subprocess.list2cmdline([str(x) for x in args]) + '\n')
        log.flush()
        completed = subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
    output = (BUILD / (name + '.log')).read_text(encoding='utf-8', errors='replace')
    errors = [line for line in output.splitlines() if 'error:' in line or 'Error ' in line or 'FAILED:' in line]
    print('\n'.join(errors[:25]) if errors else output[-3000:], flush=True)
    if completed.returncode:
        raise SystemExit(completed.returncode)

if renderer:
    run([sys.executable, ROOT / 'tools/port_crypto_categories.py'], 'port-crypto-categories')
    run([sys.executable, ROOT / 'tools/port_instance_motion.py'], 'port-instance-motion')
    run([sys.executable, ROOT / 'tools/port_persistent.py'], 'port-persistent')
    run([sys.executable, ROOT / 'tools/port_buckets.py'], 'port-buckets')

configure_args = [BIN / 'cmake.exe', '-S', ROOT / 'native-port', '-B', BUILD, '-G', 'Ninja',
     '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_C_COMPILER=' + str(BIN / 'gcc.exe'),
     '-DCMAKE_CXX_COMPILER=' + str(BIN / 'g++.exe'), '-DCMAKE_ISPC_COMPILER=' + str(BIN / 'ispc.exe'),
     '-DCMAKE_MAKE_PROGRAM=' + str(BIN / 'ninja.exe'),
     '-DCMAKE_RC_FLAGS=--preprocessor=gcc --preprocessor-arg=-E --preprocessor-arg=-xc --preprocessor-arg=-DRC_INVOKED',
     '-DBUILD_SCENE_RDL2=' + ('ON' if scene else 'OFF'),
     '-DBUILD_MOONRAY=' + ('ON' if renderer else 'OFF'),
     '-DMOONRAY_WINDOWS_XPU=' + ('ON' if '--xpu' in sys.argv else 'OFF'),
     '-DCMAKE_POLICY_VERSION_MINIMUM=3.5']
cache=(BUILD/'CMakeCache.txt').read_text(encoding='utf-8') if (BUILD/'CMakeCache.txt').is_file() else ''
xpu_matches=('MOONRAY_WINDOWS_XPU:BOOL=ON' in cache)==('--xpu' in sys.argv)
if '--build-only' not in sys.argv or not (BUILD / 'build.ninja').exists() or not xpu_matches:
    run(configure_args, 'configure')
targets = ['moonray_avx_probe', 'moonray_ispc_mask_probe'] + (['rdl2_print', 'moonray_codec_probe', 'moonray_platform_probe'] if scene else [])
if renderer:
    targets.extend(['moonray_desktop_renderer' if '--dsos' in sys.argv else 'moonray', 'moonray_desktop_probe', 'moonray_embree_probe', 'moonray_bucket_probe'])
jobs = os.environ.get('MOONRAY_BUILD_JOBS', '8')
run([BIN / 'cmake.exe', '--build', BUILD, '--parallel', jobs, '--target'] + targets + ['--', '-k', '20'], 'compile')
if '--skip-tests' not in sys.argv:
    run([BIN / 'ctest.exe', '--test-dir', BUILD, '--output-on-failure'], 'test')
else:
    print('Build completed; tests explicitly deferred.', flush=True)
