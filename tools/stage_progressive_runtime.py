"""Stage a new preview executable over a verified existing runtime, without changing DSOs."""
import argparse,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base',type=Path);parser.add_argument('destination',type=Path)
    args=parser.parse_args();base=args.base.resolve();target=args.destination.resolve()
    target.relative_to((root/'runtime').resolve())
    if target.exists():raise ValueError('Use a new runtime directory')
    manifest=json.loads((base/'build-manifest.json').read_text(encoding='utf-8'))
    for name,entry in manifest.items():
        source=(base/name).resolve();source.relative_to(base)
        if digest(source)!=entry['sha256']:raise ValueError('Base hash mismatch: '+name)
    executable=root/'build/native-renderer-avx/bin/moonray.exe'
    if b'Modo native progressive preview' not in executable.read_bytes():raise ValueError('Not a progressive build')
    listing=subprocess.check_output([str(root/'toolchain/msys64/ucrt64/bin/objdump.exe'),'-p',str(executable)],text=True,errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
    for name in re.findall(r'DLL Name:\s*(\S+)',listing):
        if not (base/name).is_file() and not (Path(os.environ['SystemRoot'])/'System32'/name).is_file() and not name.lower().startswith(('api-ms-','ext-ms-')):
            raise ValueError('New executable dependency missing from base: '+name)
    imports={};current=None
    for line in listing.splitlines():
        match=re.search(r'DLL Name:\s*(\S+)',line)
        if match:current=match[1];imports[current]=[]
        match=re.match(r'\s*[0-9a-f]+\s+<none>\s+[0-9a-f]+\s+(\S+)',line)
        if match and current:imports[current].append(match[1])
    for dll,names in imports.items():
        if not (base/dll).is_file():continue
        exports=subprocess.check_output([str(root/'toolchain/msys64/ucrt64/bin/objdump.exe'),'-p',str(base/dll)],text=True,errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
        missing=set(names)-set(exports.split())
        if missing:raise ValueError('Unresolved bundled imports: '+dll+' '+str(missing))
    shutil.copytree(base,target,ignore=shutil.ignore_patterns('validated-render.json'))
    shutil.copy2(executable,target/'moonray.exe')
    manifest['moonray.exe']={'source':str(executable),'sha256':digest(executable)}
    capability=target/'modo-session.json';value=json.loads(capability.read_text(encoding='utf-8'))
    value.update(progressive_preview=True,executable_sha256=digest(executable));capability.write_text(json.dumps(value,indent=2),encoding='utf-8')
    manifest[capability.name]={'source':str(capability),'sha256':digest(capability)}
    crypto=target/'modo-crypto-categories.json'
    if crypto.exists():
        value=json.loads(crypto.read_text(encoding='utf-8'));value['sha256']['moonray.exe']=digest(executable);value['render_validated']=False
        crypto.write_text(json.dumps(value,indent=2),encoding='utf-8');manifest[crypto.name]={'source':str(crypto),'sha256':digest(crypto)}
    (target/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Staged progressive executable with unchanged base shaders and DLLs:',target)
if __name__=='__main__':main()
