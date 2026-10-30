"""Evidence gates for the owned-scene prototype; no native scene lifetime claim."""
EXPECTED={'replace':(2,1,3),'restart':(2,1,1),'cancel':(1,0,1),'readers':(2,0,1)}
def validate(case,checks,queue):
    if case not in EXPECTED:raise ValueError('Unknown lifetime scenario')
    denied,accepted,destroyed=EXPECTED[case]
    expected=dict(case=case,denied=denied,accepted=accepted,destroyed=destroyed,wrong_thread_destroy=0,job_retention=True,passed=True)
    if checks!=expected or any(type(checks.get(k)) is not int for k in ('denied','accepted','destroyed','wrong_thread_destroy')) or type(checks.get('passed')) is not bool:raise ValueError('Incomplete scene lifetime checks')
    counters={'submitted':1,'delivered':int(case!='cancel'),'cancelled_requests':int(case=='cancel'),'late_discarded':int(case=='cancel'),'cancelled_before_dispatch':0,'retained_async':0,'worker_failures':0,'worker_batches':1,'max_batch_samples':8}
    if any(type(queue.get(k)) is not int or queue[k]!=v for k,v in counters.items()):raise ValueError('GPU work not completed and drained as expected')
    return {'status':'passed','scene_checks':checks,'gpu_drain':{k:queue[k] for k in counters}}
