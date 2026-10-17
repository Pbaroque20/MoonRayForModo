"""Exercise fused capture ownership and CUDA rejection masks, outside Modo.

Synthetic numeric checks complement the native images. Deliberate shader
mismatches are expected here; they must produce no accepted output.
"""
import argparse,ctypes as C,json,os,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file
F=C.POINTER(C.c_float);I=C.POINTER(C.c_int)
def bits(i):return struct.unpack('<f',struct.pack('<I',i))[0]
def bind(dll,name,args):
    f=getattr(dll,name);f.argtypes=args;f.restype=None;return f

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--streamed',action='store_true')
    p.add_argument('--graphs',action='store_true')
    a=p.parse_args()
    if a.graphs and not a.streamed:p.error('--graphs requires --streamed')
    build=a.build.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',scope='Synthetic capture ownership and fused CUDA lane rejection; not scene validation',capture=[],windows=[])
    try:
        m=json.loads((build/'report.json').read_text());assert m['status']=='built' and m['fused']
        for name in ('film.ptx','xpu2_film.dll','runtime/xpu2_batched.dll'):
            if digest_file(build/name)!=m['files'][name]:raise ValueError('Build drift')
        os.environ.update(XPU2_FILM_CONTRIBUTION='fast',XPU2_FUSED_FILM='1',XPU2_FILM_PTX=str(build/'film.ptx'),XPU2_FILM_PROFILE=str(out/'film.json'))
        if a.streamed:os.environ['XPU2_FILM_ASYNC_TRANSFERS']='1'
        if a.graphs:os.environ['XPU2_FILM_GRAPH']='1'
        directory=os.add_dll_directory(str(build/'runtime'))
        capture=C.CDLL(str(build/'runtime/xpu2_batched.dll'))
        begin=bind(capture,'xpu2BatchedBegin',[C.c_int]);end=bind(capture,'xpu2BatchedSampleEnd',[])
        sample=bind(capture,'xpu2BatchedLambert',[F,F,I,C.c_int]);collect=bind(capture,'xpu2BatchedCollect',[F,C.c_int,C.c_int]);take=bind(capture,'xpu2FusedTake',[F,F,I,C.c_int])
        for case in ('owned_copy','changed_wrapper','missing_lane','multiple_lobes','reuse'):
            raw=(C.c_float*48)(*range(48));ref=(C.c_float*16)(*range(16));lanes=(C.c_int*2)(7,1)
            post=(C.c_float*64)()
            for n,lane in enumerate(lanes):
                for j in range(8):post[lane*8+j]=ref[n*8+j]
            begin(15);sample(raw,ref,lanes,2)
            if case=='multiple_lobes':sample(raw,ref,lanes,2)
            end()
            if case=='changed_wrapper':post[7*8+3]+=1
            if case=='owned_copy':raw[0]=999;ref[0]=999
            collect(post,2 if case=='missing_lane' else 130,15)
            saved=(C.c_float*192)();native=(C.c_float*64)();mask=C.c_int(-1)
            take(saved,native,C.byref(mask),15)
            expected=130 if case in ('owned_copy','reuse') else 0
            if mask.value!=expected:raise ValueError('Capture guard failed '+case)
            if expected and (saved[7*24]!=0 or saved[1*24]!=24 or native[7*8]!=0 or native[1*8]!=8):raise ValueError('Capture input was borrowed or misrouted')
            report['capture'].append(dict(case=case,status='passed',mask=mask.value))
        dll=C.CDLL(str(build/'xpu2_film.dll'))
        plain=bind(dll,'xpu2FilmWindow',[F,F,F,I,I,C.c_int])
        fused=bind(dll,'xpu2FilmFusedWindow',[F,F,F,I,I,C.c_int,F,F,I])
        finish=bind(dll,'xpu2FilmFinish',[])
        pi=bits(0x3ea2f983)
        for slots in (1,9,16):
            src=(C.c_float*(128*24))();raw=(C.c_float*(128*24))();native=(C.c_float*(128*8))();ref=(C.c_float*(128*8))()
            masks=(C.c_int*16)();shader=(C.c_int*16)();valid=(C.c_int*16)()
            before=(C.c_float*(128*8))();plain_masks=(C.c_int*16)()
            guarded=(C.c_float*(128*8+2))(*([-99.]*(128*8+2)));accepted=(C.c_int*18)(*([-77]*18))
            dst=C.cast(C.byref(guarded,4),F);accepted_ptr=C.cast(C.byref(accepted,4),I)
            for slot in range(slots):
                masks[slot]=0xbf;shader[slot]=0xdf;valid[slot]=0x81
                for lane in range(8):
                    b=(slot*8+lane)*24;o=(slot*8+lane)*8
                    rgb=[C.c_float(v*pi).value for v in (.25,.5,1.)]
                    contribution=[2.,2.,1.,0.,0.,4.,.5,pi,1.,1.,1.,*rgb,2.,4.,8.]+[0.]*7
                    packet=[bits(0x32535058),bits(1),0.,0.,1.,0.,0.,1.,0.,0.,1.,1.,0.,0.,.25,.5,1.,1.,1.,1.,bits(1),bits(1),0.,0.]
                    expected=[0.,0.,1.,*rgb,pi,0.]
                    if lane==1:expected[3]+=1.
                    if lane==2:packet[22]=bits(1)
                    if lane==3:packet[23]=bits(1)
                    if lane==4:contribution[3]=1.
                    if lane==6:packet=[float('nan')]*24
                    for j in range(24):src[b+j]=contribution[j];raw[b+j]=packet[j]
                    for j in range(8):native[o+j]=expected[j]
            plain(src,ref,before,valid,plain_masks,slots)
            fused(src,ref,dst,masks,accepted_ptr,slots,raw,native,shader)
            if list(accepted)[1:slots+1]!=[0x81]*slots:raise ValueError('Wrong fused acceptance mask')
            if accepted[0]!=-77 or any(v!=-77 for v in list(accepted)[slots+1:]):raise ValueError('Acceptance boundary overwrite')
            if guarded[0]!=-99 or any(v!=-99 for v in list(guarded)[slots*64+1:]):raise ValueError('Image boundary overwrite')
            for slot in range(slots):
                for lane in (0,7):
                    o=(slot*8+lane)*8
                    if list(dst[o:o+7])!=list(before[o:o+7]):raise ValueError('Fused numeric result differs')
            report['windows'].append(dict(slots=slots,accepted=slots*2,intentional_shader_mismatches=slots,status='passed'))
        finish();profile=json.loads((out/'film.json').read_text());report['profile']=profile
        if profile['shader_checked']!=52 or profile['accepted']!=104 or profile['cpu_skipped']!=104 or profile['shader_mismatch']!=26 or profile['mismatch']!=26 or profile['shader_unsupported']!=52:raise ValueError('Guard accounting incorrect')
        if profile['errors'] or profile['cleanup_errors']:raise ValueError('GPU or cleanup failed')
        if a.streamed:
            if profile['async_completed']!=6 or profile['completion_waits']!=6 or profile['pinned_allocations']!=2 or profile['pinned_frees']!=2:raise ValueError('Pinned transfer completion/lifetime failure')
        if a.graphs:
            if profile['graph_builds']!=6 or profile['graph_frees']!=6 or profile['graph_launches']!=6 or profile['graph_captures']!=6 or profile['graph_sources_freed']!=6:raise ValueError('Graph lifecycle or replay failure')
        report.update(graphs=a.graphs,streamed=a.streamed,status='passed',build_manifest_sha256=digest_file(build/'report.json'))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(report['status'],report.get('error',''))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
