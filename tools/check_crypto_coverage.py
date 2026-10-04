"""Inspect candidate fixture ID/coverage values using the toolchain OpenImageIO Python."""
import argparse,json,math,struct,re
from pathlib import Path
import OpenImageIO as oiio

def bits(value):return struct.unpack('<I',struct.pack('<f',value))[0]
def converted(value):
    value=int(value,16)
    return value^(1<<23) if (value>>23)&255 in (0,255) else value

def read(path,part):
    image=oiio.ImageBuf(str(path),part,0)
    if not image.read(part,0,True,oiio.FLOAT):raise ValueError(image.geterror())
    spec=image.spec();names=list(spec.channelnames)
    pairs=[(i,names.index(name[:-1]+coverage)) for i,name in enumerate(names)
           for channel,coverage in [('R','G'),('B','A')] if re.fullmatch(r'Cryptomatte[0-9]{2}\.'+channel,name)]
    if not pairs:raise ValueError('No Cryptomatte channels')
    manifest=json.loads(spec.get_string_attribute('cryptomatte/d44fae7/manifest'))
    known={converted(v) for v in manifest.values()};found=set();pixels=[]
    for y in range(spec.height):
        for x in range(spec.width):
            values=image.getpixel(x,y);pixel={}
            for i,c in pairs:
                weight=values[c];identity=bits(values[i])
                if not math.isfinite(weight) or weight<0 or weight>1.00001:raise ValueError('Invalid coverage')
                if weight>0 and identity:
                    if identity not in known:raise ValueError('ID missing from manifest: '+hex(identity))
                    pixel[identity]=pixel.get(identity,0)+weight;found.add(identity)
            if sum(pixel.values())>1.00001:raise ValueError('Coverage exceeds one')
            pixels.append(pixel)
    return pixels,manifest,found

def difference(a,b):
    if len(a)!=len(b):raise ValueError('Image size mismatch')
    return max((abs(p.get(k,0)-q.get(k,0)) for p,q in zip(a,b) for k in set(p)|set(q)),default=0)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('folder',type=Path)
    args=parser.parse_args();report={'checks':[]}
    for mode in ('scalar','vector','xpu'):
        categories={}
        for part,cat in enumerate(('object','material','asset'),1):
            pixels,manifest,found=read(args.folder/(mode+'-all.exr'),part)
            single,single_manifest,_=read(args.folder/(mode+'-'+cat+'.exr'),0)
            error=difference(pixels,single)
            check={'mode':mode,'category':cat,'single_render_max_coverage_difference':error,'visible_ids':len(found),'manifest_entries':len(manifest),
                   'passed':error<=1e-6 and manifest==single_manifest and len(found)=={'object':3,'material':2,'asset':1}[cat]}
            report['checks'].append(check);categories[cat]=(pixels,manifest)
        object_pixels,object_manifest=categories['object']
        for cat in ('material','asset'):
            pixels,manifest=categories[cat];mapping={}
            for name,identity in object_manifest.items():
                index=int(re.search(r'object(\d+)\]',name).group(1))
                label=('Shared red [0]' if index%2==0 else 'Blue [1]') if cat=='material' else 'assembly'
                mapping[converted(identity)]=converted(manifest[label])
            expected=[]
            for pixel in object_pixels:
                value={}
                for identity,weight in pixel.items():value[mapping[identity]]=value.get(mapping[identity],0)+weight
                expected.append(value)
            error=difference(pixels,expected)
            report['checks'].append({'mode':mode,'category':cat,'object_aggregation_max_coverage_difference':error,'passed':error<=1e-6})
    report['passed']=all(c['passed'] for c in report['checks'])
    (args.folder/'coverage-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    if not report['passed']:raise SystemExit(1)

if __name__=='__main__':main()
