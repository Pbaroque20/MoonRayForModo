"""Qualify a fused CUDA diffuse/direct-light unit against captured native outputs."""
import argparse,ctypes as C,json,math,os,random,struct,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_cuda_sampler_probe import bind
from xpu2.native_work import cuda

def compile_kernel(source,out):
 toolkit=source/'toolchain/xpu/cuda_nvrtc-windows-x86_64-12.8.93-archive/bin'
 with os.add_dll_directory(str(toolkit)):
  builtins=C.WinDLL(str(toolkit/'nvrtc-builtins64_128.dll'));lib=C.WinDLL(str(toolkit/'nvrtc64_120_0.dll'))
 names=('sampler_cuda.cu','lambert_cuda.cu','ispc_math_cuda.cuh','diffuse_sample_cuda.cu','direct_light_cuda.cu')
 code='\n'.join(cuda((ROOT/'xpu2'/n).read_text()) if n=='diffuse_sample_cuda.cu' else (ROOT/'xpu2'/n).read_text() for n in names).encode()
 (out/'direct_light.cu').write_bytes(code);program=C.c_void_p()
 bind(lib,'nvrtcCreateProgram',[C.POINTER(C.c_void_p),C.c_char_p,C.c_char_p,C.c_int,C.c_void_p,C.c_void_p])(C.byref(program),code,b'direct_light.cu',0,None,None)
 flags=['--std=c++14','--gpu-architecture=compute_86','--fmad=false','--ftz=false','--prec-div=true','--prec-sqrt=true']
 try:
  fn=lib.nvrtcCompileProgram;fn.argtypes=[C.c_void_p,C.c_int,C.POINTER(C.c_char_p)];fn.restype=C.c_int
  options=(C.c_char_p*len(flags))(*(v.encode() for v in flags));status=fn(program,len(flags),options)
  n=C.c_size_t();bind(lib,'nvrtcGetProgramLogSize',[C.c_void_p,C.POINTER(C.c_size_t)])(program,C.byref(n));log=C.create_string_buffer(n.value)
  bind(lib,'nvrtcGetProgramLog',[C.c_void_p,C.c_void_p])(program,log);(out/'cuda.log').write_bytes(log.value)
  if status:raise ValueError('CUDA compilation failed')
  bind(lib,'nvrtcGetPTXSize',[C.c_void_p,C.POINTER(C.c_size_t)])(program,C.byref(n));ptx=C.create_string_buffer(n.value)
  bind(lib,'nvrtcGetPTX',[C.c_void_p,C.c_void_p])(program,ptx);(out/'direct_light.ptx').write_bytes(ptx.value)
 finally:bind(lib,'nvrtcDestroyProgram',[C.POINTER(C.c_void_p)])(C.byref(program))
 return flags

def compare(inputs,expected,output):
 result={'records':len(inputs),'accepted':0,'declined':0,'different_records':0,'failed_records':0,'components':[{'different':0,'failed':0,'max_absolute':0.0} for _ in range(8)],'first_differences':[]}
 for i,(a,e) in enumerate(zip(inputs,expected)):
  raw=output[i*36:(i+1)*36];v=struct.unpack('<9f',raw);native=struct.unpack('<8f',e)
  if v[8]!=1.0:result['declined']+=1;continue
  result['accepted']+=1;diff=False;bad=False
  for c,(got,want) in enumerate(zip(v,native)):
   different=raw[c*4:c*4+4]!=e[c*4:c*4+4];error=abs(got-want)
   failed=not math.isfinite(got) or error>1e-6+1e-6*abs(want)
   stat=result['components'][c];stat['different']+=different;stat['failed']+=failed;stat['max_absolute']=max(stat['max_absolute'],error)
   diff|=different;bad|=failed
  result['different_records']+=diff;result['failed_records']+=bad
  if diff and len(result['first_differences'])<4:result['first_differences'].append({'index':i,'kind':struct.unpack('<I',a[:4])[0],'input':list(struct.unpack('<32f',a))[1:],'expected':native,'got':v})
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--source',type=Path,required=True);p.add_argument('--captures',type=Path,nargs='+',required=True);p.add_argument('--output',type=Path,required=True)
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','runs':[]}
 try:
  files=[Path(__file__).resolve(),ROOT/'xpu2/native_work.py']+[ROOT/'xpu2'/n for n in ('sampler_cuda.cu','lambert_cuda.cu','ispc_math_cuda.cuh','diffuse_sample_cuda.cu','direct_light_cuda.cu')]
  inputs=[];expected=[];kinds={1:0,2:0}
  for capture in a.captures:
   folder=capture.resolve();meta=json.loads((folder/'report.json').read_text());f=folder/'capture/light.bin';raw=f.read_bytes()
   if meta['status']!='passed' or digest_file(f)!=meta['capture_sha256'] or raw[:4]!=b'XDL1' or (len(raw)-4)%160:raise ValueError('Unqualified capture')
   files.extend([folder/'report.json',f])
   for offset in range(4,len(raw),160):
    inp=raw[offset:offset+128];kind=struct.unpack('<I',inp[:4])[0];kinds[kind]+=1
    inputs.append(inp);expected.append(raw[offset+128:offset+160])
  if not inputs:raise ValueError('No native records')
  hashes={str(f):digest_file(f) for f in files};report['source_hashes']=hashes;report['kinds']=kinds
  report['cuda_flags']=compile_kernel(a.source.resolve(),out)
  driver=C.WinDLL('nvcuda.dll');ptr=C.c_void_p;u64=C.c_uint64;uint=C.c_uint;integer=C.c_int;size=C.c_size_t
  bind(driver,'cuInit',[uint])(0);device=integer();bind(driver,'cuDeviceGet',[C.POINTER(integer),integer])(C.byref(device),0)
  name=C.create_string_buffer(256);bind(driver,'cuDeviceGetName',[ptr,integer,integer])(name,256,device);report['gpu']=name.value.decode()
  context=ptr();bind(driver,'cuCtxCreate_v2',[C.POINTER(ptr),uint,integer])(C.byref(context),0,device)
  buffers=[];module=ptr()
  try:
   bind(driver,'cuModuleLoad',[C.POINTER(ptr),C.c_char_p])(C.byref(module),str(out/'direct_light.ptx').encode())
   function=ptr();bind(driver,'cuModuleGetFunction',[C.POINTER(ptr),ptr,C.c_char_p])(C.byref(function),module,b'direct_light_unit')
   alloc=bind(driver,'cuMemAlloc_v2',[C.POINTER(u64),size]);h2d=bind(driver,'cuMemcpyHtoD_v2',[u64,ptr,size]);d2h=bind(driver,'cuMemcpyDtoH_v2',[ptr,u64,size])
   launch=bind(driver,'cuLaunchKernel',[ptr,uint,uint,uint,uint,uint,uint,uint,ptr,ptr,ptr]);sync=bind(driver,'cuCtxSynchronize',[])
   for width in (128,36):
    b=u64();alloc(C.byref(b),max(len(inputs),64)*width);buffers.append(b)
   def dispatch(records,block):
    raw=b''.join(records);src=C.create_string_buffer(raw);h2d(buffers[0],src,len(raw));n=uint(len(records))
    args=(ptr*3)(C.cast(C.byref(buffers[0]),ptr),C.cast(C.byref(buffers[1]),ptr),C.cast(C.byref(n),ptr))
    launch(function,(n.value+block-1)//block,1,1,block,1,1,0,None,args,None);sync()
    result=C.create_string_buffer(n.value*36);d2h(result,buffers[1],len(result));return result.raw
   for run,block in enumerate((64,128,256)):
    order=list(range(len(inputs)));random.Random(8451+run).shuffle(order)
    ins=[inputs[i] for i in order];refs=[expected[i] for i in order];raw=dispatch(ins,block)
    row=compare(ins,refs,raw);row['block_size']=block;report['runs'].append(row)
    print(json.dumps({k:row[k] for k in ('records','accepted','declined','different_records','failed_records','block_size')}),flush=True)
    ordered=bytearray(len(raw))
    for j,i in enumerate(order):ordered[i*36:(i+1)*36]=raw[j*36:(j+1)*36]
    if run==0:
     stable=bytes(ordered)
     sentinel=bytearray(raw);struct.pack_into('<f',sentinel,16,struct.unpack_from('<f',sentinel,16)[0]+0.25)
     if compare(ins,refs,bytes(sentinel))['failed_records']<=row['failed_records']:raise ValueError('Comparator sentinel failed')
    elif stable!=bytes(ordered):raise ValueError('Schedule-dependent GPU output')
   mutations=[]
   for word,value in ((0,99),(29,1),(30,1),(31,1),(1,float('nan')),(4,3.0),(22,0.0),(22,1.5),(23,-1.0),(24,0.0),(25,-1.0),(28,0.5),(10,-1.0)):
    b=bytearray(inputs[0]);struct.pack_into('<I' if word==0 else '<f',b,word*4,value);mutations.append(bytes(b))
   rejected=dispatch(mutations,64)
   if any(struct.unpack_from('<f',rejected,i*36+32)[0]!=0.0 for i in range(len(mutations))):raise ValueError('Unsupported packet accepted')
   report['rejection_controls']=len(mutations);report['schedule_exact']=True;report['comparator_sentinel']=True
  finally:
   for b in buffers:bind(driver,'cuMemFree_v2',[u64])(b)
   if module.value:bind(driver,'cuModuleUnload',[ptr])(module)
   bind(driver,'cuCtxDestroy_v2',[ptr])(context)
  for f,h in hashes.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift')
  report['ptx_sha256']=digest_file(out/'direct_light.ptx')
  report['status']='failed' if any(r['failed_records'] or r['declined'] for r in report['runs']) else 'rounding_differences' if any(r['different_records'] for r in report['runs']) else 'passed'
  report['limitations']=['Captured numerical unit only; native CPU results still produce rendered images.','No native async scheduling, shadow query or film output is replaced.','No full-render speed claim; synchronous copies isolate arithmetic from scheduling.','Only valid, admitted diffuse light contributions are captured; capped at 65536 records per kind per scene.']
 except Exception as e:report['error']=str(e)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
