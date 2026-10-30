"""Validate native OIIO mip loading/cache bytes against the runtime TextureSystem.

Synthetic on-disk fixtures, real OIIO decoding and optional CUDA copies. No kit,
Modo scene, native shader or GPU texture filtering is modified by this probe.
"""
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from xpu2.reference import digest_file, inventory, verify
from xpu2_baseline import environment
from xpu2_repeatability import gpu_identity


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('source', 'runtime', 'output'):
        p.add_argument('--'+key, type=Path, required=True)
    p.add_argument('--gpu', action='store_true')
    a = p.parse_args()
    source, runtime, out = (getattr(a, k).resolve() for k in ('source', 'runtime', 'output'))
    if out.is_relative_to(source) or out.is_relative_to(runtime):
        p.error('Isolated output required')
    out.mkdir(parents=True, exist_ok=False)
    report = dict(status='incomplete', scope='Native OIIO raw mip texels and base-level point lookups; CUDA copies, not GPU filtering or rendered-image parity')
    try:
        prefix = source/'toolchain/msys64/ucrt64'
        compiler = prefix/'bin/g++.exe'
        cuda = source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'
        files = [ROOT/'xpu2'/n for n in ('texture_cache.h', 'texture_cuda_backend.h', 'texture_oiio_loader.h', 'texture_oiio_probe.cc')]+[Path(__file__).resolve()]
        libraries = [prefix/'lib'/n for n in ('libOpenImageIO.dll.a', 'libOpenImageIO_Util.dll.a')]
        files += libraries+[compiler, prefix/'bin/maketx.exe']
        hashes = {str(f): digest_file(f) for f in files}
        locked = inventory(runtime)
        # This probe must load the same OIIO DLLs as the frozen native XPU runtime.
        for name in ('libOpenImageIO-3.1.dll', 'libOpenImageIO_Util-3.1.dll'):
            if digest_file(prefix/'bin'/name) != digest_file(runtime/name):
                raise ValueError('Build/runtime OIIO mismatch: '+name)
        if a.gpu:
            report['gpu'] = gpu_identity()
        compile_env, run_env = environment(prefix/'bin', out), environment(runtime, out)
        def run(label, args, env, timeout=120):
            print(label, flush=True)
            r = subprocess.run([str(v) for v in args], cwd=out, env=env, capture_output=True, text=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(r.stdout+r.stderr, encoding='utf-8')
            if r.returncode:
                raise ValueError(label+' failed: '+r.stderr[-2000:])
            return r.stdout
        exe, pp = out/'oiio-probe.exe', out/'oiio-probe.ii'
        flags = ['-std=c++17', '-O2', '-mavx', '-mno-avx2', '-mno-fma', '-ffp-contract=off', '-I'+str(cuda), '-I'+str(prefix/'include')]
        run('preprocess', [compiler, *flags, '-E', ROOT/'xpu2/texture_oiio_probe.cc', '-o', pp], compile_env)
        run('compile', [compiler, *flags, pp, '-o', exe, *libraries], compile_env)
        run('fixtures', [exe, out, '--fixtures'], run_env)
        for name, ext, fmt in [('rgba', 'exr', 'float'), ('rgb', 'exr', 'half'), ('gray', 'tif', 'uint8'), ('rg', 'exr', 'float')]:
            args = [prefix/'bin/maketx.exe', '--threads', '1', '--no-history', '--checknan', '--tile', '16', '16', '--wrap', 'black', '-d', fmt]
            if fmt == 'half':
                args += ['--format', 'openexr']
            run('mips-'+name, [*args, out/(name+'.'+ext), '-o', out/(name+'.tx')], compile_env)
        run('unmipped', [prefix/'bin/maketx.exe', '--threads', '1', '--no-history', '--nomipmap', '--tile', '16', '16', out/'rgba.exr', '-o', out/'unmipped.tx'], compile_env)
        fixture_hashes = {f.name: digest_file(f) for f in sorted(out.glob('*.tx'))}
        native = json.loads(run('probe', [exe, out, *(['--gpu'] if a.gpu else [])], run_env))
        if native.get('passed') is not True or (a.gpu and native['cuda_consumers'] != 8):
            raise ValueError('Incomplete native check')
        verify(runtime, locked)
        if hashes != {str(f): digest_file(f) for f in files}:
            raise ValueError('Source/library/tool drift')
        if fixture_hashes != {f: digest_file(out/f) for f in fixture_hashes}:
            raise ValueError('Fixture drift')
        if a.gpu and gpu_identity() != report['gpu']:
            raise ValueError('GPU identity drift')
        report.update(status='passed', native=native, source_hashes=hashes, fixture_hashes=fixture_hashes, runtime_inventory=locked, preprocessed_sha256=digest_file(pp), executable_sha256=digest_file(exe))
    except Exception as e:
        report['error'] = str(e)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(report['status'], report.get('error', ''), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
