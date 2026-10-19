"""Diagnostic-only exclusive host stages and per-flight GPU intervals on reviewed sources."""
import re,shutil
from pathlib import Path
from .native_gpu_paths import once


def body(text,name):
 for match in re.finditer(r'\b'+re.escape(name)+r'\(',text):
  i=match.end();depth=1
  while depth:
   depth+=(text[i]=='(')-(text[i]==')');i+=1
  while text[i].isspace():i+=1
  if text[i]!='{':continue
  start=i;depth=1;i+=1
  # Remove comment/string tokens from brace accounting without changing offsets.
  tokens=re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]')
  for token in tokens.finditer(text,i):
   if token.group()=='{':depth+=1
   elif token.group()=='}':depth-=1
   if not depth:return start,token.start()
 raise ValueError('Missing function '+name)


def cpp_scope(text,name,stage):
 a,b=body(text,name);return text[:a+1]+'\n    xpu2cost::Scope exclusiveCost(xpu2cost::'+stage+');'+text[a+1:]


def ispc_scope(text,name,stage,returns=True):
 a,b=body(text,name);part=text[a+1:b]
 part=re.sub(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\breturn\s*([^;]*);',lambda m:m.group() if m.group(1) is None else '{ CPP_xpu2CostEnd(costToken); return '+m.group(1)+'; }',part)
 return text[:a+1]+'\n    uniform uint64 costToken=CPP_xpu2CostBegin('+stage+');'+part+'\n    CPP_xpu2CostEnd(costToken);\n'+text[b:]


def driver_scopes(text):
 mapping={'cuMemcpyHtoDAsync_v2':'Upload','cuMemcpyHtoD_v2':'Upload','cuMemcpyDtoHAsync_v2':'Readback','cuMemcpyDtoH_v2':'Readback','cuLaunchKernel':'Launch',
 'cuCtxPushCurrent_v2':'Context','cuCtxPopCurrent_v2':'Context','cuCtxSetCurrent':'Context','cuCtxGetCurrent':'Context',
 'cuEventQuery':'Completion','cuEventRecord':'Completion','cuEventElapsedTime':'Completion','cuEventSynchronize':'Wait','cuStreamSynchronize':'Wait','cuCtxSynchronize':'Wait'}
 matches=list(re.finditer(r'\b(?:fn_|f_)('+ '|'.join(mapping)+r')\(',text))
 for m in reversed(matches):
  i=m.end();depth=1
  while depth:depth+=(text[i]=='(')-(text[i]==')');i+=1
  text=text[:m.start()]+'XPU2_COST_CALL('+mapping[m.group(1)]+','+text[m.start():i]+')'+text[i:]
 return text


def patch(out):
 shutil.copyfile(Path(__file__).with_name('native_exclusive.h'),out/'native_exclusive.h')
 p=out/'early_queue.inc';s='#include "native_exclusive.h"\n'+p.read_text()
 for name,stage in [('workFlights','Coordination'),('startFlight','Packing'),('finishFlight','Validation'),('initialize','Setup'),('allocateFlights','Setup'),('closeFlights','Setup')]:s=cpp_scope(s,name,stage)
 # Queue gathering and transport encoding includes admission/expansion before the old timer.
 s=once(s,'                const bool allPrepared=device.resident', '                auto exclusivePack=xpu2cost::begin(xpu2cost::Packing);\n                const bool allPrepared=device.resident')
 s=once(s,'                f.started=std::chrono::steady_clock::now();','                xpu2cost::end(exclusivePack);\n                f.started=std::chrono::steady_clock::now();')
 # GPU timings are separate from host scope totals and from other streams.
 s=once(s,'            kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));\n            if(xpu2trace::enabled){', '            kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));\n            if(xpu2cost::enabled){xpu2cost::Scope probeCost(xpu2cost::Instrumentation);auto elapsed=fn_cuEventElapsedTime;float up=0,down=0;check(elapsed(&up,s.upload,s.begin));check(elapsed(&down,s.end,s.done));xpu2cost::gpu(index,up,ms,down);}\n            if(xpu2trace::enabled){')
 s=s.replace('xpu2trace::enabled?0:CU_EVENT_DISABLE_TIMING','(xpu2trace::enabled||xpu2cost::enabled)?0:CU_EVENT_DISABLE_TIMING')
 s=s.replace('if(xpu2trace::enabled)check(fn_cuEventCreate(&s.upload,0));','if(xpu2trace::enabled||xpu2cost::enabled)check(fn_cuEventCreate(&s.upload,0));')
 s=s.replace('if(xpu2trace::enabled)check(fn_cuEventRecord(s.upload,s.stream));','if(xpu2trace::enabled||xpu2cost::enabled)check(fn_cuEventRecord(s.upload,s.stream));')
 s=s.replace('available.wait(lock,[&]{return stopping || !pending.empty();});','XPU2_COST_CALL(Wait,available.wait(lock,[&]{return stopping || !pending.empty();}));')
 s=s.replace('std::this_thread::yield();','XPU2_COST_CALL(Wait,std::this_thread::yield());')
 p.write_text(driver_scopes(s))
 p=out/'native_gpu_shading.h';s=p.read_text();s=once(s,'    xpu2trace::reset();','    xpu2trace::reset();xpu2cost::reset();');s=once(s,'    xpu2trace::finish();','    xpu2cost::finish();xpu2trace::finish();');p.write_text(s)
 p=out/'native_gpu_early.h';s=p.read_text()
 for name,stage in [('CPP_gpuEarlySubmit','Validation'),('CPP_gpuPreparedSubmit','Packing'),('CPP_gpuWindowPublish','Coordination'),('CPP_gpuEarlyCollect','Validation'),('init','Setup'),('close','Setup'),('fillSlot','Packing'),('finishSlot','Validation'),('collect','Validation'),('work','Coordination'),('submit','Packing'),('lazySubmit','Packing'),('lazyNext','Coordination')]:s=cpp_scope(s,name,stage)
 s=s.replace('ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return ticket->done||ticket->cancelled;});','XPU2_COST_CALL(Wait,ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return ticket->done||ticket->cancelled;}));')
 s=s.replace('changed.wait_for(lock,std::chrono::milliseconds(1));','XPU2_COST_CALL(Wait,changed.wait_for(lock,std::chrono::milliseconds(1)));')
 s=s.replace('changed.wait(lock,[&]{return stopping||!pending.empty()||(lazyMode&&!broken&&lazy.readyToReserve());});','XPU2_COST_CALL(Wait,changed.wait(lock,[&]{return stopping||!pending.empty()||(lazyMode&&!broken&&lazy.readyToReserve());}));')
 s=s.replace('std::this_thread::yield();','XPU2_COST_CALL(Wait,std::this_thread::yield());')
 # Light flights previously had only a completion event; add timed stage boundaries.
 s=once(s,'CUevent done=nullptr;CUdeviceptr input=0', 'CUevent done=nullptr,upload=nullptr,start=nullptr,end=nullptr;CUdeviceptr input=0')
 s=once(s,'API(cuEventCreate) API(cuEventDestroy_v2)', 'API(cuEventElapsedTime) API(cuEventCreate) API(cuEventDestroy_v2)')
 s=once(s,'LOAD(cuEventCreate) LOAD(cuEventDestroy_v2)', 'LOAD(cuEventElapsedTime) LOAD(cuEventCreate) LOAD(cuEventDestroy_v2)')
 s=once(s,'check(f_cuEventCreate(&s.done,CU_EVENT_DISABLE_TIMING));','check(f_cuEventCreate(&s.done,xpu2cost::enabled?0:CU_EVENT_DISABLE_TIMING));if(xpu2cost::enabled){check(f_cuEventCreate(&s.upload,0));check(f_cuEventCreate(&s.start,0));check(f_cuEventCreate(&s.end,0));}')
 s=once(s,'if(s.done)check(f_cuEventDestroy_v2(s.done));','if(s.upload)check(f_cuEventDestroy_v2(s.upload));if(s.start)check(f_cuEventDestroy_v2(s.start));if(s.end)check(f_cuEventDestroy_v2(s.end));if(s.done)check(f_cuEventDestroy_v2(s.done));')
 # Insert around exact observed API calls (host submission overhead is separately scoped).
 anchor='check(f_cuMemcpyHtoDAsync_v2(s.input,s.host,s.count*128,s.stream));'
 s=once(s,anchor,'if(xpu2cost::enabled)check(f_cuEventRecord(s.upload,s.stream));'+anchor+'if(xpu2cost::enabled)check(f_cuEventRecord(s.start,s.stream));')
 anchor='check(f_cuLaunchKernel(kernel,(s.count+63)/64,1,1,64,1,1,0,s.stream,args,nullptr));'
 s=once(s,anchor,anchor+'if(xpu2cost::enabled)check(f_cuEventRecord(s.end,s.stream));')
 a,b=body(s,'finishSlot');s=s[:a+1]+'\n        if(xpu2cost::enabled && !failed){xpu2cost::Scope probeCost(xpu2cost::Instrumentation);auto elapsed=f_cuEventElapsedTime;float up=0,kernelTime=0,down=0;check(elapsed(&up,s.upload,s.start));check(elapsed(&kernelTime,s.start,s.end));check(elapsed(&down,s.end,s.done));xpu2cost::gpu(2+unsigned(&s-slots),up,kernelTime,down);}\n'+s[a+1:]
 s=driver_scopes(s)
 s+='\nextern "C" uint64_t CPP_xpu2CostBegin(unsigned stage){return xpu2cost::begin(stage);}\nextern "C" void CPP_xpu2CostEnd(uint64_t token){xpu2cost::end(token);}\nextern "C" unsigned CPP_xpu2CostPackingStage(){return xpu2::nativepath::currentWindow && xpu2::nativepath::currentWindow->replay?xpu2cost::Validation:xpu2cost::Packing;}\n'
 p.write_text(s)
 declarations='extern "C" uniform uint64 CPP_xpu2CostBegin(uniform unsigned stage);\nextern "C" void CPP_xpu2CostEnd(uniform uint64 token);\nextern "C" uniform unsigned CPP_xpu2CostPackingStage();\n'
 p=out/'PathIntegratorUtil.ispc';s=declarations+p.read_text()
 for name,stage in [('xpu2PrepareLobe','CPP_xpu2CostPackingStage()'),('xpu2SubmitMaterial','8'),('xpu2ResumeMaterial','7'),('drawBsdfSamples','7'),('drawLightSamples','7'),('xpu2PackDirectLight','0')]:s=ispc_scope(s,name,stage)
 old='else isValid=BsdfSampler_sample(pbrTls,&bSampler,lobeIndex,bsdfSample[0],bsdfSample[1],bsmp[s]);'
 assert s.count(old)==2
 s=s.replace(old,'else { uniform uint64 fallbackCost=(xpu2Prepared?CPP_xpu2CostBegin(6):0); isValid=BsdfSampler_sample(pbrTls,&bSampler,lobeIndex,bsdfSample[0],bsdfSample[1],bsmp[s]); CPP_xpu2CostEnd(fallbackCost); }')
 s=once(s,'}else f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf);','}else { uniform uint64 fallbackCost=(gpuResults!=NULL?CPP_xpu2CostBegin(6):0); f=BsdfLobe_eval(lobe,*slice,lsmp.wi,&pdf); CPP_xpu2CostEnd(fallbackCost); }')
 p.write_text(s)
 p=out/'PathIntegratorBundled.ispc';s=declarations+p.read_text();s=ispc_scope(s,'xpu2WindowPrepare','7');p.write_text(s)
