"""Coverage gates for the restricted live environment-light experiment."""
import math
import struct
VARIANTS=('sphere','tinted','black','hemisphere_up','hemisphere_down','short_ray')

def coverage(cases):
    groups={name:[] for name in VARIANTS}
    for row in cases:
        if row.get('variant') not in groups or len(row.get('sample',[]))!=8 or len(row.get('expected',[]))!=16:
            raise ValueError('Malformed native light result')
        values=struct.unpack('<24f',struct.pack('<24I',*(row['sample']+row['expected'])))
        if not all(math.isfinite(x) for x in values) or values[7]!=0 or values[16] not in (0,1):
            raise ValueError('Invalid native light result')
        if not any(values[12:15]):raise ValueError('Indirect path not exercised')
        if values[16]==0 and (any(values[17:]) or any(values[9:12])):
            raise ValueError('Miss retained light/direct output')
        groups[row['variant']].append(values)
    sizes={len(rows) for rows in groups.values()}
    if len(sizes)!=1 or 0 in sizes:raise ValueError('Incomplete light variant coverage')
    result={name:dict(cases=len(rows),hits=sum(x[16]==1 for x in rows),
                      nonzero_direct=sum(any(x[9:12]) for x in rows)) for name,rows in groups.items()}
    for name in ('sphere','tinted','black'):
        if result[name]['hits']!=result[name]['cases']:raise ValueError('Full environment unexpectedly missed')
    if result['short_ray']['hits'] or result['black']['nonzero_direct']:
        raise ValueError('Black/missed light contributed direct illumination')
    for name in ('sphere','tinted'):
        if result[name]['nonzero_direct']!=result[name]['cases']:raise ValueError('Lit branch not exercised')
    combined=result['hemisphere_up']['hits']+result['hemisphere_down']['hits']
    if combined!=result['sphere']['cases']:raise ValueError('Hemisphere cutoff coverage changed')
    return result
