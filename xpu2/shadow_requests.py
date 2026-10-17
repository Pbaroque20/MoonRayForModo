"""Fail-closed aggregate validation for the native borrowed-scene shadow adapter."""
import json

def summarize(trace):
    rows=[json.loads(line.split('XPU2_SHADOW_REQUEST ',1)[1]) for line in trace.splitlines() if line.startswith('XPU2_SHADOW_REQUEST ')]
    if not rows: raise ValueError('No shadow request batches')
    keys=('requests','rejected','stale_rejected','field_mismatches','gpu_mismatches','cpu_mismatches','cpu_reference_mismatches','blocked','lights')
    for row in rows:
        if any(type(row.get(k)) is not int or row[k]<0 for k in keys):raise ValueError('Malformed shadow counters')
        if row['cpu_mismatches']>row['requests'] or row['blocked']>row['requests']:raise ValueError('Invalid blocked count')
        if row['requests'] and not row['lights']:raise ValueError('Missing light bindings')
        if row['stale_rejected']!=row['requests']:raise ValueError('Stale binding accepted')
        if any(row[k] for k in ('rejected','field_mismatches','gpu_mismatches','cpu_reference_mismatches')):raise ValueError('Shadow request parity failed')
    sums={k:sum(r[k] for r in rows) for k in keys}
    if not sums['requests']:raise ValueError('No replayed shadow requests')
    differences=[json.loads(line.split('XPU2_SHADOW_DISAGREEMENT ',1)[1]) for line in trace.splitlines() if line.startswith('XPU2_SHADOW_DISAGREEMENT ')]
    if len(differences)!=sums['cpu_mismatches']:raise ValueError('Missing backend disagreement evidence')
    for difference in differences:
        if any(type(difference.get(k)) is not int or difference[k] not in (0,1) for k in ('cpu','native_cpu','gpu','native_gpu')):raise ValueError('Invalid backend evidence')
        if difference['cpu']!=difference['native_cpu'] or difference['gpu']!=difference['native_gpu'] or difference['cpu']==difference['gpu']:raise ValueError('Backend evidence does not match native paths')
    return dict(sums,batches=len(rows),visible=sums['requests']-sums['blocked'],status='passed',backend_parity='failed' if sums['cpu_mismatches'] else 'passed')
