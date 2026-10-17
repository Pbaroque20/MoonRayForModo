"""Small reference path tracer isolating sampler/AVX8 shader migration.

Geometry, ray origins, throughput, and film are shared Python reference code.
Only the real native/CUDA callbacks sample and shade. This is NOT the MoonRay
integrator, Embree/OptiX traversal, asynchronous execution, or a speed benchmark.
"""
import gzip
import hashlib
import json
import math
import random
import struct
from .cuda_window_samples import packet
from .shading_exchange import SIZE, WORDS, material_status

WIDTH, HEIGHT, SPP, BOUNCES = 32, 24, 4, 4
SPHERES = (((-.6, .65, -.2), .65, (.72, .32, .12)),
           ((.65, .45, -.7), .45, (.18, .42, .72)))
# axis, position, other-coordinate bounds, inward normal, albedo, emission
PLANES = ((1, 0., (-2., 2., -2., 3.), (0., 1., 0.), (.7, .7, .7), (0., 0., 0.)),
          (1, 3., (-1.5, 1.5, -1.5, 2.5), (0., -1., 0.), (0., 0., 0.), (4., 3.5, 3.)),
          (2, -2., (-2., 2., 0., 3.), (0., 0., 1.), (.7, .7, .7), (0., 0., 0.)),
          (0, -2., (0., 3., -2., 3.), (1., 0., 0.), (.7, .15, .12), (0., 0., 0.)),
          (0, 2., (0., 3., -2., 3.), (-1., 0., 0.), (.12, .6, .18), (0., 0., 0.)))
SKY = (.16, .2, .28)


def f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def unit(v):
    length = math.sqrt(dot(v, v))
    return tuple(f32(x/length) for x in v)


def trace(origin, direction, omit_spheres=False):
    """Nearest analytic surface; only the fixed, metre-scale fixture is supported."""
    hits = []
    if not omit_spheres:
        for index, (center, radius, albedo) in enumerate(SPHERES):
            delta = tuple(x-y for x, y in zip(origin, center))
            a, b = dot(direction, direction), dot(delta, direction)
            disc = b*b-a*(dot(delta, delta)-radius*radius)
            if disc < 0: continue
            for t in ((-b-math.sqrt(disc))/a, (-b+math.sqrt(disc))/a):
                if t > 1e-5:
                    pos = tuple(f32(o+t*d) for o, d in zip(origin, direction))
                    normal = unit(tuple(x-y for x, y in zip(pos, center)))
                    hits.append((t, index, pos, normal, albedo, (0., 0., 0.)))
                    break
    for index, (axis, value, bounds, normal, albedo, emission) in enumerate(PLANES, 2):
        if abs(direction[axis]) < 1e-12: continue
        t = (value-origin[axis])/direction[axis]
        if t <= 1e-5: continue
        pos = tuple(f32(o+t*d) for o, d in zip(origin, direction))
        coords = [pos[i] for i in range(3) if i != axis]
        if bounds[0] <= coords[0] <= bounds[1] and bounds[2] <= coords[1] <= bounds[3]:
            hits.append((t, index, pos, normal, albedo, emission))
    return min(hits, key=lambda h: (h[0], h[1])) if hits else None


def sample_state(path_id):
    # Fixed diagnostic sequence mapping, not MoonRay's production integrator schedule.
    pixel, sample = divmod(path_id, SPP)
    y, x = divmod(pixel, WIDTH)
    start = 1014 if sample % 2 == 0 else 1022
    return packet([0x32555058, 2, 2, 2, 0xffffffff, start, 0, 6,
                   2, (y << 16) | x, sample, 1, 0, 131, start-6])


def shade_packet(sampler, normal, outgoing, albedo):
    material = (struct.pack('<2I', 0x32535058, 1) +
                struct.pack('<12f', *normal, *normal, *outgoing, 0., 0., 0.) +
                struct.pack('<6f', *albedo, 1., 1., 1.) +
                struct.pack('<4I', 1, 1, 0, 0))
    if material_status(material): raise ValueError('Invalid fixture material')
    return struct.pack('<4I', 0x31485358, 1, 1, 0) + sampler + material + bytes(32)


def film(samples):
    if len(samples) != WIDTH*HEIGHT*SPP: raise ValueError('Incomplete film')
    values = []
    for pixel in range(WIDTH*HEIGHT):
        for channel in range(3):
            total = 0.
            for sample in samples[pixel*SPP:(pixel+1)*SPP]:
                total = f32(total+sample[channel])
            values.append(f32(total/SPP))
    if not all(math.isfinite(v) and v >= 0 for v in values): raise ValueError('Invalid film')
    return struct.pack('<%df' % len(values), *values)


def render(dispatch, omit_secondary_spheres=False):
    paths = []
    for path_id in range(WIDTH*HEIGHT*SPP):
        pixel, sample = divmod(path_id, SPP)
        y, x = divmod(pixel, WIDTH)
        sx, sy = sample % 2, sample // 2
        target = ((2*(x+(sx+.5)/2)/WIDTH-1)*2.,
                  1.25+(1-2*(y+(sy+.5)/2)/HEIGHT)*1.5, -1.)
        origin = (0., 1.25, 4.)
        direction = unit(tuple(t-o for t, o in zip(target, origin)))
        paths.append({'id': path_id, 'origin': origin, 'direction': direction,
                      'beta': (1., 1., 1.), 'sampler': sample_state(path_id)})
    samples = [(0., 0., 0.) for _ in paths]
    records, coverage = {}, {'emitter': 0, 'sky': 0, 'invalid': 0, 'zero_pdf': 0,
                            'bounce_limit': 0, 'secondary_sphere_hits': 0, 'surface_hits': {}}
    for bounce in range(BOUNCES+1):
        shade, active = [], []
        for path in paths:
            hit = trace(path['origin'], path['direction'], omit_secondary_spheres and bounce > 0)
            key = '%d:%d' % (path['id'], bounce)
            row = {'origin': path['origin'], 'direction': path['direction'], 'beta': path['beta'],
                   'sampler': path['sampler'].hex(), 'hit': None if hit is None else hit[1:]}
            records[key] = row
            emission = SKY if hit is None else hit[5]
            if hit is None or any(emission):
                coverage['sky' if hit is None else 'emitter'] += 1
                samples[path['id']] = tuple(f32(b*e) for b, e in zip(path['beta'], emission))
                row['contribution'] = samples[path['id']]
                continue
            obj = str(hit[1])
            coverage['surface_hits'][obj] = coverage['surface_hits'].get(obj, 0)+1
            if bounce and hit[1] < 2: coverage['secondary_sphere_hits'] += 1
            if bounce == BOUNCES:
                coverage['bounce_limit'] += 1
                continue
            normal, outgoing = hit[3], tuple(-v for v in path['direction'])
            state = shade_packet(path['sampler'], normal, outgoing, hit[4])
            shade.append({'input': state, 'length': SIZE, 'id': path['id'], 'bounce': bounce})
            active.append((path, hit, row))
        if not shade: break
        returned, words = dispatch(shade, bounce)
        if len(returned) != SIZE*len(shade) or len(words) != WORDS*len(shade):
            raise ValueError('Truncated image shading result')
        paths = []
        for i, (path, hit, row) in enumerate(active):
            result = list(words[i*WORDS:(i+1)*WORDS])
            state = returned[i*SIZE:(i+1)*SIZE]
            if result[0] != 0: raise ValueError('Unresolved image shading status')
            row['returned'] = state.hex()
            row['result'] = result
            wi = struct.unpack('<3f', struct.pack('<3I', *result[4:7]))
            value = struct.unpack('<3f', struct.pack('<3I', *result[7:10]))
            pdf = struct.unpack('<f', struct.pack('<I', result[10]))[0]
            if not all(math.isfinite(v) for v in (*wi, *value, pdf)) or pdf < 0 or result[11] not in (0, 1):
                raise ValueError('Invalid shader result')
            if result[11]: coverage['invalid'] += 1; continue
            if pdf == 0: coverage['zero_pdf'] += 1; continue
            # includeCosine=true: shader returns f*cos, so no extra cosine factor.
            path['beta'] = tuple(f32(b*f32(v/pdf)) for b, v in zip(path['beta'], value))
            if not all(math.isfinite(v) and v >= 0 for v in path['beta']): raise ValueError('Invalid throughput')
            path['sampler'], path['direction'] = state[16:80], wi
            # Fixture-only offset, not a proposed production ray-origin correction.
            path['origin'] = tuple(f32(p+n*1e-4) for p, n in zip(hit[2], hit[3]))
            paths.append(path)
    return film(samples), records, coverage


def compare(reference, candidate):
    a, ar, ac = reference
    b, br, bc = candidate
    if len(a) != len(b): raise ValueError('Mismatched film dimensions')
    floats_a = struct.unpack('<%df' % (len(a)//4), a)
    floats_b = struct.unpack('<%df' % (len(b)//4), b)
    # Canonical serialization also catches a changed +/- zero or float bit value.
    canonical = lambda r: json.dumps(r, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    mismatches = sum(canonical(ar[k]) != canonical(br[k]) for k in ar.keys() & br.keys())
    missing = len(ar.keys() ^ br.keys())
    return {'passed': a == b and not mismatches and not missing and ac == bc,
            'different_rgb_components': sum(a[i:i+4] != b[i:i+4] for i in range(0, len(a), 4)),
            'max_rgb_error': max(abs(x-y) for x, y in zip(floats_a, floats_b)),
            'different_path_events': mismatches, 'missing_path_events': missing,
            'film_sha256': hashlib.sha256(b).hexdigest(),
            'trajectory_sha256': hashlib.sha256(canonical(br)).hexdigest()}


def run(cpu, gpu, out):
    out.mkdir()
    baseline = render(lambda batch, bounce: cpu(batch, 1))
    raw = json.dumps(baseline[1], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    (out/'native-trajectory.json.gz').write_bytes(gzip.compress(raw, mtime=0))
    (out/'native.rgb32f').write_bytes(baseline[0])
    rgb = struct.unpack('<%df' % (len(baseline[0])//4), baseline[0])
    pixels = bytes(round(255*(min(1., v)**(1/2.2))) for v in rgb)
    (out/'native.ppm').write_bytes(('P6\n%d %d\n255\n' % (WIDTH, HEIGHT)).encode()+pixels)
    reports = []
    for plan in ('native_workers4', 'gpu', 'gpu_fallback', 'alternating', 'shuffled'):
        counts = {'cpu': 0, 'gpu': 0, 'cpu_to_gpu': 0, 'gpu_to_cpu': 0, 'fallback': 0}
        last = {}
        def dispatch(batch, bounce):
            order = list(range(len(batch)))
            if plan == 'shuffled': random.Random(313+bounce).shuffle(order)
            groups = {}
            for i in order:
                pid = batch[i]['id']
                device = 0 if plan == 'native_workers4' else 1 if plan in ('gpu', 'gpu_fallback') else (pid+bounce)%2
                fallback = plan != 'gpu' and device == 1 and pid % 11 == 0 and bounce in (1, 2)
                groups.setdefault((device, fallback), []).append(i)
            states, results = [None]*len(batch), [None]*len(batch)
            for (device, fallback), indices in groups.items():
                subset = [batch[i] for i in indices]
                if fallback:
                    st, ws = gpu(subset, 64, bounce != 1, bounce != 2)
                    if st != b''.join(r['input'] for r in subset) or list(ws) != [v for _ in subset for v in [1]+[0]*11]:
                        raise ValueError('Image fallback advanced or corrupted state')
                    counts['fallback'] += len(subset)
                    device = 0
                st, ws = cpu(subset, 4) if device == 0 else gpu(subset, 64 if plan == 'gpu' else 128, True, True)
                if len(st) != SIZE*len(subset) or len(ws) != WORDS*len(subset): raise ValueError('Truncated image batch')
                counts['cpu' if device == 0 else 'gpu'] += len(subset)
                for j, i in enumerate(indices):
                    states[i], results[i] = st[j*SIZE:(j+1)*SIZE], list(ws[j*WORDS:(j+1)*WORDS])
                    pid = batch[i]['id']
                    if pid in last and last[pid] != device:
                        counts['cpu_to_gpu' if device else 'gpu_to_cpu'] += 1
                    last[pid] = device
            return b''.join(states), [v for r in results for v in r]
        candidate = render(dispatch)
        (out/(plan+'.rgb32f')).write_bytes(candidate[0])
        comparison = compare(baseline, candidate)
        if not comparison['passed']:
            failed = json.dumps(candidate[1], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            (out/(plan+'-failed-trajectory.json.gz')).write_bytes(gzip.compress(failed, mtime=0))
        reports.append({'plan': plan, **comparison, **counts})
    # Prove this fixture observes secondary visibility rather than only primary color.
    control = render(lambda batch, bounce: cpu(batch, 1), omit_secondary_spheres=True)
    sensitivity = compare(baseline, control)
    coverage = baseline[2]
    adequate = (coverage['emitter'] > 0 and coverage['sky'] > 0 and
                coverage['secondary_sphere_hits'] > 0 and coverage['bounce_limit'] > 0 and
                len(coverage['surface_hits']) == 6 and sensitivity['different_rgb_components'] > 0)
    schedules = all(r['cpu_to_gpu'] and r['gpu_to_cpu'] and r['fallback'] for r in reports if r['plan'] in ('alternating', 'shuffled'))
    return {'passed': bool(adequate and schedules and all(r['passed'] for r in reports)),
            'scope': 'Custom host reference traversal and film; real native AVX8/CUDA sampler and Lambert shading; not MoonRay image parity or a performance benchmark',
            'dimensions': [WIDTH, HEIGHT], 'spp': SPP, 'max_scattering_bounces': BOUNCES,
            'coverage': coverage, 'path_events': len(baseline[1]), 'plans': reports,
            'secondary_visibility_negative_control': sensitivity,
            'baseline_trajectory_sha256': hashlib.sha256(raw).hexdigest(),
            'renderer_migration_enabled': False}
