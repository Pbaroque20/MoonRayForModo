"""Audit the consolidated builder's retained history and generated-source equivalence."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.native_build import historical_source,STAGES
from xpu2.reference import digest_file


def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete'}
 try:
  manifest=ROOT/'xpu2/legacy-builders.json';record=json.loads(manifest.read_text())
  assert len(record['builders'])==44
  archive=subprocess.check_output(['git','archive',record['revision'],'tools'],cwd=ROOT)
  with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
   for row in record['builders']:
    data=tar.extractfile(row['path']).read()
    assert hashlib.sha256(data).hexdigest()==row['git_content_sha256']
    assert not (ROOT/row['path']).exists()
  assert not list((ROOT/'tools').glob('xpu2_native_*_build.py'))
  row=record['builders'][0];historical_source(ROOT/row['path'],row['git_content_sha256'])
  rejected=False
  try:historical_source(ROOT/row['path'],'0'*64)
  except ValueError:rejected=True
  assert rejected,'Historical tampering accepted'
  for module in STAGES.values():assert (ROOT/'xpu2'/(module+'.py')).is_file()
  before,after=a.before.resolve(),a.after.resolve();compared=[]
  for f in sorted(before.iterdir()):
   if f.suffix not in ('.h','.inc','.ispc','.cc'):continue
   other=after/f.name;left=f.read_text();right=other.read_text()
   # Two intentional review changes landed between builds; compiler consolidation
   # must not otherwise alter generated native code.
   if f.name=='resident_records.h':right=right.replace('static_assert(sizeof(prepared::Group::common)==commonWords*sizeof(float),"Resident common layout drift");\n','')
   if f.name=='early_queue.inc':right=right.replace('if(!residentRejected)std::fputs("XPU2: rejected stale/invalid resident record; using native CPU fallback\\n",stderr);','')
   assert left==right,'Generated code drift '+f.name
   compared.append({'name':f.name,'before':digest_file(f),'after':digest_file(other)})
  report.update(status='passed',archived_builders=44,manifest_sha256=digest_file(manifest),compared_sources=compared,
   scope='All archived builder sources verified. Current resident recipe actually compiled; other active recipes share this pipeline but were not rebuilt in this audit.')
 except Exception as exc:report.update(status='failed',error=str(exc))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(report['status'],report.get('error',''))
 return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
