"""Validate the scenes produced by probe_rdl_part_links.py with MoonRay's native reader."""
import argparse, json, subprocess, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import native
p=argparse.ArgumentParser();p.add_argument('runtime');p.add_argument('--output',default='test-results/rdl-part-links');args=p.parse_args()
runtime=Path(args.runtime).resolve();out=Path(args.output).resolve()
report=json.loads((out/'report.json').read_text());assert report['ok'],report
checked=[]
for capture in report['captures']:
 path=Path(capture['path'])
 r=subprocess.run([str(runtime/'modo_rdl_import.exe'),str(path),str(runtime)],env=native.environment(runtime),capture_output=True,text=True,timeout=60)
 (out/(path.stem+'-reader.log')).write_text(r.stderr,encoding='utf-8')
 assert not r.returncode,r.stderr
 data=json.loads(r.stdout.rsplit('@@MODO_RDL_JSON',1)[1]);objects={v['name']:v for v in data['objects']}
 (out/(path.stem+'-readback.json')).write_text(json.dumps(data,indent=2),encoding='utf-8')
 layer=next(v['attributes'] for v in data['objects'] if v['type']=='Layer')
 rows=[i for i,g in enumerate(layer['geometries']) if g.startswith('/modo/mesh/')]
 selected=[tuple(objects[layer['lightsets'][i]]['attributes']['lights']) for i in rows]
 assert len(set(selected))==2,(rows,selected)
 assert all(len(v)==1 for v in selected),selected
 assert sum(bool(layer['lightfiltersets'][i]) for i in rows)==1,layer
 assert sum(bool(layer['shadowsets'][i]) for i in rows)==1,layer
 checked.append(path.stem)
(out/'native-report.json').write_text(json.dumps({'ok':True,'captures':checked},indent=2),encoding='utf-8')
print('Native per-part assignments passed:',', '.join(checked))
