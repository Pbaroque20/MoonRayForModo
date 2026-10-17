"""Validate ordering at real native frame and accelerator lifetime boundaries."""
import json

def validate(trace,frames,updated=False,dedicated=False,require_progress=False):
    rows=[json.loads(line.split('XPU2_NATIVE_DRAIN ',1)[1]) for line in trace.splitlines() if line.startswith('XPU2_NATIVE_DRAIN ')]
    if not rows or any(row.get('error') or row.get('mismatches') for row in rows):raise ValueError('Native drain error or visibility mismatch')
    if dedicated:
        reservation=None
        for row in rows:
            if row['event']=='accelerator_rebuild':reservation=None
            elif row['event']=='queue_reserved':reservation=row
            elif row['event'] in ('captured','worker_begin','worker_done'):
                keys=('native_slots','worker_queue')
                if reservation is None or any(row.get(k)!=reservation.get(k) for k in keys):raise ValueError('Missing or stale dedicated queue reservation')
    opens=[r for r in rows if r['event']=='frame_open']
    if len(opens)!=frames or [r['generation'] for r in opens]!=list(range(1,frames+1)):raise ValueError('Missing or reused scene generation')
    for generation in range(1,frames+1):
        events=[r['event'] for r in rows if r['generation']==generation]
        required=['frame_open','captured','drain_begin','worker_done','drained','post_frame']
        if any(events.count(e)!=1 for e in required):raise ValueError('Missing or repeated native lifetime event')
        chains=[['frame_open','captured','drain_begin','drained','post_frame'],['captured','worker_done','drained']]
        if not dedicated:chains.append(['drain_begin','worker_done'])
        if any([events.index(e) for e in chain]!=sorted(events.index(e) for e in chain) for chain in chains):raise ValueError('Native cleanup passed unfinished GPU work')
        done=next(r for r in rows if r['generation']==generation and r['event']=='worker_done')
        if type(done['count']) is not int or done['count']<1 or not 0<=done['blocked']<=done['count']:raise ValueError('No native GPU queries')
        if dedicated:
            group=[r for r in rows if r['generation']==generation]
            if any(r.get('dedicated')!=1 for r in group):raise ValueError('Dedicated queue was not enabled')
            for name in ('captured','worker_begin','worker_done'):
                matches=[r for r in group if r['event']==name]
                if len(matches)!=1:raise ValueError('Missing dedicated service event')
                r=matches[0];slots=r.get('native_slots',0)
                if slots<1 or r.get('worker_queue')!=slots or not 0<=r.get('source_queue',-1)<slots:raise ValueError('Native and dedicated queue slots alias')
            if events.count('stop_requested')!=1 or not events.index('captured')<events.index('worker_begin')<events.index('worker_done'):raise ValueError('Invalid dedicated service order')
            if not events.index('stop_requested')<events.index('drain_begin'):raise ValueError('Drain preceded native stop')
            captured=next(r for r in group if r['event']=='captured')
            if done.get('iterations')!=4096 or done['count']!=4096*captured['count']:raise ValueError('Incomplete dedicated replay')
            progress=done.get('native_progress',0)
            if type(progress) is not int or progress<0 or events.count('native_progress')!=int(progress>0):raise ValueError('Invalid native progress count')
            if progress and not events.index('worker_begin')<events.index('native_progress')<min(events.index('worker_done'),events.index('stop_requested')):raise ValueError('No native progress during active service')
        # Mutation and destruction must follow a completed drain if this generation had work.
        if any(events.index(e)<events.index('drained') for e in ('update_scene','update_scene_binary','update_geometry','context_teardown','accelerator_rebuild') if e in events):raise ValueError('Scene mutation before drain')
    counts={name:sum(r['event']==name for r in rows) for name in ('accelerator_rebuild','context_teardown','update_scene')}
    if counts['context_teardown']<1 or counts['accelerator_rebuild']<1 or (updated and (counts['update_scene']!=1 or counts['context_teardown']<2 or counts['accelerator_rebuild']<3)):raise ValueError('Native lifecycle coverage incomplete')
    progress=sum(r.get('native_progress',0) for r in rows if r['event']=='worker_done')
    if require_progress and (not dedicated or progress<1):raise ValueError('No active native rendering overlapped service')
    return dict(status='passed',dedicated=dedicated,native_progress=progress,frames=frames,queries=sum(r['count'] for r in rows if r['event']=='worker_done'),blocked=sum(r['blocked'] for r in rows if r['event']=='worker_done'),boundaries=counts)

def validate_cancel(log,code,lifetime):
    import re
    from xpu2.reference import log_metrics
    metrics=log_metrics(log)
    threads=re.findall(r'numRenderThreads:(\d+)',log)
    if (code!=0 or '@@MODO_SESSION CANCELED 0' not in log or '@@MODO_SESSION DONE 0' in log or threads!=['1'] or not metrics['xpu_selected'] or not metrics['gpu_setup_complete'] or metrics['cpu_fallback'] or metrics['gpu_error'] or lifetime.get('status')!='passed' or lifetime.get('queries',0)<1):
        raise ValueError('Invalid cancelled native XPU session')
    return dict(metrics,passed=True,actual_threads=1,completion='cancelled',gpu_evidence='Completed native OptiX replay, not finished-frame percentage')
