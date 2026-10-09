"""The ramps and the transforms among a shader's attributes, as the things they are rather than lists of numbers.

MoonRay holds a ramp as three lists that go together, and a transform as sixteen numbers. Neither is something to
type: the graph editor and the material forms show a ramp as a strip of its colours and a transform as a move, a
turn and a size. This says which attributes those are and takes a transform apart and puts it together; it touches
neither Modo nor Qt."""
import math


def groups(schema):
    """The ramps among a node's attributes: positions, the colours or values at them, and how each blends to the
    next. Returns {positions key: (label, positions key, values key, interpolations key)}."""
    found={}
    for key in schema:
        if not key.endswith('positions') or not schema[key]['type']=='FloatVector':continue
        stem=key[:-len('positions')]
        values=next((stem+word for word in ('colors','values') if stem+word in schema),None)
        blends=stem+'interpolations'
        if values is None or blends not in schema:continue
        found[key]=((stem.replace('_',' ')+'ramp').strip(),key,values,blends)
    return found


def parts(matrix):
    """A transform as (move, turn in degrees about X then Y then Z, size), or None for one that shears, mirrors or
    is not sixteen numbers, which those three cannot say."""
    if not isinstance(matrix,(list,tuple)) or len(matrix)!=16:return None
    try:matrix=[float(v) for v in matrix]
    except (TypeError,ValueError):return None
    if any(not math.isfinite(v) for v in matrix) or any(abs(matrix[i])>1e-9 for i in (3,7,11)) or abs(matrix[15]-1)>1e-9:return None
    rows=[matrix[i*4:i*4+3] for i in range(3)]
    sizes=[math.sqrt(sum(v*v for v in row)) for row in rows]
    if any(size<1e-12 for size in sizes):return None
    turn=[[v/size for v in row] for row,size in zip(rows,sizes)]
    if any(abs(sum(a*b for a,b in zip(turn[i],turn[j])))>1e-4 for i,j in ((0,1),(0,2),(1,2))):return None
    cross=[turn[0][1]*turn[1][2]-turn[0][2]*turn[1][1],turn[0][2]*turn[1][0]-turn[0][0]*turn[1][2],turn[0][0]*turn[1][1]-turn[0][1]*turn[1][0]]
    if sum(a*b for a,b in zip(cross,turn[2]))<0:return None
    if abs(turn[0][2])>.999999:
        # Turned a quarter about Y, the other two turn about the same line: all of it is given to X.
        x,y,z=math.atan2(-turn[2][1],turn[1][1]),-math.copysign(math.pi/2,turn[0][2]),0.0
    else:
        x,y,z=math.atan2(turn[1][2],turn[2][2]),-math.asin(turn[0][2]),math.atan2(turn[0][1],turn[0][0])
    return list(matrix[12:15]),[math.degrees(v)+0.0 for v in (x,y,z)],sizes


def matrix(move,turn,size):
    """The transform that sizes, then turns about X, Y and Z, then moves: what parts() takes apart."""
    (sx,cx),(sy,cy),(sz,cz)=[(math.sin(math.radians(v)),math.cos(math.radians(v))) for v in turn]
    rows=[[cy*cz,cy*sz,-sy],[sx*sy*cz-cx*sz,sx*sy*sz+cx*cz,sx*cy],[cx*sy*cz+sx*sz,cx*sy*sz-sx*cz,cx*cy]]
    result=[]
    for row,scale in zip(rows,size):result.extend([v*float(scale) for v in row]+[0.0])
    return result+[float(v) for v in move]+[1.0]


def words(matrix):
    """A transform in a line, for the button that opens it."""
    held=parts(matrix)
    if held is None:return None
    said=[]
    for name,values,rest in (('Move',held[0],0.0),('Turn',held[1],0.0),('Size',held[2],1.0)):
        if any(abs(v-rest)>1e-6 for v in values):said.append(name+' '+' '.join('%.4g'%(v+0.0) for v in values))
    return ', '.join(said) or 'Not moved, turned or sized'
