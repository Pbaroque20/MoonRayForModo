"""Control-render validation of fieldwise native surface-state capture."""
import argparse,hashlib,json,struct,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import inventory,verify,digest_file
from xpu2.images import read_rgba,compare_rgba
from xpu2.surface_state import decode
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',required=True,type=Path);p.add_argument('--scene-reference',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();build=a.build.resolve();prior=a.scene_reference.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'Native numeric surface snapshot after parent-ray release; no state restoration or asynchronous native integration','runs':[]}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text())
        if manifest['status']!='built':raise ValueError('Incomplete capture build')
        dependencies=[Path(__file__).resolve(),ROOT/'xpu2/native_surface_capture.h',ROOT/'xpu2/surface_state.py',ROOT/'xpu2/images.py']
        hashes={str(f):digest_file(f) for f in dependencies}
        if hashes[str(ROOT/'xpu2/native_surface_capture.h')]!=manifest['header_sha256']:raise ValueError('Capture source changed after build')
        report.update(build_manifest_sha256=digest_file(build/'build-inputs.json'),source_hashes=hashes,gpu=gpu_identity())
        locks={str(build/label):inventory(build/label) for label in ('control','trace')}
        for label in ('control','trace'):
            if digest_file(build/label/'librendering_rndr.dll')!=manifest[label+'_dll_sha256']:raise ValueError('Capture DLL drift')
        previous=json.loads((prior/'report.json').read_text())
        if digest_file(prior/'scene.rdla')!=previous['diagnostic_scene_sha256']:raise ValueError('Reference scene drift')
        text=(prior/'scene.rdla').read_text(encoding='utf-8')+'\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0 }\n'
        images={};captures={}
        for label,runtime,enabled in [('control',build/'control',False),('disabled',build/'trace',False),('capture',build/'trace',True),('repeat',build/'trace',True)]:
            folder=out/label;folder.mkdir();scene=folder/'scene.rdla';scene.write_text(text,encoding='utf-8');env=environment(runtime,folder)
            env.pop('XPU2_SURFACE_CAPTURE',None)
            if enabled:env['XPU2_SURFACE_CAPTURE']=str(folder/'surface.bin')
            print('Native surface '+label,flush=True)
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
                raw=(folder/'surface.bin').read_bytes();rows=decode(raw);captures[label]=raw
                row.update(capture_sha256=digest_file(folder/'surface.bin'),records=len(rows),states=rows)
                if {r['ids']['pixel'] for r in rows}!={(77<<16)|96,(96<<16)|132}:raise ValueError('Missing selected pixel')
            elif (folder/'surface.bin').exists():raise ValueError('Disabled capture emitted state')
            report['runs'].append(row)
        if captures['capture']!=captures['repeat']:raise ValueError('Native surface capture did not repeat bitwise')
        for path,lock in locks.items():verify(Path(path),lock)
        if hashes!={str(f):digest_file(f) for f in dependencies} or report['gpu']!=gpu_identity():raise ValueError('Source/GPU drift')
        report.update(status='passed',capture_repeat_bitwise=True,runtime_inventory_sha256={k:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest() for k,v in locks.items()})
    except Exception as e:report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
