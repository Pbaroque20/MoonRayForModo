"""Retain native-image and fused CUDA direct-light qualification evidence."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT)]
from xpu2.reference import digest_file

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--captures',type=Path,nargs='+',required=True);p.add_argument('--cuda',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();file=a.cuda.resolve()/'report.json';r=json.loads(file.read_text())
 if r['status']!='passed' or not r['schedule_exact'] or not r['comparator_sentinel'] or r['rejection_controls']!=13:raise ValueError('Unqualified CUDA report')
 if [v['block_size'] for v in r['runs']]!=[64,128,256]:raise ValueError('Incomplete launch matrix')
 if any(v['accepted']!=v['records'] or v['declined'] or v['different_records'] or v['failed_records'] for v in r['runs']):raise ValueError('Numerical mismatch')
 for f,h in r['source_hashes'].items():
  if digest_file(Path(f))!=h:raise ValueError('Source/capture drift')
 if digest_file(file.parent/'direct_light.ptx')!=r['ptx_sha256']:raise ValueError('PTX drift')
 captures=[]
 for folder in a.captures:
  f=folder.resolve()/'report.json';c=json.loads(f.read_text());binary=f.parent/'capture/light.bin'
  if c['status']!='passed' or digest_file(binary)!=c['capture_sha256']:raise ValueError('Capture drift')
  if r['source_hashes'][str(f)]!=digest_file(f):raise ValueError('CUDA used a different capture')
  if [v['label'] for v in c['runs']]!=['reference','capture'] or any(v['comparison']['status']!='passed' or v['comparison']['exactly_different_pixels'] for v in c['runs']):raise ValueError('Image mismatch')
  captures.append({'path':str(f.relative_to(ROOT)),'sha256':digest_file(f),'capture_sha256':c['capture_sha256'],'records':c['records'],'counts':c['counts'],'runs':c['runs']})
 if sum(c['records'] for c in captures)!=r['runs'][0]['records']:raise ValueError('Record accounting mismatch')
 result={'status':'passed','scope':'Captured valid diffuse direct-light arithmetic; not live GPU image restoration or speed qualification','captures':captures,'cuda':{'path':str(file.relative_to(ROOT)),'sha256':digest_file(file),**r},'component_order':['material_r','material_g','material_b','pdf','unshadowed_contribution_r','unshadowed_contribution_g','unshadowed_contribution_b','mis_weight']}
 a.output.write_text(json.dumps(result,indent=2)+'\n');print('passed',flush=True)
if __name__=='__main__':main()
