"""Validate ordering at real native frame and accelerator lifetime boundaries."""
import json

def validate(trace,frames,updated=False):
    rows=[json.loads(line.split('XPU2_NATIVE_DRAIN ',1)[1]) for line in trace.splitlines() if line.startswith('XPU2_NATIVE_DRAIN ')]
    if not rows or any(row.get('error') or row.get('mismatches') for row in rows):raise ValueError('Native drain error or visibility mismatch')
    opens=[r for r in rows if r['event']=='frame_open']
    if len(opens)!=frames or [r['generation'] for r in opens]!=list(range(1,frames+1)):raise ValueError('Missing or reused scene generation')
    for generation in range(1,frames+1):
        events=[r['event'] for r in rows if r['generation']==generation]
        required=['frame_open','captured','drain_begin','worker_done','drained','post_frame']
        if any(events.count(e)!=1 for e in required) or [events.index(e) for e in required]!=sorted(events.index(e) for e in required):raise ValueError('Native cleanup passed unfinished GPU work')
        done=next(r for r in rows if r['generation']==generation and r['event']=='worker_done')
        if type(done['count']) is not int or done['count']<1 or not 0<=done['blocked']<=done['count']:raise ValueError('No native GPU queries')
        # Mutation and destruction must follow a completed drain if this generation had work.
        if any(events.index(e)<events.index('drained') for e in ('update_scene','update_scene_binary','update_geometry','context_teardown','accelerator_rebuild') if e in events):raise ValueError('Scene mutation before drain')
    counts={name:sum(r['event']==name for r in rows) for name in ('accelerator_rebuild','context_teardown','update_scene')}
    if counts['context_teardown']<1 or counts['accelerator_rebuild']<1 or (updated and (counts['update_scene']!=1 or counts['context_teardown']<2 or counts['accelerator_rebuild']<3)):raise ValueError('Native lifecycle coverage incomplete')
    return dict(status='passed',frames=frames,queries=sum(r['count'] for r in rows if r['event']=='worker_done'),blocked=sum(r['blocked'] for r in rows if r['event']=='worker_done'),boundaries=counts)

def validate_cancel(log,code,lifetime):
    import re
    from xpu2.reference import log_metrics
    metrics=log_metrics(log)
    threads=re.findall(r'numRenderThreads:(\d+)',log)
    if (code!=0 or '@@MODO_SESSION CANCELED 0' not in log or '@@MODO_SESSION DONE 0' in log or threads!=['1'] or not metrics['xpu_selected'] or not metrics['gpu_setup_complete'] or metrics['cpu_fallback'] or metrics['gpu_error'] or lifetime.get('status')!='passed' or lifetime.get('queries',0)<1):
        raise ValueError('Invalid cancelled native XPU session')
    return dict(metrics,passed=True,actual_threads=1,completion='cancelled',gpu_evidence='Completed native OptiX replay, not finished-frame percentage')
