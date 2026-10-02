"""Small real XPU render; fails on CPU fallback and never opens Modo."""
import argparse,json,re,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla
parser=argparse.ArgumentParser();parser.add_argument('runtime',type=Path);args=parser.parse_args()
runtime=native.find_runtime(args.runtime)
out=root/'test-results'/('xpu-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
scene={'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'focal_mm':50,'film_mm':36},
       'materials':{'red':{'color':[.7,.03,.02],'roughness':.3}},'lights':[],
       'meshes':[{'name':'XPU check','vertices':[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],'faces':[[0,1,2,3]],'material':'red'}]}
source=out/'scene.rdla';image=out/'image.exr';source.write_text(rdla.scene_text(scene,128,128,2,1),encoding='utf-8')
with (out/'render.log').open('w',encoding='utf-8') as log:
    proc=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,image,4,'xpu'),env=native.environment(runtime),cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
text=(out/'render.log').read_text(encoding='utf-8',errors='replace')
report={'runtime':str(runtime),'exit_code':proc.returncode,'image_created':image.is_file() and image.stat().st_size>16,
        'gpu_setup_complete':'GPU: Setup complete' in text,'cpu_fallback':'falling back' in text.lower(),
        'gpu_errors':any(term in text for term in ['optixLaunch() failure','cudaStreamSynchronize() error']),
        'log':str(out/'render.log')}
match=re.search(r'GPU bundled intersection ray utilization\s*=\s*([0-9.]+)%',text)
report['gpu_intersection_percent']=float(match.group(1)) if match else 0
report['passed']=report['gpu_intersection_percent']>0 and report['exit_code']==0 and report['image_created'] and report['gpu_setup_complete'] and not report['cpu_fallback'] and not report['gpu_errors']
(out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
print('\n'.join(line for line in text.splitlines() if any(key in line for key in ('GPU:','XPU','GPU rays','GPU device','GPU Device')))[-6000:])
raise SystemExit(0 if report['passed'] else 1)
