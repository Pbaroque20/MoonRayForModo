"""Fetch pinned official NVIDIA components locally; never install a display driver."""
from pathlib import Path
import hashlib,json,subprocess,urllib.request,zipfile
root=Path(__file__).resolve().parents[1];target=root/'toolchain/xpu';target.mkdir(parents=True,exist_ok=True)
manifest=json.loads((root/'patches/native-windows/xpu-sources.json').read_text())
for name,entry in manifest['components'].items():
    archive=target/Path(entry['relative_path']).name
    if not archive.exists(): urllib.request.urlretrieve('https://developer.download.nvidia.com/compute/cuda/redist/'+entry['relative_path'],archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=entry['sha256']: raise ValueError('Checksum mismatch: '+name)
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist(): (target/info.filename).resolve().relative_to(target.resolve())
        z.extractall(target)
    print(name+' verified',flush=True)
optix=manifest['optix'];checkout=target/'optix-dev'
if not checkout.exists(): subprocess.run(['git','clone','--depth','1','--branch',optix['tag'],optix['url'],str(checkout)],check=True)
if subprocess.check_output(['git','-C',str(checkout),'rev-parse','HEAD'],text=True).strip()!=optix['commit']:
    raise ValueError('OptiX checkout differs from pinned revision')
print('XPU build dependencies ready; NVIDIA license files retained in component folders.')
