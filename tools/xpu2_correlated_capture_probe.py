"""Control-render validation of native sampler/Lambert event correlation."""
import argparse,hashlib,json,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import inventory,verify,digest_file
from xpu2.images import read_rgba,compare_rgba
from xpu2.correlated_state import decode,match_surface
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--surface-reference',required=True,type=Path);p.add_argument('--build',required=True,type=Path);p.add_argument('--scene-reference',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();build=a.build.resolve();prior=a.scene_reference.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'Same-call sampler/Lambert capture, matched to repeatable surface fixture; no native resumption','runs':[]}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text())
        if manifest['status']!='built':raise ValueError('Incomplete capture build')
        dependencies=[Path(__file__).resolve(),ROOT/'xpu2/correlated_context.ispc.inc',ROOT/'xpu2/correlated_bridge.cc',ROOT/'xpu2/correlated_state.py',ROOT/'xpu2/images.py']
        hashes={str(f):digest_file(f) for f in dependencies}
        for f,h in manifest['source_hashes'].items():
            if digest_file(Path(f))!=h:raise ValueError('Capture source changed after build')
        surface_meta=json.loads((a.surface_reference/'report.json').read_text())
        if surface_meta['status']!='passed':raise ValueError('Unverified surface fixture')
        surface_run=next(r for r in surface_meta['runs'] if r['label']=='capture')
        surfaces=surface_run['states']
        report['surface_reference_sha256']=digest_file(a.surface_reference/'report.json')
        report.update(build_manifest_sha256=digest_file(build/'build-inputs.json'),source_hashes=hashes,gpu=gpu_identity())
        locks={str(build/label):inventory(build/label) for label in ('control','trace')}
        for label in ('control','trace'):
            for module in ('librendering_rndr.dll','librendering_shading.dll'):
                if digest_file(build/label/module)!=manifest[label+'_'+module]:raise ValueError('Capture DLL drift')
            if digest_file(build/label/'xpu2_capture.dll')!=manifest['bridge_sha256']:raise ValueError('Bridge DLL drift')
        previous=json.loads((prior/'report.json').read_text())
        if digest_file(prior/'scene.rdla')!=previous['diagnostic_scene_sha256']:raise ValueError('Reference scene drift')
        text=(prior/'scene.rdla').read_text(encoding='utf-8')+'\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0 }\n'
        images={};captures={}
        for label,runtime,enabled in [('control',build/'control',False),('disabled',build/'trace',False),('capture',build/'trace',True),('repeat',build/'trace',True)]:
            folder=out/label;folder.mkdir();scene=folder/'scene.rdla';scene.write_text(text,encoding='utf-8');env=environment(runtime,folder)
            env.pop('XPU2_CORRELATED_CAPTURE',None)
            if enabled:env['XPU2_CORRELATED_CAPTURE']=str(folder/'correlated.bin')
            print('Native correlated '+label,flush=True)
            with (folder/'render.log').open('w',encoding='utf-8') as f:
                done=subprocess.run([str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],env=env,cwd=folder,stdout=f,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
            stats=(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else ''
            checks=successful('xpu',1,done.returncode,(folder/'render.log').read_text(errors='replace'),stats,(folder/'beauty.exr').exists())
            if not checks['passed']:raise ValueError('Native render failed '+label)
            image=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env);images[label]=image
            row={'label':label,'render':checks,'scene_sha256':digest_file(scene)}
            if label!='control':
                comparison=compare_rgba(images['control'],image);row['image_comparison']=comparison
                def bits(v):return b''.join(struct.pack('<%df'%len(v['channels'][c]),*v['channels'][c]) for c in 'RGBA')
                row['bitwise_equal']=bits(images['control'])==bits(image)
                if comparison['status']!='passed' or not row['bitwise_equal']:raise ValueError('Capture changed image '+label)
            if enabled:
                raw=(folder/'correlated.bin').read_bytes();rows=decode(raw);captures[label]=raw
                row.update(capture_sha256=digest_file(folder/'correlated.bin'),records=len(rows),states=rows,surface_matches=match_surface(rows,surfaces))
                if digest_file(scene)!=surface_run['scene_sha256']:raise ValueError('Correlated and surface scenes differ')
                if {r['metadata'][0] for r in rows}!={(77<<16)|96,(96<<16)|132}:raise ValueError('Missing selected pixel')
            elif (folder/'correlated.bin').exists():raise ValueError('Disabled capture emitted state')
            report['runs'].append(row)
        if captures['capture']!=captures['repeat']:raise ValueError('Correlated sampler/Lambert capture did not repeat bitwise')
        for path,lock in locks.items():verify(Path(path),lock)
        if hashes!={str(f):digest_file(f) for f in dependencies} or report['gpu']!=gpu_identity():raise ValueError('Source/GPU drift')
        report.update(status='passed',capture_repeat_bitwise=True,runtime_inventory_sha256={k:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest() for k,v in locks.items()})
    except Exception as e:report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
