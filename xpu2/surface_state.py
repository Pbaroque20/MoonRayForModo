"""Parse explicit native numeric state captures; not resumable RayState objects."""
import math
import struct

IDS=('pixel','subpixel','sequence','tile_pass','ray_depth','ray_mask','ray_differentials',
     'geometry_derivatives','assignment','geometry','primitive','instance','dependencies',
     'diffuse_depth','glossy_depth','mirror_depth','nonmirror_depth','presence_depth',
     'hair_depth','subsurface_depth','volume_depth','lpe_state','lobe_type','pixel_samples')
FIELDS=(('origin',0,3),('direction',3,3),('near',6,1),('far',7,1),('time',8,1),
        ('origin_x',9,3),('direction_x',12,3),('origin_y',15,3),('direction_y',18,3),
        ('position',21,3),('geometric_normal',24,3),('normal',27,3),('uv',30,2),
        ('dpds',32,3),('dpdt',35,3),('throughput',38,3),('pixel_weight',41,1),
        ('aov_weight',42,1),('distance',43,1),('presence',44,1),('opacity',45,1),
        ('roughness',46,2),('subpixel_xy',48,2),('clamp',50,1),('primary_scale',51,1),
        ('texture_scale',52,1),('evaluated_presence',53,1))
RECORD=struct.Struct('<24I64f')

def decode(data):
    if data[:4]!=b'XNS1' or (len(data)-4)%RECORD.size:raise ValueError('Malformed surface capture')
    count=(len(data)-4)//RECORD.size
    if not 1<=count<=1024:raise ValueError('Surface capture count out of bounds')
    result=[]
    for offset in range(4,len(data),RECORD.size):
        values=RECORD.unpack_from(data,offset);ids=dict(zip(IDS,values[:24]));f=values[24:]
        if not all(math.isfinite(v) for v in f) or any(f[54:]):raise ValueError('Invalid numeric/reserved surface state')
        if ids['dependencies'] & ~31 or ids['ray_differentials'] not in (0,1) or ids['geometry_derivatives'] not in (0,1):raise ValueError('Unknown surface flags')
        if ids['pixel'] not in ((77<<16)|96,(96<<16)|132) or ids['subpixel']!=0:raise ValueError('Unexpected diagnostic sample')
        if not ids['ray_differentials'] and any(f[9:21]):raise ValueError('Inactive ray derivatives were not cleared')
        if not ids['geometry_derivatives'] and any(f[32:38]):raise ValueError('Inactive geometry derivatives were not cleared')
        result.append(dict(ids=ids,fields={name:list(f[start:start+size]) for name,start,size in FIELDS}))
    return result
