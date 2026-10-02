"""Deferred small renders for Auto, Vector, Scalar; does not launch Modo."""
import argparse,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla
parser=argparse.ArgumentParser();parser.add_argument('runtime',type=Path);args=parser.parse_args()
runtime=native.find_runtime(args.runtime);out=root/'test-results'/('modes-'+time.strftime('%Y%m%d-%H%M%S'));out.mkdir(parents=True)
scene={'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'focal_mm':50,'film_mm':36},'materials':{'':{'color':[.5,.1,.1]}},'lights':[],
'meshes':[{'name':'quad','vertices':[[-1,-1,0],[1,-1,0],[1,1,0],[-1,1,0]],'faces':[[0,1,2,3]],'material':''}],'render_settings':{'sampling_mode':0}}
source=out/'scene.rdla';source.write_text(rdla.scene_text(scene,64,64,2,1),encoding='utf-8')
for mode in ('auto','vector','scalar'):
 image=out/(mode+'.exr')
 result=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(source,image,4,mode),env=native.environment(runtime),cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
 log=result.stdout.decode('utf-8',errors='replace');(out/(mode+'.log')).write_text(log,encoding='utf-8')
 assert result.returncode==0 and image.is_file() and image.stat().st_size>16,log[-2000:]
 selected=native.execution_status(log)
 assert selected and 'active' in selected,log[-2000:]
 if mode=='vector': assert selected.startswith('Vector')
 if mode=='scalar': assert selected.startswith('Scalar')
 print(mode+': '+selected)
print('Completed; unsupported-feature and GPU-memory fallback cases require separate scenes.')
