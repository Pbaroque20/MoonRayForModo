"""Check live CUDA window bounds/masks using exact, analytic contribution values.

This is an ABI/kernel check, not rendered-scene validation. Run after the image
probe to avoid competing with its timing measurements.
"""
import argparse,ctypes as C,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build=a.build.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',cases=[],scope='Synthetic numeric ABI/kernel bounds and lane masks, not scene validation')
    try:
        manifest=json.loads((build/'report.json').read_text())
        if manifest['status']!='built':raise ValueError('Incomplete build')
        for name in ('film.ptx','xpu2_film.dll'):
            if digest_file(build/name)!=manifest['files'][name]:raise ValueError('Build drift')
        os.environ.update(XPU2_FILM_CONTRIBUTION='fast',XPU2_FILM_PTX=str(build/'film.ptx'),XPU2_FILM_PROFILE=str(out/'film.json'))
        directory=os.add_dll_directory(str(build/'runtime'))
        dll=C.CDLL(str(build/'xpu2_film.dll'))
        fn=dll.xpu2FilmWindow;fn.argtypes=[C.POINTER(C.c_float)]*3+[C.POINTER(C.c_int)]*2+[C.c_int];fn.restype=None
        finish=dll.xpu2FilmFinish;finish.argtypes=[];finish.restype=None
        expected_accepted=0;expected_unsupported=0
        for packet in (True,False):
            os.environ['XPU2_FILM_WINDOW']='1' if packet else '16'
            for slots in (1,9,16):
                src=(C.c_float*(128*24))();ref=(C.c_float*(128*8))()
                # Surround both write destinations with canaries. Requests never
                # permit a write beyond the active slot range.
                raw=(C.c_float*(128*8+2))(*([-999.]*(128*8+2)))
                results=(C.c_int*18)(*([-777]*18))
                dst=C.cast(C.byref(raw,C.sizeof(C.c_float)),C.POINTER(C.c_float))
                accepted=C.cast(C.byref(results,C.sizeof(C.c_int)),C.POINTER(C.c_int))
                masks=(C.c_int*16)();wanted=[];count=0
                for slot in range(slots):
                    masks[slot]=255 if slot%2==0 else 0x81
                    expected=0
                    for lane in range(8):
                        b=(slot*8+lane)*24
                        values=[2.,2.,1.,0.,0.,4.,.5,.5,1.,1.,1.,.25,.5,1.,2.,4.,8.]+[0.]*7
                        if lane==2:values[3]=1. # Mirror: native fallback.
                        if lane==3:values[4]=1. # Missing light: native fallback.
                        if lane==4:values[7]=0. # Invalid pdf: native fallback.
                        if lane==5:values[11]=float('nan') # Nonfinite: fallback.
                        if not masks[slot]&(1<<lane):values=[float('nan')]*24
                        for j,value in enumerate(values):src[b+j]=value
                        if masks[slot]&(1<<lane):
                            if lane in (2,3,4,5):expected_unsupported+=1
                            else:expected|=1<<lane;count+=1
                    wanted.append(expected)
                fn(src,ref,dst,masks,accepted,slots)
                if list(results)[1:1+slots]!=wanted:raise ValueError('Accepted-lane mask incorrect')
                if results[0]!=-777 or any(v!=-777 for v in list(results)[1+slots:]):raise ValueError('Mask boundary overwrite')
                if raw[0]!=-999. or any(v!=-999. for v in list(raw)[1+slots*8*8:]):raise ValueError('Output boundary overwrite')
                expected=[4.,.25,1.,4.,.25,.5,1.]
                for slot,mask in enumerate(wanted):
                    for lane in range(8):
                        if mask&(1<<lane):
                            b=(slot*8+lane)*8
                            if list(dst[b:b+7])!=expected:raise ValueError('Wrong contribution or sample offset')
                expected_accepted+=count
                report['cases'].append(dict(packet_control=packet,slots=slots,accepted=count,status='passed'))
        finish();profile=json.loads((out/'film.json').read_text());report['profile']=profile
        if profile['accepted']!=expected_accepted or profile['cpu_skipped']!=expected_accepted or profile['unsupported']!=expected_unsupported:raise ValueError('Accounting mismatch')
        if any(profile[k] for k in ('errors','mismatch','cleanup_errors')):raise ValueError('GPU or cleanup error')
        report.update(status='passed',build_manifest_sha256=digest_file(build/'report.json'))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(report['status'],report.get('error',''))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
