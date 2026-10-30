"""Private canonical input -> immutable CPU plan -> image/edit checks."""
import argparse,array,json,subprocess
from pathlib import Path
from native_build import build
from fallback import environment
from reference_runtime import sha,verify
from run_cpu_image import rdla,compare_fixture
from run_m0 import standalone,image,guard
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();source=a.source.resolve();rt=a.runtime.resolve();out=a.output.resolve()
 if out.is_relative_to(source) or out.is_relative_to(rt):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);r={'status':'incomplete','scope':'experimental planar diffuse subset; production routing remains full fallback'}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
  files=[HERE/n for n in ('cpu_scene.h','cpu_lane.h','cpu_scene_probe.cc','run_cpu_scene.py','native_build.py','canonical_session.h','surface_core.h','sample_tree.h','sample_stream.h','path_stage.h','run_cpu_image.py','surface-gates.json')]+[ROOT/'xpu2'/n for n in ('rdl_scene_index.h','rdl_replica.h','indexed_scene.h','persistent_map.h')]
  held={str(p):sha(p) for p in files};r['source_hashes']=held
  gates=json.loads((HERE/'surface-gates.json').read_text());r['gates']=gates
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2)+'\n',encoding='utf-8')
  scene=out/'input.rdla';scene.write_text(rdla(0)+'\nSceneVariables { ["russian_roulette_threshold"]=0.0, ["lights_visible_in_camera"]=false }\n',encoding='utf-8')
  exe,meta=build(source,HERE/'cpu_scene_probe.cc',out/'build',[rt/'libembree4.dll']);r['build']=meta
  process=subprocess.run([str(exe),str(scene),str(rt),str(out)],env=environment(rt,out),cwd=out,capture_output=True,text=True,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'probe.log').write_text(process.stdout+process.stderr,encoding='utf-8')
  if process.returncode:raise RuntimeError('Native probe failed: '+process.stderr[-1200:])
  native=json.loads(process.stdout);r['native']=native
  if native['status']!='passed':raise RuntimeError('Native checks failed')
  if (out/'initial.rgba').read_bytes()!=(out/'retained-initial.rgba').read_bytes():raise RuntimeError('Old snapshot changed')
  if (out/'geometry.rgba').read_bytes()!=(out/'recovered.rgba').read_bytes():raise RuntimeError('Recovery changed image')
  r['comparisons']={}
  for stage in native['stages']:
   label=stage['name'];folder=out/('reference-'+label);print('Reference comparison:',label,flush=True)
   rendered=standalone(rt,out/label/'scene.rdlb',folder,1);ref=image(rt,folder)
   values=array.array('f');values.frombytes((out/(label+'.rgba')).read_bytes())
   r['comparisons'][label]={'execution':rendered['execution'],'errors':compare_fixture(values,ref,gates)}
  # Unsupported input still uses the exact frozen canonical RDLB in MoonRay.
  # It is never approximated by the prototype's Lambert operation.
  folder=out/'fallback-map';rendered=standalone(rt,out/'map/scene.rdlb',folder,1);ref=image(rt,folder)
  r['unsupported_map_fallback']={'execution':rendered['execution'],'image_sha256':sha(folder/'beauty.exr')}
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['status']='passed'
 except Exception as e:r.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in r.items() if k not in ('source_hashes','build','gates')},indent=2),flush=True)
 return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
