"""Deferred linear RGB reference comparison. Supply matching, linear EXR renders.

Reports numeric error only. A passing pair does not prove full scene parity.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import subprocess
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('moonray',type=Path)
parser.add_argument('modo',type=Path)
parser.add_argument('--rmse-limit',type=float,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
tool=root/'toolchain/msys64/ucrt64/bin/oiiotool.exe'

def load(path, temporary):
    subprocess.run([str(tool),str(path.resolve()),'--ch','R,G,B','-o',str(temporary)],
                   check=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    with temporary.open('rb') as stream:
        if stream.readline().strip()!=b'PF': raise ValueError('Expected RGB float pixels')
        width,height=map(int,stream.readline().split());scale=float(stream.readline())
        data=stream.read()
    if len(data)!=width*height*12: raise ValueError('Unexpected pixel buffer size')
    pixels=struct.unpack(('<' if scale<0 else '>')+'%df'%(width*height*3),data)
    if not all(math.isfinite(v) for v in pixels): raise ValueError('Non-finite image pixels')
    return (width,height),pixels

with tempfile.TemporaryDirectory(prefix='MoonRay-reference-') as temporary:
    shape,a=load(args.moonray,Path(temporary)/'moonray.pfm')
    other,b=load(args.modo,Path(temporary)/'modo.pfm')
if shape!=other: raise ValueError('Reference image dimensions differ')
rmse=math.sqrt(sum((x-y)**2 for x,y in zip(a,b))/len(a))
report={'passed':rmse<=args.rmse_limit,'linear_rgb_rmse':rmse,'threshold':args.rmse_limit,
        'size':shape,'max_absolute_error':max(abs(x-y) for x,y in zip(a,b)),
        'scope':'This supplied image pair only; inputs must share camera, exposure, color space and AOV.'}
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
