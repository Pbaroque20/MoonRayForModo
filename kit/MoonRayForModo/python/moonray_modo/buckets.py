"""Bounded active tile protocol decoder, independent of Qt and Modo."""
# XPU2 (xpu2_session.cc Outlines): where the GPU has handed samples on and they still wait, filled over the picture
# until they are rendered (viewer.py): samples it deferred to the CPU, and its provisional samples (textures read a level
# up while their tiles landed), not yet rendered again in full.
HANDOFF={'@@MODO_DEFERRED_TILES':'deferred','@@MODO_PROVISIONAL_TILES':'provisional'}
KINDS=('@@MODO_TILES','@@MODO_WORKERS','@@MODO_GPU_WORKERS')+tuple(HANDOFF)

def parse(line):
    parts=line.strip().split()
    if not parts or parts[0] not in KINDS:return None
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

def handoff_kind(line):
    """'deferred' or 'provisional' for XPU2's lines of where the GPU's handed-on samples wait, else None."""
    word=line.split(None,1)[0] if line.strip() else ''
    return HANDOFF.get(word)

def route(line,packet):
    """Which of the renderer's signals a parsed line goes to, and with what: ('buckets', packet) for the tiles, else
    ('workers', ...): the CPU workers' squares as they are, XPU2's GPU cells marked 'gpu', and its handed-on tiles marked
    'deferred' or 'provisional' (viewer.py set_workers)."""
    word=line.split(None,1)[0]
    if word in HANDOFF:return 'workers',(HANDOFF[word],)+tuple(packet)
    if word=='@@MODO_GPU_WORKERS':return 'workers',('gpu',)+tuple(packet)
    if word=='@@MODO_WORKERS':return 'workers',packet
    return 'buckets',packet
