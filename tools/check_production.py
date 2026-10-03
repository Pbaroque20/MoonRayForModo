"""Opt-in standalone fixture render. Never opens or changes Modo."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'kit/MoonRayForModo/python'),str(root/'tests')]
from moonray_modo import native,rdla,nodes
from test_production import scene

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime',required=True,type=Path)
parser.add_argument('--run',action='store_true',help='Explicitly run the standalone renderer; otherwise write a fixture only')
parser.add_argument('--mode',choices=('scalar','vector','xpu','auto'),default='scalar')
parser.add_argument('--vdb',type=Path,help='Optional VDB asset with a density grid')
args=parser.parse_args();runtime=native.find_runtime(args.runtime)
folder=Path(tempfile.mkdtemp(prefix='MoonRayProductionCheck-'))
value=scene();graph=nodes.new();graph['nodes']['displacement']={'type':'NormalDisplacement','parameters':{'height':.02,'bound_padding':.05}};graph['displacement']='displacement';value['materials']['']['node_graph']=graph
value['custom_aovs']=[{'name':'object_ids','kind':'cryptomatte'},{'name':'key_light','kind':'lpe','expression':"C.*<L.'key'>"},{'name':'motion_vectors','kind':'motion'}]
value['production']={'lights':{'key':{'label':'key','filter_enabled':True,'filter_exposure':-1}},'objects':{'mesh1':{'link_enabled':True,'lights':['key']}}}
value['extra_geometry']=[{'kind':'curves','identity':'hair','name':'Hair','vertices':[[-.6,0,.3],[-.6,1,.3]],'counts':[2],'radii':[.02,0]}, {'kind':'points','identity':'points','name':'Points','vertices':[[.7,0,.3]],'radius':.08}]
if args.vdb:value['extra_geometry'].append({'kind':'vdb','identity':'smoke','name':'Smoke','file':str(args.vdb.resolve()),'density_grid':'density'})
output=folder/'beauty.exr';rdla_path=folder/'scene.rdla';rdla_path.write_text(rdla.scene_text(value,128,128,2,.15,str(output)),encoding='utf-8')
print('Fixture:',rdla_path)
if args.run:
    with (folder/'render.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([str(runtime/'moonray.exe'),*native.arguments(rdla_path,output,4,args.mode)],env=native.environment(runtime),stdout=log,stderr=subprocess.STDOUT,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or not output.is_file():raise SystemExit('Render failed; inspect '+str(folder/'render.log'))
    info=subprocess.run([str(runtime/'oiiotool.exe'),'--info','-v',str(output)],env=native.environment(runtime),capture_output=True,text=True,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    (folder/'image-info.txt').write_text(info.stdout+info.stderr,encoding='utf-8')
    if info.returncode or 'Cryptomatte' not in info.stdout:raise SystemExit('EXR inspection failed; inspect image-info.txt')
    print('Native fixture completed. Inspect beauty, curve silhouettes, object IDs, light group and optional VDB before accepting visual parity.')
