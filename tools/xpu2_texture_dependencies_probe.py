"""Validate native RDL texture dependencies through background OIIO decoding; no render."""
import argparse,json,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2_baseline import environment
from xpu2_rdl_index_probe import block

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','fixtures','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();source,runtime,fixtures,out=(getattr(a,k).resolve() for k in ('source','runtime','fixtures','output'))
    if any(out.is_relative_to(v) for v in (source,runtime,fixtures)):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',scope='Native RDL metadata dependency and background decoded-byte validation; no rendered scene or speed measurement')
    try:
        prior=json.loads((fixtures/'report.json').read_text());assert prior['status']=='passed'
        fixture_hashes={name:digest_file(fixtures/name) for name in ('rgba.tx','gray.tx')}
        if any(h!=prior['fixture_hashes'][name] for name,h in fixture_hashes.items()):raise ValueError('Fixture drift')
        verify(runtime,prior['runtime_inventory']);locked=inventory(runtime)
        build=source/'build/native-avx';prefix=source/'toolchain/msys64/ucrt64';compiler=prefix/'bin/g++.exe'
        ninja=(build/'build.ninja').read_text(encoding='utf-8');comp=block(ninja,'build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:');link=block(ninja,'build bin/rdl2_print.exe:')
        flags=shlex.split(' '.join(comp[k] for k in ('DEFINES','FLAGS','INCLUDES')))+['-I'+str(prefix/'include'),'-fno-fast-math']
        libs=[str((build/v).resolve()) if not v.startswith('-') else v for v in shlex.split(link['LINK_LIBRARIES'])]+[str(prefix/'lib'/v) for v in ('libOpenImageIO.dll.a','libOpenImageIO_Util.dll.a')]
        files=[ROOT/'xpu2'/n for n in ('indexed_scene.h','persistent_map.h','rdl_scene_index.h','texture_cache.h','texture_residency.h','texture_dependencies.h','rdl_texture_dependencies.h','rdl_texture_dependencies_probe.cc','texture_async.h','texture_oiio_loader.h')]+[Path(__file__).resolve(),ROOT/'tools/xpu2_rdl_index_probe.py',compiler]
        files += [Path(v) for v in libs if not v.startswith('-')]
        hashes={str(f):digest_file(f) for f in files}
        for name in ('libOpenImageIO-3.1.dll','libOpenImageIO_Util-3.1.dll'):
            if digest_file(prefix/'bin'/name)!=digest_file(runtime/name):raise ValueError('OIIO runtime mismatch')
        def run(label,command,env):
            print(label,flush=True);r=subprocess.run([str(v) for v in command],env=env,cwd=out,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
            if r.returncode:raise ValueError(label+' failed: '+r.stderr[-2500:])
            return r.stdout
        exe,pp=out/'dependencies.exe',out/'dependencies.ii';env=environment(compiler.parent,out)
        run('preprocess',[compiler,*flags,'-E',ROOT/'xpu2/rdl_texture_dependencies_probe.cc','-o',pp],env)
        run('compile',[compiler,*flags,pp,'-o',exe,*libs],env)
        env=environment(runtime,out);native=json.loads(run('probe',[exe,env['RDL2_DSO_PATH'],fixtures],env))
        if not native.get('passed') or native.get('native_stages')!=8 or native.get('background_tiles')!=3:raise ValueError('Native coverage incomplete')
        verify(runtime,locked)
        if hashes!={str(f):digest_file(f) for f in files} or fixture_hashes!={n:digest_file(fixtures/n) for n in fixture_hashes}:raise ValueError('Source/fixture drift')
        report.update(status='passed',native=native,source_hashes=hashes,fixture_hashes=fixture_hashes,executable_sha256=digest_file(exe),preprocessed_sha256=digest_file(pp))
    except Exception as e:report['error']=str(e)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
