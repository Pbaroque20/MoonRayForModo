"""Compile native scene-index contracts and optionally exercise real CUDA jobs.

The owned indexed resources are synthetic; this does not render a MoonRay scene.
Requires a new output directory. Never installs a runtime or starts Modo.
"""
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
from xpu2_baseline import environment
from xpu2 import native_integration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Read-only compiler/CUDA toolchain root')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ptx', type=Path, help='Previously validated sampler.ptx; enables CUDA integration')
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    if out.is_relative_to(source):
        parser.error('Output must be outside shared source checkout')
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='incomplete', scope='Native owned scene index; optional real CUDA with synthetic indexed resources', runs=[])
    compiler = source / 'toolchain/msys64/ucrt64/bin/g++.exe'
    include = source / 'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
    files = [ROOT / 'xpu2' / name for name in ('indexed_scene.h', 'indexed_scene_test.cc', 'persistent_map.h')]
    files += [Path(__file__).resolve()]
    try:
        cases = [('index', files[1])]
        if args.ptx:
            ptx = args.ptx.resolve()
            files.extend([ROOT/'xpu2/indexed_scene_gpu_probe.cc', ROOT/'xpu2/native_lambert_queue.cc', ptx])
            cases.append(('gpu', ROOT/'xpu2/indexed_scene_gpu_probe.cc'))
            raw = gzip.decompress((ROOT/'xpu2/reference/native-lambert-avx8-cuda-20261017.bin.gz').read_bytes())
            if hashlib.sha256(raw).hexdigest() != '39715df807458a8da5746fd8133f5a552ae5dd6116738f2d57010c66401b5ee3':
                raise ValueError('Capture fixture drift')
            capture = out / 'reference.bin'
            capture.write_bytes(raw)
        hashes = {str(f): digest_file(f) for f in files}
        report.update(source_hashes=hashes, compiler_sha256=digest_file(compiler))
        flags = ['-std=c++17', '-O2', '-mavx', '-mno-avx2', '-mno-fma', '-ffp-contract=off', '-I'+str(include)]
        env = environment(compiler.parent, out)
        for name, cpp in cases:
            print('build '+name, flush=True)
            exe, pp = out/(name+'.exe'), out/(name+'.ii')
            for label, command in [('preprocess', ['-E', str(cpp), '-o', str(pp)]), ('compile', [str(pp), '-o', str(exe)])]:
                done = subprocess.run([str(compiler), *flags, *command], env=env, capture_output=True, text=True,
                                      timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
                (out/(name+'-'+label+'.log')).write_text(done.stdout+done.stderr, encoding='utf-8')
                if done.returncode:
                    raise RuntimeError(name+' '+label+' failed')
            runenv = dict(env)
            command = [str(exe)]
            if name == 'gpu':
                command.append(str(capture))
                runenv.update(XPU2_NATIVE_LAMBERT='sentinel', XPU2_NATIVE_LAMBERT_PTX=str(ptx),
                              XPU2_NATIVE_LAMBERT_LOG=str(out/'shading.log'), XPU2_NATIVE_LAMBERT_RECORDS=str(out/'shading.bin'),
                              XPU2_QUEUE_CAPACITY='64', XPU2_QUEUE_POLICY='all', XPU2_QUEUE_LOG=str(out/'queue.log'))
            print('run '+name, flush=True)
            done = subprocess.run(command, env=runenv, capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(name+'-run.log')).write_text(done.stdout+done.stderr, encoding='utf-8')
            if done.returncode:
                raise RuntimeError(name+' probe failed: '+done.stderr.strip())
            result = json.loads(done.stdout)
            if result.get('passed') is not True:
                raise ValueError('Probe did not pass')
            item = dict(case=name, checks=result, executable_sha256=digest_file(exe), preprocessed_sha256=digest_file(pp))
            if name == 'gpu':
                counts = native_integration.summary((out/'shading.log').read_text())
                observed = native_integration.records((out/'shading.bin').read_bytes())
                native_integration.verify_counts(counts, observed, 'replace')
                if counts['samples'] != 16 or counts['accepted'] != 16:
                    raise ValueError('Expected two fully accepted real CUDA jobs')
                item['shading'] = counts
            report['runs'].append(item)
        if hashes != {str(f): digest_file(f) for f in files}:
            raise ValueError('Sources changed during validation')
        report['status'] = 'passed'
    except Exception as exc:
        report['error'] = str(exc)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(report['status'], report.get('error', ''), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
