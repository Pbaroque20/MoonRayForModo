"""Private restricted native CPU image vs pinned MoonRay; no speed claim."""
import argparse,array,json,math,subprocess
from pathlib import Path
from fallback import environment
from reference_runtime import sha,verify
from run_m0 import standalone,image,guard
HERE=Path(__file__).resolve().parent

def rdla(frame):
    # Same fixture data as cpu_image_fixture.cc; not a general RDL native adapter.
    text="""SceneVariables { ["image_width"]=64, ["image_height"]=48,
 ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=%d,
 ["lock_frame_noise"]=false, ["two_stage_output"]=false, ["pixel_filter"]=0, ["pixel_filter_width"]=1.0,
 ["bsdf_samples"]=1, ["light_samples"]=1, ["max_depth"]=2,
 ["max_diffuse_depth"]=1, ["enable_dof"]=false, ["enable_motion_blur"]=false,
 ["sample_clamping_value"]=0.0, ["shadow_terminator_fix"]=0 }
PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,4,1),
 ["focal"]=50.0, ["film_width_aperture"]=36.0, ["near"]=0.001, ["far"]=1000.0 }
SceneVariables { ["camera"]=PerspectiveCamera("/camera") }
EnvLight("/sky") { ["color"]=Rgb(0.8,0.7,0.6), ["intensity"]=1.0,
 ["sample_upper_hemisphere_only"]=false }
LightSet("/lights") { EnvLight("/sky") }
"""%frame
    for i,c in enumerate(((.7,.03,.4),(.08,.6,.12),(.12,.2,.8),(.6,.6,.6))):
        text+='UsdPreviewSurface("/m%d") { ["diffuseColor"]=Rgb(%s), ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0), ["clearcoat"]=0.0, ["emissiveColor"]=Rgb(0,0,0) }\n'%(i,','.join(map(str,c)))
        x0=(i%2-1)*10;y0=(i//2-1)*10
        verts=((x0,y0,0),(x0+10,y0,0),(x0+10,y0+10,0),(x0,y0+10,0))
        text+='RdlMeshGeometry("/g%d") { ["vertex_list"]={ %s }, ["face_vertex_count"]={3,3}, ["vertices_by_index"]={0,1,2,0,2,3}, ["is_subd"]=false }\n'%(i,','.join('Vec3(%s)'%','.join(map(str,v)) for v in verts))
    text+='GeometrySet("/geometry") { '+','.join('RdlMeshGeometry("/g%d")'%i for i in range(4))+' }\n'
    text+='Layer("/layer") { '+','.join('{ RdlMeshGeometry("/g%d"), "", UsdPreviewSurface("/m%d"), LightSet("/lights") }'%(i,i) for i in range(4))+' }\n'
    text+='SceneVariables { ["layer"]=Layer("/layer") }\n'
    text+='RenderOutput("/beauty") { ["file_name"]="beauty.exr", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }\nRenderOutput("/alpha") { ["file_name"]="beauty.exr", ["result"]=1, ["channel_format"]=0, ["compression"]=1 }\n'
    return text

def compare_fixture(values,reference,gates):
    w,h=64,48;block=gates['image_block_width'];errors={}
    if len(values)!=w*h*4:raise ValueError('Wrong native buffer size')
    if not all(math.isfinite(v) for v in values):raise ValueError('Nonfinite native image')
    for c,name in enumerate('RGBA'):
        ref=reference['channels'][name]
        if len(ref)!=w*h or not all(math.isfinite(v) for v in ref):raise ValueError('Invalid reference '+name)
        diffs=[float(values[i*4+c])-float(ref[i]) for i in range(w*h)]
        blocks=[abs(sum(diffs[y*w+x] for y in range(by,min(h,by+block)) for x in range(bx,min(w,bx+block)))/(min(block,w-bx)*min(block,h-by))) for by in range(0,h,block) for bx in range(0,w,block)]
        errors[name]={'max_pixel':max(map(abs,diffs)),'max_block_mean':max(blocks),'mean':sum(diffs)/(w*h)}
        if c==3:
            if errors[name]['max_pixel']>gates['image_alpha_error']:raise ValueError('Alpha mismatch')
        elif errors[name]['max_pixel']>gates['image_max_pixel_error'] or errors[name]['max_block_mean']>gates['image_max_block_mean_error']:raise ValueError('Image comparison failed '+name+': '+str(errors[name]))
    return errors

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();source=a.source.resolve();rt=a.runtime.resolve()
    if out.is_relative_to(source) or out.is_relative_to(rt):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'generated four-material plane only; no general RDL import, MIS, clamping, maps or GPU renderer','cases':[]}
    try:
        guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
        gates=json.loads((HERE/'surface-gates.json').read_text());report['gates']=gates
        (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8')
        files=[HERE/n for n in ('surface_core.h','sample_tree.h','sample_stream.h','path_stage.h','cpu_image_fixture.cc','run_cpu_image.py','surface-gates.json')]
        held={str(p):sha(p) for p in files};report['source_hashes']=held
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';prefix=compiler.parent.parent
        flags=['-std=c++17','-O2','-march=ivybridge','-mno-avx2','-mno-fma','-ffp-contract=off','-fno-fast-math','-pthread','-I'+str(prefix/'include')]
        pre=out/'image.ii';exe=out/'image.exe';lib=rt/'libembree4.dll'
        for phase,cmd in [('preprocess',['-E',str(HERE/'cpu_image_fixture.cc'),'-o',str(pre)]),('compile',[str(pre),str(lib),'-o',str(exe)])]:
            r=subprocess.run([str(compiler),*flags,*cmd],capture_output=True,text=True,env=environment(compiler.parent,out),timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(phase+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
            if r.returncode:raise RuntimeError(phase+': '+r.stderr[-1000:])
        report['build']={'preprocessed_sha256':sha(pre),'compiler_sha256':sha(compiler),'exe_sha256':sha(exe),'embree_sha256':sha(lib),'flags':flags}
        for frame in gates['seeds']:
            candidates=[]
            for threads in (1,12):
                binary=out/f'native-f{frame}-t{threads}.rgba'
                result=subprocess.run([str(exe),str(binary),str(threads),str(frame)],cwd=out,env=environment(rt,out),capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
                (out/f'native-f{frame}-t{threads}.log').write_text(result.stdout+result.stderr,encoding='utf-8')
                if result.returncode:raise RuntimeError('Native fixture failed '+str(result.returncode))
                meta=json.loads(result.stdout);candidates.append(binary.read_bytes());report['cases'].append(dict(native=meta,sha256=sha(binary)))
            if candidates[0]!=candidates[1]:raise RuntimeError('Native 1/12-worker repeatability failed')
            scene=out/f'f{frame}.rdla';scene.write_text(rdla(frame),encoding='utf-8')
            folder=out/f'reference-f{frame}'
            frozen=out/f'f{frame}.rdlb'
            conversion=subprocess.run([str(rt/'rdl2_convert.exe'),'-i',str(scene),'-o',str(frozen)],cwd=out,env=environment(rt,out),capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/f'conversion-f{frame}.log').write_text(conversion.stdout+conversion.stderr,encoding='utf-8')
            if conversion.returncode:raise RuntimeError('RDLB conversion failed')
            run=standalone(rt,frozen,folder,1);ref=image(rt,folder)
            values=array.array('f');values.frombytes(candidates[0])
            errors=compare_fixture(values,ref,gates)
            report['cases'].append({'reference_frame':frame,'execution':run['execution'],'errors':errors})
            print('Image comparison passed, frame',frame,flush=True)
        if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
        verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
    except Exception as e:report.update(status='failed',error=str(e))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','build','gates')},indent=2),flush=True)
    return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
