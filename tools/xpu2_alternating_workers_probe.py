"""Compare actual AVX8/CUDA Lambert workers under three ownership policies."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from xpu2.reference import digest_file
from xpu2.correlated_state import decode
from xpu2 import profile_patch, window_dispatch_patch, async_transfer_patch, packed_readback_patch
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity


def summarize(rows):
    if len(rows) != 80:
        raise ValueError('Expected 80 matched runs')
    summaries = []
    for workers in (1, 6):
        for size in (8, 128):
            group = [r for r in rows if r['workers'] == workers and r['samples_per_job'] == size]
            if len({r['digest'] for r in group}) != 1:
                raise ValueError('Schedule-dependent samples')
            for policy in ('cpu', 'barrier', 'alternating', 'shared'):
                selected = [r for r in group if r['policy'] == policy]
                if sorted(r['repeat'] for r in selected) != list(range(5)):
                    raise ValueError('Missing/duplicate trial')
                for r in selected:
                    if r['wall_ns'] <= 0 or r['cpu_jobs'] + r['gpu_jobs'] != 1024:
                        raise ValueError('Invalid work/time')
                    if min(r['cpu_jobs'], r['gpu_jobs'], r['cpu_busy_ns'], r['gpu_busy_ns']) < 0:
                        raise ValueError('Negative accounting')
                    if r['cpu_busy_ns'] > r['wall_ns'] * workers or r['gpu_busy_ns'] > r['wall_ns']:
                        raise ValueError('Invalid busy time')
                    if policy == 'cpu' and r['gpu_jobs']:
                        raise ValueError('CPU control used GPU')
                    if policy in ('barrier', 'alternating') and (r['cpu_jobs'], r['gpu_jobs'], r['swaps']) != (512, 512, 960):
                        raise ValueError('Incorrect ownership alternation')
                summaries.append(dict(workers=workers, samples_per_job=size, policy=policy,
                    median_ms=statistics.median(r['wall_ns'] for r in selected)/1e6,
                    range_ms=[min(r['wall_ns'] for r in selected)/1e6, max(r['wall_ns'] for r in selected)/1e6],
                    gpu_jobs=[r['gpu_jobs'] for r in selected]))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'native', 'runtime', 'capture', 'ptx', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    a = parser.parse_args()
    a = argparse.Namespace(**{k: v.resolve() for k, v in vars(a).items()})
    if a.output.is_relative_to(a.source):
        parser.error('Output must be outside shared checkout')
    decode(a.capture.read_bytes())
    a.output.mkdir(parents=True, exist_ok=False)
    names = ['alternating_workers_probe.cc', 'native_lambert_queue.cc', 'batched_bridge.cc',
             'profile_metrics.h', 'profile_patch.py', 'window_dispatch_patch.py', 'async_transfer_patch.py', 'packed_readback_patch.py']
    inputs = [ROOT/'xpu2'/n for n in names] + [Path(__file__).resolve(), a.capture, a.ptx,
        a.native/'lambert_sample.obj', a.native/'link.rsp']
    # Freeze/link the retained original native objects; never rebuild shared code.
    link_inputs = [Path(line.strip().strip('"')) for line in (a.native/'link.rsp').read_text().splitlines()
                   if line.strip().strip('"').lower().endswith(('.obj', '.o', '.a'))]
    inputs += [p for p in link_inputs if p.is_file()]
    hashes = {str(p): digest_file(p) for p in inputs}
    report = dict(status='incomplete', scope='Owned native AVX8 / real CUDA Lambert stage jobs. Captured inputs are replayed; no ray continuation, film, adaptive sampling or renderer speed claim.',
                  source_hashes=hashes, gpu=gpu_identity())
    try:
        bridge = profile_patch.apply((ROOT/'xpu2/native_lambert_queue.cc').read_text(), (ROOT/'xpu2/batched_bridge.cc').read_text(), (ROOT/'xpu2/profile_metrics.h').read_text())
        bridge = packed_readback_patch.apply(async_transfer_patch.apply(window_dispatch_patch.apply(bridge)))
        cpp = a.output/'alternating.cc'
        cpp.write_text((ROOT/'xpu2/alternating_workers_probe.cc').read_text(encoding='utf-8-sig').replace('#include "batched_bridge.cc"', bridge))
        compiler = a.source/'toolchain/msys64/ucrt64/bin/g++.exe'
        env = environment(a.runtime, a.output)
        env['PATH'] = str(compiler.parent)+os.pathsep+env['PATH']
        exe = a.output/'alternating.exe'
        pp = a.output/'alternating.ii'
        flags = ['-std=c++17', '-O2', '-mavx', '-mno-avx2', '-mno-fma', '-ffp-contract=off', '-pthread',
                 '-I'+str(a.source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
        for label, args in [('preprocess', ['-E', str(cpp), '-o', str(pp)]),
                            ('link', [str(pp), str(a.native/'lambert_sample.obj'), '@'+str(a.native/'link.rsp'), '-o', str(exe)])]:
            print(label, flush=True)
            done = subprocess.run([str(compiler), *flags, *args], env=env, capture_output=True, text=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
            (a.output/(label+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:
                raise ValueError(label+' failed: '+done.stderr[-2500:])
        report.update(compiler_sha256=digest_file(compiler), executable_sha256=digest_file(exe), preprocessed_sha256=digest_file(pp))
        env.update(XPU2_NATIVE_LAMBERT='replace', XPU2_NATIVE_LAMBERT_PTX=str(a.ptx),
                   XPU2_PROFILE_FILE=str(a.output/'profile.json'), XPU2_PROFILE_QUIET='1', XPU2_QUEUE_CAPACITY='64',
                   XPU2_QUEUE_COALESCE_US='0', XPU2_WINDOW_DISPATCH='1', XPU2_ASYNC_TRANSFERS='1', XPU2_PACKED_READBACK='1', XPU2_SHADER_AUDIT='1')
        print('Measuring alternating and shared workers', flush=True)
        done = subprocess.run([str(exe), str(a.capture)], env=env, cwd=a.output, capture_output=True, text=True, timeout=180, creationflags=subprocess.CREATE_NO_WINDOW)
        (a.output/'process.log').write_text(done.stdout+done.stderr)
        if done.returncode:
            raise ValueError('Experiment failed: '+done.stderr[-2000:])
        results = json.loads(done.stdout)
        if not results['passed'] or not results['gpu_samples']:
            raise ValueError('GPU validation missing')
        report.update(results=results, summary=summarize(results['runs']), profile=json.loads((a.output/'profile.json').read_text()))
        if report['profile']['audit_samples'] != results['gpu_samples']:
            raise ValueError('GPU audit missing')
        if hashes != {str(p): digest_file(p) for p in inputs} or report['gpu'] != gpu_identity():
            raise ValueError('Input/device drift')
        report['status'] = 'passed'
        print(json.dumps(report['summary'], indent=2))
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
