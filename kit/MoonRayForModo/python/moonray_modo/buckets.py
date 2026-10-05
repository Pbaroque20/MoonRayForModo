"""Bounded active tile protocol decoder, independent of Qt and Modo."""
def parse(line):
    parts=line.strip().split()
    if not parts or parts[0] not in ('@@MODO_TILES','@@MODO_WORKERS'):return None
    if not 4<=len(parts)<=516:return None
    try:
        generation,width,height=map(int,parts[1:4])
        if generation<0 or not 1<=width<=65535 or not 1<=height<=65535:return None
        rectangles=[]
        for value in parts[4:]:
            rect=tuple(map(int,value.split(',')))
            if len(rect)!=4:return None
            x0,y0,x1,y1=rect
            if not (0<=x0<x1<=width and 0<=y0<y1<=height):return None
            rectangles.append(rect)
        return generation,width,height,rectangles
    except (ValueError,OverflowError):return None
