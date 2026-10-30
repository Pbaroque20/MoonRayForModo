"""Native capture plus owned CPU-worker replay of contribution arithmetic only."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import inventory,verify,digest_file
from xpu2.images import read_rgba,compare_rgba
from xpu2 import contribution_capture
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity
from xpu2_profile_probe import bits,validate_profile,validate_native_overlap


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('source','build','scene-reference','ptx-reference','output'):
        p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();source=a.source.resolve();build=a.build.resolve();out=a.output.resolve();prior=a.scene_reference.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'Owned native pre-clamp contribution arithmetic on CPU workers. No whole-path resumption, GPU/CPU path split or acceleration claim.','renders':[],'replays':[]}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text())
        if manifest['status']!='built' or not manifest.get('contribution_capture'):raise ValueError('Capture build required')
        dependencies=[Path(__file__).resolve(),ROOT/'xpu2/contribution_replay.cc',ROOT/'tools/xpu2_profile_probe.py',ROOT/'xpu2/images.py',ROOT/'tools/xpu2_baseline.py',ROOT/'tools/xpu2_repeatability.py']
        hashes={**manifest['source_hashes'],**manifest['original_hashes'],**{str(f):digest_file(f) for f in dependencies}}
        for file,want in hashes.items():
            if digest_file(Path(file))!=want:raise ValueError('Source drift')
        report.update(source_hashes=hashes,gpu=gpu_identity(),build_manifest_sha256=digest_file(build/'build-inputs.json'))
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';ispc=compiler.with_name('ispc.exe')
        original=source/'upstream/openmoonray/moonray/moonray/lib/rendering/pbr/integrator/PathIntegratorUtil.ispc'
        code=out/'resume.ispc';code.write_text(contribution_capture.kernel(original.read_text()))
        ninja=(source/'build/native-renderer-avx/build.ninja').read_text()
        stanza=next(s for s in ninja.split('\n\n') if s.startswith('build ') and 'PathIntegratorUtil.ispc.obj' in s.splitlines()[0] and 'ISPC_COMPILER' in s.splitlines()[0])
        variables=dict(line.strip().split(' = ',1) for line in stanza.splitlines()[1:] if ' = ' in line)
        flags=shlex.split(' '.join(variables[k] for k in ('DEFINES','INCLUDES','FLAGS')))
        if '--opt=force-aligned-memory' in flags:flags.remove('--opt=force-aligned-memory')
        flags+=['-I'+str(original.parent)]
        env=environment(compiler.parent,out)
        def run(command,label):
            done=subprocess.run(command,env=env,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError(label+' failed')
        run([str(ispc),*flags,'-E',str(code)],'resume-preprocess')
        run([str(ispc),*flags,str(code),'--emit-obj','-o',str(out/'resume.obj')],'resume-compile')
        run([str(ispc),*flags,'-E',str(code)],'resume-recheck')
        if digest_file(out/'resume-preprocess.log')!=digest_file(out/'resume-recheck.log'):raise ValueError('Header drift')
        exe=out/'replay.exe'
        run([str(compiler),'-std=c++17','-O2','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off',str(ROOT/'xpu2/contribution_replay.cc'),str(out/'resume.obj'),'-o',str(exe)],'replay-compile')
        report['replay_build']={f.name:digest_file(f) for f in (compiler,ispc,exe,code,out/'resume.obj',out/'resume-preprocess.log')}
        locks={str(build/label):inventory(build/label) for label in ('control','trace')}
        for label in ('control','trace'):
            for module in ('librendering_rndr.dll','librendering_shading.dll'):
                if digest_file(build/label/module)!=manifest[label+'_'+module]:raise ValueError('Runtime drift')
            if digest_file(build/label/'xpu2_batched.dll')!=manifest['bridge_sha256']:raise ValueError('Bridge drift')
        meta=json.loads((a.ptx_reference/'report.json').read_text());ptx=a.ptx_reference.resolve()/'sampler.ptx'
        if meta['status']!='passed' or digest_file(ptx)!=meta['ptx_sha256']:raise ValueError('Unverified PTX')
        report['ptx_sha256']=digest_file(ptx)
        previous=json.loads((prior/'report.json').read_text())
        if digest_file(prior/'scene.rdla')!=previous['diagnostic_scene_sha256']:raise ValueError('Scene drift')
        text=(prior/'scene.rdla').read_text()+'\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0, ["bsdf_samples"]=3 }\n'
        images={};captures={}
        for label in ('control','disabled','capture','repeat'):
            runtime=build/('control' if label=='control' else 'trace');enabled=label in ('capture','repeat')
            folder=out/label;folder.mkdir();scene=folder/'scene.rdla';scene.write_text(text)
            renv=environment(runtime,folder)
            for key in list(renv):
                if key.startswith('XPU2_'):del renv[key]
            if enabled:renv.update(XPU2_CONTRIBUTION_CAPTURE=str(folder/'contributions.bin'),XPU2_NATIVE_LAMBERT='replace',XPU2_NATIVE_LAMBERT_PTX=str(ptx),XPU2_NATIVE_BATCH_WIDTH='16',XPU2_WINDOW_DISPATCH='1',XPU2_ASYNC_TRANSFERS='1',XPU2_PACKED_READBACK='1',XPU2_SHADER_AUDIT='1',XPU2_NATIVE_LIGHT_OVERLAP='1',XPU2_PROFILE_FILE=str(folder/'profile.json'),XPU2_PROFILE_QUIET='1')
            print('Owned contribution '+label,flush=True)
            with (folder/'render.log').open('w') as log:
                done=subprocess.run([str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],env=renv,cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
            checks=successful('xpu',1,done.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            if not checks['passed']:raise ValueError('Render failed '+label)
            image=read_rgba(runtime,folder/'beauty.exr',folder,'raw',renv);images[label]=image
            row={'label':label,'render':checks,'scene_sha256':digest_file(scene),'rgba_bitwise_equal':bits(image)==bits(images['control'])}
            if not row['rgba_bitwise_equal']:raise ValueError('Capture changed film')
            if enabled:
                profile=json.loads((folder/'profile.json').read_text());validate_profile(profile,'overlap_1');validate_native_overlap(profile,'overlap_1',True);row['profile']=profile
                raw=(folder/'contributions.bin').read_bytes()
                if raw[:4]!=b'XCR1' or (len(raw)-4)%160 or not 1<=(len(raw)-4)//160<=4096:raise ValueError('Invalid capture')
                captures[label]=raw;row.update(capture_sha256=digest_file(folder/'contributions.bin'),records=(len(raw)-4)//160)
            report['renders'].append(row)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if captures['capture']!=captures['repeat']:raise ValueError('Capture is not bitwise repeatable')
        outputs={}
        for mode in ('normal','sentinel'):
            for workers in (1,4):
                for order in ('forward','reverse'):
                    label=f'{mode}-{workers}-{order}';result=out/(label+'.bin')
                    done=subprocess.run([str(exe),str(out/'capture/contributions.bin'),str(workers),order,mode,str(result)],env=env,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
                    (out/(label+'.log')).write_text(done.stdout+done.stderr)
                    if done.returncode:raise ValueError('Owned replay failed '+label)
                    row=json.loads(done.stdout);row.update(label=label,result_sha256=digest_file(result))
                    if not row['passed']:raise ValueError('Replay did not pass')
                    if mode in outputs and outputs[mode]!=row['result_sha256']:raise ValueError('Worker schedule changed result')
                    outputs[mode]=row['result_sha256'];report['replays'].append(row)
        if outputs['normal']==outputs['sentinel']:raise ValueError('Replay inputs ignored')
        report['rejected_payloads']=[]
        raw=captures['capture']
        invalid={'bad_header':b'BAD!'+raw[4:],'truncated':raw[:-1]}
        for name,word,value in [('nonfinite',7,float('nan')),('zero_pdf',7,0.),('unknown_flag',2,2.),('reserved',17,1.)]:
            data=bytearray(raw);struct.pack_into('<f',data,4+32+word*4,value);invalid[name]=data
        for name,data in invalid.items():
            path=out/(name+'.bin');path.write_bytes(data)
            done=subprocess.run([str(exe),str(path),'4','reverse','normal',str(out/(name+'-result.bin'))],env=env,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            if done.returncode!=1 or (out/(name+'-result.bin')).exists():raise ValueError('Invalid payload admitted: '+name)
            report['rejected_payloads'].append({'case':name,'diagnostic':done.stderr.strip()})

        for path,lock in locks.items():verify(Path(path),lock)
        for file,want in hashes.items():
            if digest_file(Path(file))!=want:raise ValueError('Source drift')
        if report['gpu']!=gpu_identity() or digest_file(ptx)!=report['ptx_sha256']:raise ValueError('GPU/PTX drift')
        if digest_file(exe)!=report['replay_build']['replay.exe']:raise ValueError('Replay executable drift')
        report.update(status='passed',capture_repeat_bitwise=True,speedup_established=False)
    except Exception as exc:
        report['error']=str(exc);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
