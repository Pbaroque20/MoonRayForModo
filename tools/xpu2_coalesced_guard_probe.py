"""Concurrent numeric CUDA checks: masking, job scatter and multi-block dispatch."""
import argparse,ctypes as C,json,os,sys,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_fused_guard_probe import bind,bits,F,I

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();build=a.build.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report=dict(status='incomplete',scope='Synthetic concurrent numeric CUDA guard; not a rendered scene')
 try:
  m=json.loads((build/'report.json').read_text());assert m['status']=='built'
  for n in ('xpu2_film.dll','film.ptx'):
   if digest_file(build/n)!=m['files'][n]:raise ValueError('Build drift')
  for k in list(os.environ):
   if k.startswith('XPU2_'):del os.environ[k]
  os.environ.update(XPU2_FILM_CONTRIBUTION='fast',XPU2_FILM_COALESCE='1',XPU2_FILM_PTX=str(build/'film.ptx'),XPU2_FILM_PROFILE=str(out/'film.json'),XPU2_FILM_QUEUE_PROFILE=str(out/'queue.json'))
  directory=os.add_dll_directory(str(build/'runtime'));dll=C.CDLL(str(build/'xpu2_film.dll'))
  plain=bind(dll,'xpu2FilmWindow',[F,F,F,I,I,C.c_int]);fused=bind(dll,'xpu2FilmFusedWindow',[F,F,F,I,I,C.c_int,F,F,I]);finish=bind(dll,'xpu2FilmFinish',[])
  pi=bits(0x3ea2f983);fixtures=[]
  for worker in range(16):
   src=(C.c_float*(128*24))();raw=(C.c_float*(128*24))();native=(C.c_float*(128*8))();ref=(C.c_float*(128*8))()
   masks=(C.c_int*16)(*([0xbf]*16));shader=(C.c_int*16)(*([0xdf]*16));valid=(C.c_int*16)(*([0x81]*16))
   before=(C.c_float*(128*8))();pm=(C.c_int*16)()
   for slot in range(16):
    for lane in range(8):
     b=(slot*8+lane)*24;o=(slot*8+lane)*8
     color=[.25*(1+worker),.5,1.];rgb=[C.c_float(v*pi).value for v in color]
     contribution=[2.,2.,1.,0.,0.,4.,.5,pi,1.,1.,1.,*rgb,2.,4.,8.]+[0.]*7
     packet=[bits(0x32535058),bits(1),0.,0.,1.,0.,0.,1.,0.,0.,1.,1.,0.,0.,*color,1.,1.,1.,bits(1),bits(1),0.,0.]
     expected=[0.,0.,1.,*rgb,pi,0.]
     if lane==1:expected[3]+=1.
     if lane==2:packet[22]=bits(1)
     if lane==3:packet[23]=bits(1)
     if lane==4:contribution[3]=1.
     if lane==6:packet=[float('nan')]*24
     for j in range(24):src[b+j]=contribution[j];raw[b+j]=packet[j]
     for j in range(8):native[o+j]=expected[j]
   plain(src,ref,before,valid,pm,16);fixtures.append((src,ref,masks,raw,native,shader,before))
  barrier=threading.Barrier(16,timeout=30)
  def worker(index):
   src,ref,masks,raw,native,shader,before=fixtures[index]
   for iteration in range(8):
    guarded=(C.c_float*(128*8+2))(*([-99.]*(128*8+2)));accepted=(C.c_int*18)(*([-77]*18))
    dst=C.cast(C.byref(guarded,4),F);ac=C.cast(C.byref(accepted,4),I)
    barrier.wait();fused(src,ref,dst,masks,ac,16,raw,native,shader)
    if list(accepted)[1:17]!=[0x81]*16 or accepted[0]!=-77 or accepted[17]!=-77:raise ValueError('Mask routing/canary failure worker='+str(index)+' masks='+str(list(accepted)))
    if guarded[0]!=-99 or guarded[-1]!=-99:raise ValueError('Output canary failure')
    for slot in range(16):
     for lane in (0,7):
      o=(slot*8+lane)*8
      if list(dst[o:o+7])!=list(before[o:o+7]):raise ValueError('Cross-job numeric routing failure worker='+str(index)+' slot='+str(slot)+' lane='+str(lane)+' actual='+str(list(dst[o:o+7]))+' expected='+str(list(before[o:o+7])))
   return 8
  with ThreadPoolExecutor(max_workers=16) as pool:completed=sum(pool.map(worker,range(16)))
  finish();q=json.loads((out/'queue.json').read_text());fp=json.loads((out/'film.json').read_text())
  if q['submitted']!=128 or q['returned']!=128 or q['declined'] or q['exceptions'] or q['combined']==0 or not 16<q['max_slots']<=128:raise ValueError('Concurrent queue/multi-block boundary not exercised')
  if fp['accepted']!=4608 or fp['shader_checked']!=4096 or fp['shader_mismatch']!=2048 or fp['shader_unsupported']!=4096 or fp['errors'] or fp['cleanup_errors']:raise ValueError('CUDA rejection accounting failed')
  report.update(status='passed',completed=completed,queue=q,film=fp,build_manifest_sha256=digest_file(build/'report.json'))
 except Exception as exc:
  report['error']=str(exc)
  if 'finish' in locals():finish()
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(report['status'],report.get('error',''))
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
