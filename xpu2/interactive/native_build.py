"""Isolated native probe compilation using the installed Windows RDL toolchain."""
from pathlib import Path
import shlex
import subprocess
import sys
from fallback import environment
from reference_runtime import sha
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from xpu2_rdl_index_probe import block

def build(source,unit,out,extra_libraries=(),extra_flags=()):
    source,out,unit=map(lambda x:Path(x).resolve(),(source,out,unit))
    out.mkdir(exist_ok=False)
    compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe'
    root=source/'build/native-avx'
    ninja=(root/'build.ninja').read_text(encoding='utf-8')
    c=block(ninja,'build scene-rdl2/cmd/rdl2_cmd/rdl2_print/CMakeFiles/rdl2_print.dir/rdl2_print.cc.obj:')
    l=block(ninja,'build bin/rdl2_print.exe:')
    flags=shlex.split(' '.join(c[k] for k in ('DEFINES','FLAGS','INCLUDES')))
    flags+=list(extra_flags)
    flags+=['-I'+str(compiler.parent.parent/'include'),'-fno-fast-math','-ffp-contract=off']
    libs=[str((root/v).resolve()) if not v.startswith('-') else v for v in shlex.split(l['LINK_LIBRARIES'])]
    libs += [str(compiler.parent.parent/'lib'/n) for n in ('libOpenImageIO.dll.a','libOpenImageIO_Util.dll.a')]
    libs += [str(v) if str(v).startswith('-') else str(Path(v).resolve()) for v in extra_libraries]
    held={v:sha(Path(v)) for v in libs if not v.startswith('-')}
    pre,exe=out/'probe.ii',out/'probe.exe'
    for name,cmd in [('preprocess',['-E',str(unit),'-o',str(pre)]),('compile',[str(pre),'-o',str(exe),*libs])]:
        r=subprocess.run([str(compiler),*flags,*cmd],env=environment(compiler.parent,out),capture_output=True,
                         text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError(name+' failed: '+r.stderr[-500:])
    if any(sha(Path(p))!=v for p,v in held.items()):raise RuntimeError('Link library drift')
    return exe,{'libraries':held,'compiler_sha256':sha(compiler),'preprocessed_sha256':sha(pre),'executable_sha256':sha(exe)}
