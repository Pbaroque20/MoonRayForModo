"""Build isolated sampler/Lambert same-call capture from frozen link inputs."""
import argparse,json,os,shlex,shutil,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','pbr-build','shading-build','output'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();source=a.source.resolve();runtime=a.runtime.resolve();out=a.output.resolve()
    if out.is_relative_to(source) or out.is_relative_to(runtime):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ispc=compiler.with_name('ispc.exe')
    env=dict(os.environ);env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    def run(args,label,stdout=None):
        with (out/(label+'.log')).open('w',encoding='utf-8') as log:
            if stdout:
                with stdout.open('w',encoding='utf-8') as f:done=subprocess.run(args,env=env,stdout=f,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            else:done=subprocess.run(args,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
        if done.returncode:raise RuntimeError(label+' failed')
    fragments=[ROOT/'xpu2/correlated_context.ispc.inc',ROOT/'xpu2/correlated_bridge.cc',ROOT/'xpu2/native_lambert_hook.ispc.inc']
    identities={str(f):sha(f) for f in fragments}
    bridge=out/'bridge.cc';bridge.write_bytes(fragments[1].read_bytes())
    flags=['-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off']
    run([str(compiler),*flags,'-E',str(bridge),'-o',str(out/'bridge.ii')],'bridge-preprocess')
    dll=out/'xpu2_capture.dll';lib=out/'libxpu2_capture.dll.a'
    run([str(compiler),*flags,str(out/'bridge.ii'),'-shared','-Wl,--out-implib,'+str(lib),'-o',str(dll)],'bridge-compile')
    ninja=(source/'build/native-renderer-avx/build.ninja').read_text(encoding='utf-8')
    originals={}
    for name,relative in [('sampler','pbr/integrator/PathIntegratorUtil.ispc'),('lambert','shading/ispc/bsdf/BsdfLambert.ispc')]:
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering'/relative
        text=original.read_text(encoding='utf-8');originals[str(original)]=sha(original)
        if name=='sampler':
            text='extern "C" void xpu2SetContext(uniform int words[], uniform int mask);\nextern "C" void xpu2ClearContext();\n'+text
            anchor='            getSample(bsdfSamples, bsdfSample, pv.nonMirrorDepth, *pbrTls->mFs);'
            if text.count(anchor)!=1:raise ValueError('Unknown sample draw')
            text=text.replace(anchor,'            varying uint32_t xpu2Before=bsdfSamples.mSampleNumber;\n'+anchor)
            anchor='            bool isValid = BsdfSampler_sample(pbrTls, &bSampler, lobeIndex,\n                    bsdfSample[0], bsdfSample[1], bsmp[s]);'
            if text.count(anchor)!=1:raise ValueError('Unknown BSDF dispatch')
            text=text.replace(anchor,fragments[0].read_text(encoding='utf-8')+anchor+'\n            xpu2ClearContext();')
        else:
            text='extern "C" void xpu2CorrelatedLambert(uniform float input[], uniform float output[], uniform int lanes[], uniform int count);\n'+text
            anchor='    return LambertBsdfLobe_eval(lobe, slice, wi, &pdf);'
            if text.count(anchor)!=1:raise ValueError('Unknown Lambert return')
            hook=fragments[2].read_text(encoding='utf-8').replace('    xpu2NativeLambert(input, output, count);','    xpu2CorrelatedLambert(input, output, lanes, count);')
            text=text.replace(anchor,hook)
        code=out/(name+'.ispc');code.write_text(text,encoding='utf-8')
        stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and original.stem+'.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
        variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
        ff=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
        if '--opt=force-aligned-memory' in ff:ff.remove('--opt=force-aligned-memory')
        ff+=['-I'+str(original.parent)]
        print('Compiling '+name+' correlation',flush=True)
        run([str(ispc),*ff,'-E',str(code)],name+'-preprocess',out/(name+'.pp'))
        run([str(ispc),*ff,str(code),'--emit-obj','-o',str(out/(name+'.obj'))],name+'-compile')
        run([str(ispc),*ff,'-E',str(code)],name+'-recheck',out/(name+'-recheck.pp'))
        if sha(out/(name+'.pp'))!=sha(out/(name+'-recheck.pp')):raise ValueError('Header drift')
    manifest={'status':'incomplete','scope':'Retained-object two-DLL capture; no asynchronous integration','runtime':str(runtime),'source_hashes':identities,'original_hashes':originals,'inputs':{},'compiler_sha256':sha(compiler),'ispc_sha256':sha(ispc),'bridge_sha256':sha(dll)}
    for label in ('control','trace'):
        shutil.copytree(runtime,out/label);shutil.copy2(dll,out/label/dll.name)
    for module,prior,replacement,replname in [('librendering_rndr.dll',a.pbr_build.resolve(),'PathIntegratorUtil.ispc.obj','sampler'),('librendering_shading.dll',a.shading_build.resolve(),'BsdfLambert.ispc.obj','lambert')]:
        prior_manifest=json.loads((prior/'build-inputs.json').read_text())
        if prior_manifest['status']!='built':raise ValueError('Prior link inputs incomplete')
        inputs=out/module;inputs.mkdir();frozen=[];records=[];index=None;mapping={}
        for item in prior_manifest['inputs']:
            old=prior/item['copy'];dest=inputs/old.name
            if sha(old)!=item['sha256']:raise ValueError('Retained object drift')
            shutil.copy2(old,dest)
            if sha(dest)!=item['sha256']:raise ValueError('Input copy mismatch')
            if Path(item['path']).name==replacement:index=len(frozen)
            mapping[str(old.resolve())]=str(dest)
            frozen.append(str(dest));records.append({'copy':str(dest.relative_to(out)),'sha256':sha(dest),'original':item['path']})
        if index is None:raise ValueError('Missing replacement object')
        manifest['inputs'][module]=records
        replacement_path=frozen[index]
        old_rsp=shlex.split((prior/'control.rsp').read_text())
        frozen=[]
        for arg in old_rsp:
            if arg.startswith('-l'):frozen.append(arg)
            elif arg.startswith('-'):raise ValueError('Unhandled retained link flag '+arg)
            else:frozen.append(mapping[str(Path(arg).resolve())])
        index=frozen.index(replacement_path)
        manifest.setdefault('link_flags',{})[module]=[v for v in frozen if v.startswith('-')]
        for label in ('control','trace'):
            args=frozen.copy()
            if label=='trace':args[index]=str(out/(replname+'.obj'));args.append(str(lib))
            rsp=out/(module+'-'+label+'.rsp');rsp.write_text('\n'.join('"'+v.replace('\\','/')+'"' for v in args),encoding='utf-8')
            print('Linking '+label+' '+module,flush=True)
            run([str(compiler),'-O3','-DNDEBUG','-shared','-o',str(out/label/module),'@'+str(rsp)],module+'-'+label)
            manifest[label+'_'+module]=sha(out/label/module)
    if identities!={str(f):sha(f) for f in fragments} or any(sha(Path(f))!=v for f,v in originals.items()):raise ValueError('Source drift')
    manifest['preprocessed_sha256']={name:sha(out/name) for name in ('bridge.ii','sampler.pp','lambert.pp')}
    manifest['status']='built';(out/'build-inputs.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
