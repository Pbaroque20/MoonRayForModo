"""Opt-in linear RGB reference comparison. Without --run only writes a plan."""
import argparse,array,json,math,os,platform,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from moonray_modo import native

def pixels(path):
    with path.open('rb') as stream:
        def line():
            value=stream.readline()
            while value.startswith(b'#'):value=stream.readline()
            return value.strip()
        if line()!=b'PF':raise ValueError('Expected RGB PFM')
        width,height=map(int,line().split());scale=float(line())
        if width<=0 or height<=0 or width*height>64000000 or not math.isfinite(scale) or scale==0:raise ValueError('Invalid image dimensions/scale')
        data=stream.read(width*height*12+1)
        if len(data)!=width*height*12:raise ValueError('Unexpected image byte count')
    values=array.array('f');values.frombytes(data)
    if (scale<0)!=(sys.byteorder=='little'):values.byteswap()
    if abs(scale)!=1:values=array.array('f',(v*abs(scale) for v in values))
    return (width,height),values

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--actual',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-error',type=float,default=.01)
    parser.add_argument('--rms-error',type=float,default=.001)
    parser.add_argument('--run',action='store_true')
    args=parser.parse_args()
    if any(not math.isfinite(v) or v<0 for v in (args.max_error,args.rms_error)):parser.error('Tolerances must be finite and nonnegative')
    folder=args.output.resolve()
    if folder.exists() and any(folder.iterdir()):parser.error('Choose an empty output directory')
    folder.mkdir(parents=True,exist_ok=True)
    report={'status':'not_run','reference':str(args.reference.resolve()),'actual':str(args.actual.resolve()),
      'platform':platform.platform(),'python':sys.version,'max_error_limit':args.max_error,'rms_error_limit':args.rms_error,
      'contract':'Inputs must use the same linear RGB working space, framing, exposure and alpha convention. RGB only; no automatic color transform. A pass does not establish renderer equivalence.'}
    try:
        if args.run:
            runtime=native.find_runtime(args.runtime);images=[]
            for label,source in [('reference',args.reference),('actual',args.actual)]:
                if not source.is_file():raise ValueError('Missing '+label+' image')
                target=folder/(label+'.pfm')
                result=subprocess.run([str(runtime/'oiiotool.exe'),str(source.resolve()),'--ch','R,G,B','-o',str(target)],
                    env=native.environment(runtime),capture_output=True,text=True,timeout=120,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                (folder/(label+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
                if result.returncode:raise ValueError('Image conversion failed: '+label)
                images.append(pixels(target))
            if images[0][0]!=images[1][0]:raise ValueError('Image dimensions differ')
            peak=0.;squares=0.;count=0
            for a,b in zip(images[0][1],images[1][1]):
                if not math.isfinite(a) or not math.isfinite(b):raise ValueError('Nonfinite pixels in comparison')
                difference=abs(a-b);peak=max(peak,difference);squares+=difference*difference;count+=1
            rms=math.sqrt(squares/count)
            report.update(dimensions=images[0][0],maximum_absolute_error=peak,rms_error=rms,
                status='passed' if peak<=args.max_error and rms<=args.rms_error else 'failed')
    except Exception as exc:report.update(status='failed',reason=str(exc))
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report['status'],folder/'report.json')
    return 1 if report['status']=='failed' else 0

if __name__=='__main__':raise SystemExit(main())
