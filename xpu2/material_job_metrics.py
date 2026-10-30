"""Prospective exact-word gates and sampled CPU frame-cost accounting."""
import csv
import math
import struct

METRICS = ('max_abs', 'rms', 'mean_abs', 'abs_signed_mean', 'different_words_fraction')

def compare(reference, actual):
    if reference['dimensions'] != actual['dimensions'] or reference['metadata'] != actual['metadata']:
        raise ValueError('Image layout or metadata mismatch')
    count = math.prod(reference['dimensions'])
    result = {}
    if count <= 0 or set(reference['channels']) != set('RGBA') or set(actual['channels']) != set('RGBA'):
        raise ValueError('Missing image channels')
    for channel in 'RGBA':
        a, b = reference['channels'][channel], actual['channels'][channel]
        if len(a) != count or len(b) != count or not all(math.isfinite(x) for x in (*a, *b)):
            raise ValueError('Invalid/nonfinite image')
        delta = [x-y for x,y in zip(a,b)]
        words = sum(struct.pack('<f', x) != struct.pack('<f', y) for x,y in zip(a,b))
        result[channel] = dict(max_abs=max(map(abs, delta)), rms=math.sqrt(math.fsum(x*x for x in delta)/count),
            mean_abs=math.fsum(map(abs, delta))/count, abs_signed_mean=abs(math.fsum(delta)/count),
            different_words_fraction=words/count, different_words=words)
    return result

def envelope(references):
    if len(references) != 5:
        raise ValueError('Five reference repeats required by frozen protocol')
    pairs = [compare(a,b) for i,a in enumerate(references) for b in references[i+1:]]
    return {c:{m:max(pair[c][m] for pair in pairs) for m in METRICS} for c in 'RGBA'}

def qualified(comparisons, bound=None):
    if not comparisons:
        raise ValueError('Missing comparisons')
    if bound is None:
        return all(row[c]['different_words'] == 0 for row in comparisons for c in 'RGBA')
    return all(row[c][m] <= bound[c][m] for row in comparisons for c in 'RGBA' for m in METRICS)

def cpu_totals(path):
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError('Missing CPU scope rows')
    stages = {}
    for row in rows:
        v = {k:int(row[k]) for k in ('thread','calls','lanes','sampled_calls','sampled_lanes','exclusive_ns','errors','active','rate')}
        if any(x < 0 for x in v.values()) or v['errors'] or v['active'] or not v['rate']:
            raise ValueError('Invalid/overlapping sampled scopes')
        if v['sampled_calls'] > v['calls'] or v['sampled_lanes'] > v['lanes']:
            raise ValueError('Impossible sample counts')
        entry = stages.setdefault(row['stage'], dict(estimated_worker_seconds=0., measured_sample_seconds=0., lanes=0, sampled_lanes=0, calls=0, sampled_calls=0, workers=[]))
        entry['estimated_worker_seconds'] += v['exclusive_ns'] * v['rate'] / 1e9
        entry['measured_sample_seconds'] += v['exclusive_ns'] / 1e9
        for key in ('lanes','sampled_lanes','calls','sampled_calls'):
            entry[key] += v[key]
        if v['calls']:
            entry['workers'].append(v['thread'])
    required = ('material_construct_maps','all_lobes_mis','light_sample_eval','light_tree')
    if any(s not in stages for s in required):
        raise ValueError('Full disjoint material and lighting scopes required')
    if any(stages[s]['lanes'] and not stages[s]['sampled_lanes'] for s in required):
        raise ValueError('Unsampled nonempty required stage')
    for entry in stages.values():
        entry['ns_per_sampled_lane'] = entry['measured_sample_seconds']*1e9/entry['sampled_lanes'] if entry['sampled_lanes'] else None
        entry['lane_weighted_worker_seconds'] = entry['measured_sample_seconds']*entry['lanes']/entry['sampled_lanes'] if entry['sampled_lanes'] else None
    return dict(stages=stages, material_maps_worker_seconds=stages['material_construct_maps']['estimated_worker_seconds'],
        selected_lighting_worker_seconds=sum(stages[s]['estimated_worker_seconds'] for s in required[1:]))
