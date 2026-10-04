"""Reorder supplied simulation samples by explicit point or strand identity."""
import copy

def align(reference,sample):
 ids=reference.get('ids');other=sample.get('ids')
 if ids is None and other is None:raise ValueError('Strict point/strand motion requires persistent IDs; provide simulation IDs, a point-ID map or strand-ID tag, or choose freeze/velocity motion')
 if ids is None or other is None:raise ValueError('Every shutter sample must provide geometry IDs')
 def validate(entry,values):
  size=len(entry.get('counts',[])) if entry['kind']=='curves' else len(entry['vertices'])
  if len(values)!=size or any(type(v) not in (str,int) for v in values) or len(set(values))!=len(values):raise ValueError('Geometry IDs must be unique strings/integers, one per point or strand')
 validate(reference,ids);validate(sample,other)
 if set(ids)!=set(other):raise ValueError('Simulation IDs change during the shutter; choose an explicit freeze or velocity policy for births/deaths')
 positions={identity:i for i,identity in enumerate(other)};order=[positions[v] for v in ids];result=copy.deepcopy(sample)
 if reference['kind']=='points':
  vertices=order
 else:
  counts=sample['counts'];offsets=[0]
  for count in counts:offsets.append(offsets[-1]+count)
  if offsets[-1]!=len(sample['vertices']):raise ValueError('Curve counts do not match vertices')
  vertices=[v for i in order for v in range(offsets[i],offsets[i+1])]
  result['counts']=[counts[i] for i in order]
  if result['counts']!=reference['counts']:raise ValueError('Strand topology changed during shutter')
  if 'uvs' in sample:result['uvs']=[sample['uvs'][i] for i in order]
 for key in ('vertices','velocities','vertices_close'):
  if key in sample:
   if len(sample[key])!=len(sample['vertices']):raise ValueError('Per-vertex field length mismatch: '+key)
   result[key]=[sample[key][i] for i in vertices]
 radii=sample.get('radii')
 if radii and len(radii)>1:
  selection=vertices if len(radii)==len(sample['vertices']) else order
  if len(radii) not in (len(sample['vertices']),len(other)):raise ValueError('Radius count mismatch')
  result['radii']=[radii[i] for i in selection]
 result['ids']=list(ids);return result
