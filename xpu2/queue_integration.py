"""Verify bounded native queue publication and distinguish image repeatability."""
import json


def verify(log, gpu_samples, full=False):
    rows=[json.loads(x) for x in log.splitlines() if x.startswith('{')]
    summaries=[r for r in rows if 'calls' in r]
    deliveries=[r for r in rows if 'delivered_id' in r]
    if not summaries:raise ValueError('Missing queue summary')
    r=summaries[-1]
    fields={'calls','submitted','delivered','cpu_batches','queue_full','timeouts','late_discarded','worker_failures','worker_batches',
            'max_batch_samples','max_queue','cpu_completed_while_gpu_pending','kernel_window_cpu_observations','kernel_microseconds'}
    if set(r) not in (fields,fields|{'cancelled_before_dispatch'},fields|{'cancelled_before_dispatch','closed_fallback'}) or any(type(v) is not int or v<0 for v in r.values()):raise ValueError('Invalid queue counters')
    if r['calls']!=r['submitted']+r['cpu_batches']+r['queue_full']+r.get('closed_fallback',0):raise ValueError('Unaccounted request')
    if r['submitted']!=r['delivered'] or r['timeouts'] or r['late_discarded'] or r['worker_failures'] or r.get('cancelled_before_dispatch',0) or r.get('closed_fallback',0):raise ValueError('Incomplete or failed publication')
    if r['max_queue']>64 or r['max_batch_samples']>512 or r['worker_batches']>r['submitted']:raise ValueError('Queue capacity violation')
    ids=[];samples=0
    for row in deliveries:
        if set(row)!={'delivered_id','samples'} or type(row['delivered_id']) is not int or not 0<=row['delivered_id']<r['calls'] or type(row['samples']) is not int or not 1<=row['samples']<=8:raise ValueError('Invalid request delivery')
        ids.append(row['delivered_id']);samples+=row['samples']
    if len(ids)!=r['delivered'] or len(set(ids))!=len(ids):raise ValueError('Missing or duplicate publication')
    if gpu_samples is not None and samples!=gpu_samples:raise ValueError('Unaccounted shader samples')
    if full:
        if not r['queue_full'] or r['submitted'] or r['max_queue']:raise ValueError('Queue-full fallback not exercised')
    elif not r['submitted']:raise ValueError('No queued GPU requests')
    return dict(r,unique_deliveries=len(ids),delivered_samples=samples,passed=True)
