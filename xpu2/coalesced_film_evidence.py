"""Evidence gates for bounded native-worker coalescing (not path migration)."""
from xpu2.fused_film_evidence import validate_fused


def validate_queue(q,p,mode,threads):
    keys=('submitted','returned','declined','batches','combined','max_jobs','max_slots','max_outstanding','during_service','exceptions')
    if any(type(q.get(k)) is not int or q[k]<0 for k in keys):raise ValueError('Incomplete queue evidence')
    result=validate_fused(p,mode)
    if not q['submitted'] or q['submitted']!=q['returned'] or q['declined'] or q['exceptions']:raise ValueError('Unreturned or failed queue jobs')
    if not 1<=q['batches']<=q['submitted'] or q['batches']!=p['calls']:raise ValueError('Queue/device batch accounting')
    if not 1<=q['max_jobs']<=16 or not 1<=q['max_slots']<=128 or not 1<=q['max_outstanding']<=16:raise ValueError('Queue capacity exceeded')
    if q['max_slots']!=p['max_slots'] or q['combined']>q['batches'] or q['during_service']>q['submitted']:raise ValueError('Invalid aggregation evidence')
    if threads==1:
        if q['combined'] or q['max_jobs']!=1 or q['batches']!=q['submitted']:raise ValueError('Single caller unexpectedly combined')
    elif not q['combined'] or q['max_jobs']<2 or not q['during_service']:raise ValueError('Concurrent coalescing not exercised')
    return dict(result,submitted=q['submitted'],batches=q['batches'],combined=q['combined'],during_service=q['during_service'])
