"""Exercise the owned texture -> CUDA Lambert -> CPU-resume pipeline (not a native render)."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from xpu2.reference import digest_file
from xpu2 import native_integration
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity

CASES = {
    'pipeline': (2, 0, 0, 2), 'missing_ptx': (2, 0, 0, 2),
    'admission_fallback': (2, 0, 0, 2), 'restart': (1, 0, 0, 2),
    'leased_restart': (1, 1, 0, 2), 'decode_failure': (0, 0, 1, 0),
    'prepare_failure': (0, 0, 1, 0), 'identity_failure': (0, 0, 1, 0),
    'capacity': (32, 0, 0, 32), 'close_pending': (0, 0, 0, 1),
    'nonfinite': (0, 0, 1, 0), 'ready_restart': (1, 0, 0, 2),
}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--ptx', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--fast-math', action='store_true', help='Check guards with the native renderer optimization mode')
    a = p.parse_args()
    source, ptx, out = a.source.resolve(), a.ptx.resolve(), a.output.resolve()
    if out.is_relative_to(source):
        p.error('Output must be outside the shared source checkout')
    out.mkdir(parents=True, exist_ok=False)
    files = [ROOT / ('xpu2/' + f) for f in [
        'shading_dispatch.h', 'shading_dispatch_probe.cc', 'continuation_mailbox.h',
        'native_lambert_queue.cc', 'texture_work.h', 'texture_async.h', 'texture_cache.h',
        'texture_dependencies.h', 'texture_residency.h', 'indexed_scene.h']]
    files += [Path(__file__).resolve(), ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz', ptx]
    identities = {str(f): digest_file(f) for f in files}
    report = {'status': 'incomplete', 'scope': 'Owned stage dispatcher with real CUDA Lambert; synthetic tint tiles and resume metadata; no native path restoration or rendered image',
              'sources': identities, 'gpu': gpu_identity(), 'runs': []}
    try:
        raw = gzip.decompress(files[-2].read_bytes())
        if hashlib.sha256(raw).hexdigest() != '39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3':
            raise ValueError('Native fixture changed')
        fixture = out/'reference.bin'
        fixture.write_bytes(raw)
        compiler = source/'toolchain/msys64/ucrt64/bin/g++.exe'
        headers = source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        flags = ['-std=c++17', '-O2', '-mavx', '-mno-avx2', '-mno-fma', '-ffp-contract=off', '-I'+str(headers)]
        if a.fast_math:
            flags.append('-ffast-math')
        report['compiler_flags'] = flags
        env = environment(compiler.parent, out)
        pp, exe = out/'shading.ii', out/'shading-dispatch.exe'
        for label, args in [('preprocess', ['-E', str(files[1]), '-o', str(pp)]), ('compile', [str(pp), '-o', str(exe)])]:
            run = subprocess.run([str(compiler), *flags, *args], env=env, capture_output=True, text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(run.stdout+run.stderr, encoding='utf-8')
            if run.returncode:
                raise ValueError(label+' failed: '+run.stderr[-3000:])
        report.update(compiler_sha256=digest_file(compiler), preprocessed_sha256=digest_file(pp), executable_sha256=digest_file(exe))
        for case, expected in CASES.items():
            folder = out/case
            folder.mkdir()
            runenv = environment(compiler.parent, folder)
            runenv.update(XPU2_NATIVE_LAMBERT='sentinel', XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if case=='missing_ptx' else ptx),
                          XPU2_NATIVE_LAMBERT_LOG=str(folder/'shader.log'), XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shader.bin'),
                          XPU2_QUEUE_CAPACITY='0' if case=='admission_fallback' else '64', XPU2_QUEUE_POLICY='all', XPU2_QUEUE_LOG=str(folder/'queue.log'))
            print('Shading dispatch: '+case, flush=True)
            run = subprocess.run([str(exe), case, str(fixture)], env=runenv, capture_output=True, text=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'process.log').write_text(run.stdout+run.stderr, encoding='utf-8')
            if run.returncode:
                raise ValueError(case+' failed: '+run.stderr)
            observed = json.loads(run.stdout)
            if not observed['passed'] or observed['outstanding'] or tuple(observed[k] for k in ('accepted','revoked','failed','dispatched')) != expected:
                raise ValueError('Unexpected dispatch accounting: '+case)
            if observed['admitted'] != sum(observed[k] for k in ('accepted','revoked','failed','cancelled','outstanding')):
                raise ValueError('Shading job lost its terminal outcome')
            if observed['cancelled'] != {'restart': 2, 'ready_restart': 1, 'close_pending': 1}.get(case, 0):
                raise ValueError('Unexpected shading cancellation count')
            shader = {}
            if (folder/'shader.log').exists():
                shader = native_integration.summary((folder/'shader.log').read_text())
                records = native_integration.records((folder/'shader.bin').read_bytes())
                if case=='missing_ptx':
                    if not shader['errors'] or shader['accepted'] or shader['replaced'] or shader['samples']!=16:
                        raise ValueError('Missing PTX did not preserve fallback')
                else:
                    native_integration.verify_counts(shader, records, 'replace')
                    if shader['samples'] < 8:
                        raise ValueError('No actual shader work')
            elif case not in ('admission_fallback','decode_failure','prepare_failure','identity_failure','nonfinite'):
                raise ValueError('Expected real GPU shader execution')
            rows = [json.loads(line) for line in (folder/'queue.log').read_text().splitlines() if line.startswith('{')]
            q = [r for r in rows if 'calls' in r][-1]
            ids = [r['delivered_id'] for r in rows if 'delivered_id' in r]
            if len(ids)!=len(set(ids)) or len(ids)!=q['delivered'] or q['retained_async'] or q['worker_failures']:
                raise ValueError('Duplicate delivery or leaked GPU work')
            if q['calls'] != q['submitted']+q['queue_full']+q['closed_fallback']+q['cpu_batches']:
                raise ValueError('Admission accounting failed')
            if q['submitted'] != q['delivered']+q['cancelled_requests']+q['timeouts']:
                raise ValueError('GPU terminal accounting failed')
            if q['cancelled_requests']+q['timeouts'] != q['late_discarded']+q['cancelled_before_dispatch']:
                raise ValueError('Cancellation accounting failed')
            report['runs'].append({'case':case, 'checks':observed, 'queue':q, 'shader':shader,
                                   'logs':{f.name:digest_file(f) for f in folder.iterdir() if f.is_file()}})
        if identities != {str(f):digest_file(f) for f in files} or report['gpu'] != gpu_identity():
            raise ValueError('Source/device changed during validation')
        if report['executable_sha256'] != digest_file(exe):
            raise ValueError('Executable changed')
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')

if __name__=='__main__':
    main()
