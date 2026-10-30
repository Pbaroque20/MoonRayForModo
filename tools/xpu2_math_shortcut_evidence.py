"""Retain the math-shortcut experiment without promoting approximate images to exact passes."""
import json
from pathlib import Path
import statistics
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file


def evidence():
    result={'schema':1, 'experiment':'rough diffuse inverse-cosine/cosine to clamped dot product',
            'scope':'One native worker, fixed sampling, rough diffuse plus transmission fixture.',
            'reports':{}, 'limitations':[
                'Not a general reversible representation compiler or full GPU material shading.',
                'Numerical tolerance passing does not imply bitwise parity or production qualification.',
                'CUDA event intervals may include scheduling contention; they are not isolated arithmetic timings.',
                'Three measured rounds and process snapshots do not exclude all background system activity.']}
    for name in ('checks','timing'):
        path=ROOT/'test-results'/('xpu2-math-rough-'+name)/'report.json'
        report=json.loads(path.read_text())
        if report['status'] not in ('passed','image_differences'):
            raise ValueError('Incomplete diagnostic '+name)
        rows=[]
        for run in report['runs']:
            row={k:run[k] for k in ('round','label','seconds','exact_parity','comparison','families','activity_before','activity_after') if k in run}
            row['mcrt_seconds']=run['execution']['renderer_timings_seconds']['Mcrt time']
            if 'profiles' in run:
                row['profiles']={k:run['profiles'][k] for k in ('gpu','flight','transport','window','prepared','resident')}
            rows.append(row)
        result['reports'][name]={'sha256':digest_file(path),'status':report['status'],
            'exact_parity':report['exact_parity'],'tolerance_parity':report['tolerance_parity'],
            'runs':rows,'summary':report['summary']}
        if name=='timing':
            pairs={}
            for run in rows:
                if run['round']>0:pairs.setdefault(run['round'],{})[run['label']]=run['mcrt_seconds']
            delta=[row['shortcut']-row['exact'] for _,row in sorted(pairs.items())]
            result['paired_shortcut_minus_exact_seconds']=delta
            result['paired_median_seconds']=statistics.median(delta)
    result['build_report_sha256']=digest_file(ROOT/'test-results/xpu2-resident-v2-build/report.json')
    result['ptx_reports']={name:json.loads((ROOT/'test-results'/('xpu2-math-'+name+'-ptx')/'report.json').read_text()) for name in ('exact','shortcut')}
    return result


if __name__=='__main__':
    path=ROOT/'xpu2/math-shortcut-20261019.json'
    path.write_text(json.dumps(evidence(),indent=2)+'\n',encoding='utf-8')
    print(path)
