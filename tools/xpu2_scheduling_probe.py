"""Measure independent CPU work overlapping real GPU batches; not a render benchmark."""
import argparse
import json
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


def summarize(runs):
    if not runs:
        raise ValueError('No scheduling measurements')
    result = []
    for steps in sorted({r['steps'] for r in runs}):
        rows = [r for r in runs if r['steps'] == steps]
        if len({r['digest'] for r in rows}) != 1:
            raise ValueError('Schedule-dependent numerical result')
        groups = {s: [r for r in rows if r['schedule'] == s] for s in ('serial', 'overlap')}
        if not all(groups.values()) or len(groups['serial']) != len(groups['overlap']):
            raise ValueError('Missing matched schedule')
        if len({r['rounds'] for r in rows}) != 1:
            raise ValueError('Unequal work')
        for schedule, group in groups.items():
            if sorted(r['repeat'] for r in group) != list(range(len(group))):
                raise ValueError('Missing or duplicate repetition')
            for row in group:
                for key in ('wall_ns', 'rounds'):
                    if type(row[key]) is not int or row[key] <= 0:
                        raise ValueError('Invalid duration/work count')
                for key in ('cpu_ns', 'collect_ns'):
                    if type(row[key]) is not int or not 0 <= row[key] <= row['wall_ns']:
                        raise ValueError('Invalid stage duration')
                for key in ('cpu_started_pending', 'cpu_finished_pending'):
                    if type(row[key]) is not int or not 0 <= row[key] <= row['rounds']:
                        raise ValueError('Invalid pending observation')
                    if schedule == 'serial' and row[key]:
                        raise ValueError('Serial control overlapped')
        med = {s: statistics.median(r['wall_ns'] for r in group) for s, group in groups.items()}
        result.append({'steps': steps, 'serial_ms': med['serial'] / 1e6,
                       'overlap_ms': med['overlap'] / 1e6, 'speedup': med['serial'] / med['overlap'],
                       'serial_range_ms': [min(r['wall_ns'] for r in groups['serial']) / 1e6, max(r['wall_ns'] for r in groups['serial']) / 1e6],
                       'overlap_range_ms': [min(r['wall_ns'] for r in groups['overlap']) / 1e6, max(r['wall_ns'] for r in groups['overlap']) / 1e6],
                       'overlap_cpu_started_pending': sum(r['cpu_started_pending'] for r in groups['overlap']),
                       'overlap_cpu_finished_pending': sum(r['cpu_finished_pending'] for r in groups['overlap']),
                       'rounds_per_schedule': sum(r['rounds'] for r in groups['overlap'])})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'capture', 'ptx', 'output'):
        p.add_argument('--' + key, type=Path, required=True)
    a = p.parse_args()
    source, out = a.source.resolve(), a.output.resolve()
    if out.is_relative_to(source):
        p.error('Output must be outside the shared source checkout')
    decode(a.capture.read_bytes())
    out.mkdir(parents=True, exist_ok=False)
    names = ['scheduling_probe.cc', 'continuation_mailbox.h', 'native_lambert_queue.cc',
             'batched_bridge.cc', 'profile_metrics.h', 'profile_patch.py', 'window_dispatch_patch.py',
             'async_transfer_patch.py', 'packed_readback_patch.py', 'correlated_state.py', 'reference.py']
    inputs = [ROOT / 'xpu2' / n for n in names] + [Path(__file__).resolve(), a.capture.resolve(), a.ptx.resolve(),
              ROOT / 'tools/xpu2_baseline.py', ROOT / 'tools/xpu2_repeatability.py']
    hashes = {str(f): digest_file(f) for f in inputs}
    report = {'status': 'incomplete', 'scope': 'Scheduling feasibility with native captured Lambert packets and synthetic AVX CPU work. No native path resumption, film, scene load or renderer speedup claim.',
              'source_hashes': hashes, 'gpu': gpu_identity(), 'runs': []}
    try:
        bridge = profile_patch.apply((ROOT/'xpu2/native_lambert_queue.cc').read_text(),
                                     (ROOT/'xpu2/batched_bridge.cc').read_text(),
                                     (ROOT/'xpu2/profile_metrics.h').read_text())
        bridge = packed_readback_patch.apply(async_transfer_patch.apply(window_dispatch_patch.apply(bridge)))
        code = (ROOT/'xpu2/scheduling_probe.cc').read_text().replace('#include "batched_bridge.cc"', bridge)
        code = code.replace('#include "continuation_mailbox.h"', (ROOT/'xpu2/continuation_mailbox.h').read_text())
        cpp, pp, exe = out/'scheduling.cc', out/'scheduling.ii', out/'scheduling.exe'
        cpp.write_text(code, encoding='utf-8')
        compiler = source/'toolchain/msys64/ucrt64/bin/g++.exe'
        env = environment(compiler.parent, out)
        flags = ['-std=c++17', '-O2', '-mavx', '-mno-avx2', '-mno-fma', '-ffp-contract=off',
                 '-I'+str(source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include')]
        for label, args in [('preprocess', ['-E', str(cpp), '-o', str(pp)]), ('compile', [str(pp), '-o', str(exe)])]:
            done = subprocess.run([str(compiler), *flags, *args], env=env, capture_output=True, text=True,
                                  timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:
                raise ValueError(label+' failed')
        report.update(compiler_sha256=digest_file(compiler), executable_sha256=digest_file(exe),
                      preprocessed_sha256=digest_file(pp))
        for mode in ('replace', 'sentinel'):
            folder = out/mode
            folder.mkdir()
            env = environment(compiler.parent, folder)
            env.update(XPU2_NATIVE_LAMBERT=mode, XPU2_NATIVE_LAMBERT_PTX=str(a.ptx.resolve()),
                       XPU2_PROFILE_FILE=str(folder/'profile.json'), XPU2_PROFILE_QUIET='1',
                       XPU2_QUEUE_CAPACITY='64', XPU2_QUEUE_COALESCE_US='0', XPU2_WINDOW_DISPATCH='1',
                       XPU2_ASYNC_TRANSFERS='1', XPU2_PACKED_READBACK='1', XPU2_SHADER_AUDIT='1')
            print('Scheduling '+mode, flush=True)
            done = subprocess.run([str(exe), str(a.capture.resolve()), mode], env=env, cwd=folder,
                                  capture_output=True, text=True, timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
            (folder/'process.log').write_text(done.stdout+done.stderr)
            if done.returncode:
                raise ValueError(mode+' failed')
            row = json.loads(done.stdout)
            if not row['passed'] or not row['cleanup']:
                raise ValueError('Incomplete checks')
            row.update(mode=mode, summary=summarize(row['runs']), profile=json.loads((folder/'profile.json').read_text()))
            if row['profile']['readback_calls'] != row['gpu_batches']:
                raise ValueError('Readback count drift')
            if row['profile']['audit_samples'] != row['gpu_samples']:
                raise ValueError('GPU audit missing')
            row['log_hashes'] = {f.name: digest_file(f) for f in folder.iterdir() if f.is_file()}
            report['runs'].append(row)
        if hashes != {str(f): digest_file(f) for f in inputs} or report['gpu'] != gpu_identity():
            raise ValueError('Source/device drift')
        if digest_file(exe) != report['executable_sha256']:
            raise ValueError('Executable drift')
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
