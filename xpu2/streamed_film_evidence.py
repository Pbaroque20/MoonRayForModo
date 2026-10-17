"""Pinned-transfer evidence gates include completed reads and balanced lifetime."""
from xpu2.fused_film_evidence import validate_fused


def validate_streamed(p,mode):
    keys=('async_enabled','pinned_allocations','pinned_frees','async_batches','async_completed','completion_waits','error_drains','staging_ns')
    if any(type(p.get(k)) is not int or p[k]<0 for k in keys):raise ValueError('Incomplete stream evidence')
    base='fast' if mode in ('blocking','blocking_repeat') else 'missing' if mode in ('transfer_fault','pinned_fault') else mode
    result=validate_fused(p,base)
    if p['pinned_allocations']!=p['pinned_frees']:raise ValueError('Pinned allocation leak')
    if sum(p[k] for k in ('initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns','staging_ns'))>p['total_ns']:raise ValueError('Overlapping stream timing')
    if mode in ('blocking','blocking_repeat'):
        if any(p[k] for k in keys):raise ValueError('Blocking control used asynchronous transfers')
        return result
    if p['async_enabled']!=1:raise ValueError('Stream path disabled')
    if mode in ('missing','pinned_fault'):
        if any(p[k] for k in ('async_batches','async_completed','completion_waits','error_drains','dispatches')):raise ValueError('Initialization failure submitted work')
        if p['pinned_allocations']!=(1 if mode=='pinned_fault' else 0):raise ValueError('Partial allocation control not exercised')
    elif mode=='transfer_fault':
        if p['pinned_allocations']!=2 or not p['async_batches'] or p['error_drains']!=p['async_batches']:raise ValueError('Queued uploads were not drained')
        if any(p[k] for k in ('async_completed','completion_waits','dispatches')):raise ValueError('Faulted work completed')
    else:
        if p['pinned_allocations']!=2 or not p['async_batches']:raise ValueError('Pinned path not used')
        if p['async_batches']!=p['dispatches'] or p['async_completed']!=p['dispatches'] or p['completion_waits']!=p['dispatches']:raise ValueError('Dispatch did not complete through exactly one wait')
        if p['error_drains']:raise ValueError('Unexpected transfer failure')
    return dict(result,transfer_mode=mode,pinned_frees=p['pinned_frees'])


def compare_streamed(blocking,streamed):
    validate_streamed(blocking,'blocking');validate_streamed(streamed,'fast')
    for k in ('eligible','accepted','cpu_skipped','shader_checked','packets','dispatches'):
        if blocking[k]!=streamed[k]:raise ValueError('Completed work changed: '+k)
    return dict(status='passed',dispatches=streamed['dispatches'],accepted=streamed['accepted'],
                blocking_bridge_seconds=blocking['total_ns']/1e9,streamed_bridge_seconds=streamed['total_ns']/1e9)
