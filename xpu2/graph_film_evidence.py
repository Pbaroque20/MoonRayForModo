"""Cached GPU graph lifetime and replay validation."""
from xpu2.fused_film_evidence import validate_fused
from xpu2.streamed_film_evidence import validate_streamed,compare_streamed


def validate_graph(p,mode):
    keys=('graph_enabled','graph_captures','graph_sources_freed','graph_builds','graph_frees','graph_launches','graph_build_ns')
    if any(type(p.get(k)) is not int or p[k]<0 for k in keys):raise ValueError('Missing graph evidence')
    if p['graph_captures']!=p['graph_sources_freed'] or p['graph_builds']!=p['graph_frees']:raise ValueError('Graph resource leak')
    if sum(p[k] for k in ('initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns','staging_ns','graph_build_ns'))>p['total_ns']:raise ValueError('Overlapping graph timing')
    if mode in ('blocking','blocking_repeat'):
        result=validate_streamed(p,mode)
        if any(p[k] for k in keys):raise ValueError('Blocking control used graph replay')
        return result
    if p['graph_enabled']!=1:raise ValueError('Graph path disabled')
    if mode in ('graph_build_fault','graph_launch_fault'):
        result=validate_fused(p,'missing')
        if p['async_enabled']!=1 or p['pinned_allocations']!=2 or p['pinned_frees']!=2:raise ValueError('Faulted graph leaked staging')
        if not p['graph_captures'] or p['async_completed'] or p['completion_waits']:raise ValueError('Graph fault did not stop completion')
        if mode=='graph_build_fault':
            if any(p[k] for k in ('graph_builds','graph_launches','async_batches','dispatches','error_drains')):raise ValueError('Failed graph build submitted work')
        else:
            if not p['graph_launches'] or p['graph_launches']!=p['error_drains'] or p['graph_launches']!=p['async_batches'] or p['graph_launches']!=p['dispatches']:raise ValueError('Enqueued graph failure was not drained')
        return dict(result,graph_mode=mode)
    result=validate_streamed(p,mode)
    if mode in ('missing','pinned_fault'):
        if any(p[k] for k in keys[1:]):raise ValueError('Initialization failure created graphs')
    else:
        if not 1<=p['graph_builds']<=32 or p['graph_builds']!=p['graph_captures']:raise ValueError('Graph cache bound not respected')
        if p['graph_launches']!=p['dispatches'] or not p['graph_launches']:raise ValueError('Graph replay not used')
    return dict(result,graph_mode=mode)


def compare_graph(blocking,graph):
    validate_graph(blocking,'blocking');validate_graph(graph,'fast')
    return dict(compare_streamed(blocking,graph),graph_builds=graph['graph_builds'],graph_launches=graph['graph_launches'])
