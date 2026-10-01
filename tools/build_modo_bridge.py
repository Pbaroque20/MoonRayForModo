"""Build the native preview adapter using the user-supplied Modo SDK."""
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[1]
sdk=root/'upstream/modo-sdk-661446/LXSDK_661446'
compiler=root/'toolchain/msys64/ucrt64/bin/g++.exe'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=root/'build/modo-bridge')
folder=parser.parse_args().output_dir.resolve(); folder.mkdir(parents=True,exist_ok=True)
env=os.environ.copy(); env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
test_command=[str(compiler),'-std=c++17','-O2','-static',
    str(root/'native-modo/test_image_resample.cpp'),'-o',str(folder/'test_image_resample.exe')]
subprocess.run(test_command,env=env,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
subprocess.run([str(folder/'test_image_resample.exe')],env=env,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
command=[str(compiler),'-std=c++17','-shared','-O2','-D_WIN32','-D_WIN64','-DWIN32',
    '-static','-static-libgcc','-static-libstdc++','-I'+str(sdk/'include'),
    str(root/'native-modo/preview_bridge.cpp'),str(sdk/'common/cwrap.cpp'),str(sdk/'common/util.cpp'),
    '-o',str(folder/'MoonRayPreview.lx')]
with (folder/'build.log').open('w') as log:
    result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
print((folder/'build.log').read_text(errors='replace')[-7000:])
if result.returncode: raise SystemExit(result.returncode)
(folder/'build.json').write_text(json.dumps({'sdk_build':661446,
    'image_scaling_tests_passed':True,
    'sdk_version_sha256':hashlib.sha256((sdk/'include/lxversion.h').read_bytes()).hexdigest(),
    'plugin_sha256':hashlib.sha256((folder/'MoonRayPreview.lx').read_bytes()).hexdigest()},indent=2))
print('Built native Modo preview adapter')
