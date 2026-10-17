// Isolated resident-stack contribution bridge. Numeric input only; no native pointers.
#include <windows.h>
#include <cuda.h>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <stdexcept>
#include <string>
namespace xpu2film {
using Clock=std::chrono::steady_clock;
using U=unsigned long long;
U now(){return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();}
int mode(){static int m=[] {const char* s=std::getenv("XPU2_FILM_CONTRIBUTION");if(!s)return 0;
 if(!std::strcmp(s,"audit"))return 1;if(!std::strcmp(s,"replace"))return 2;
 if(!std::strcmp(s,"fast"))return 3;if(!std::strcmp(s,"sentinel"))return 4;return 0;}();return m;}
bool asyncTransfers(){static bool enabled=[] {const char* s=std::getenv("XPU2_FILM_ASYNC_TRANSFERS");return s&&!std::strcmp(s,"1");}();return enabled;}
bool graphReplay(){static bool enabled=[] {const char* s=std::getenv("XPU2_FILM_GRAPH");return asyncTransfers()&&s&&!std::strcmp(s,"1");}();return enabled;}
struct State {
 std::mutex mutex;bool attempted=false,ready=false,closed=false;HMODULE driver=nullptr;
 CUcontext context=nullptr;CUmodule module=nullptr;CUfunction kernel=nullptr,fusedKernel=nullptr;CUdeviceptr input=0,output=0;CUstream stream=nullptr;
 CUgraphExec graphs[32]={};
 U graphCaptures=0,graphSourcesFreed=0,graphBuilds=0,graphFrees=0,graphLaunches=0,graphBuildTime=0;
 float* hostInput=nullptr;float* hostOutput=nullptr;
 U pinnedAllocs=0,pinnedFrees=0,asyncBatches=0,asyncCompleted=0,completionWaits=0,errorDrains=0,staging=0;
 U fusedCalls=0,shaderChecked=0,shaderUnsupported=0,shaderMismatch=0;
 U packets=0,dispatches=0,maxSlots=0;
 U calls=0,eligible=0,accepted=0,replaced=0,cpuSkipped=0,unsupported=0,mismatch=0,errors=0,cleanupErrors=0;
 U total=0,init=0,upload=0,launch=0,wait=0,download=0,compare=0;
#define FN(n) decltype(&n) n##_p=nullptr;
 FN(cuInit) FN(cuDeviceGet) FN(cuCtxCreate_v2) FN(cuCtxGetCurrent) FN(cuCtxSetCurrent) FN(cuCtxPushCurrent_v2) FN(cuCtxPopCurrent_v2)
 FN(cuModuleLoad) FN(cuModuleGetFunction) FN(cuMemAlloc_v2) FN(cuMemFree_v2) FN(cuModuleUnload) FN(cuCtxDestroy_v2)
 FN(cuStreamBeginCapture_v2) FN(cuStreamEndCapture) FN(cuGraphInstantiateWithFlags) FN(cuGraphLaunch) FN(cuGraphDestroy) FN(cuGraphExecDestroy)
 FN(cuMemHostAlloc) FN(cuMemFreeHost) FN(cuMemcpyHtoDAsync_v2) FN(cuMemcpyDtoHAsync_v2)
 FN(cuMemcpyHtoD_v2) FN(cuMemcpyDtoH_v2) FN(cuLaunchKernel) FN(cuStreamCreate) FN(cuStreamSynchronize) FN(cuStreamDestroy_v2)
#undef FN
 void check(CUresult r){if(r!=CUDA_SUCCESS)throw std::runtime_error("CUDA status "+std::to_string(int(r)));}
 void initialize(){
  attempted=true;driver=LoadLibraryExA("nvcuda.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!driver)throw std::runtime_error("CUDA driver missing");
#define LOAD(n) n##_p=reinterpret_cast<decltype(n##_p)>(GetProcAddress(driver,#n));if(!n##_p)throw std::runtime_error(#n);
  LOAD(cuInit) LOAD(cuDeviceGet) LOAD(cuCtxCreate_v2) LOAD(cuCtxGetCurrent) LOAD(cuCtxSetCurrent) LOAD(cuCtxPushCurrent_v2) LOAD(cuCtxPopCurrent_v2)
  LOAD(cuModuleLoad) LOAD(cuModuleGetFunction) LOAD(cuMemAlloc_v2) LOAD(cuMemFree_v2) LOAD(cuModuleUnload) LOAD(cuCtxDestroy_v2)
  if(graphReplay()){LOAD(cuStreamBeginCapture_v2) LOAD(cuStreamEndCapture) LOAD(cuGraphInstantiateWithFlags) LOAD(cuGraphLaunch) LOAD(cuGraphDestroy) LOAD(cuGraphExecDestroy)}
  LOAD(cuMemHostAlloc) LOAD(cuMemFreeHost) LOAD(cuMemcpyHtoDAsync_v2) LOAD(cuMemcpyDtoHAsync_v2)
  LOAD(cuMemcpyHtoD_v2) LOAD(cuMemcpyDtoH_v2) LOAD(cuLaunchKernel) LOAD(cuStreamCreate) LOAD(cuStreamSynchronize) LOAD(cuStreamDestroy_v2)
#undef LOAD
  check(cuInit_p(0));CUdevice device;check(cuDeviceGet_p(&device,0));CUcontext previous=nullptr;check(cuCtxGetCurrent_p(&previous));
  try {check(cuCtxCreate_v2_p(&context,0,device));
   const char* path=std::getenv("XPU2_FILM_PTX");if(!path)throw std::runtime_error("Missing film PTX");
   check(cuModuleLoad_p(&module,path));check(cuModuleGetFunction_p(&kernel,module,"film_contribution"));
   check(cuMemAlloc_v2_p(&input,128*64*sizeof(float)));check(cuMemAlloc_v2_p(&output,128*8*sizeof(float)));
   check(cuStreamCreate_p(&stream,CU_STREAM_NON_BLOCKING));
   if(asyncTransfers()){
    check(cuMemHostAlloc_p(reinterpret_cast<void**>(&hostInput),128*64*sizeof(float),0));++pinnedAllocs;
    if(std::getenv("XPU2_FILM_FAIL_PINNED"))throw std::runtime_error("Injected partial pinned allocation failure");
    check(cuMemHostAlloc_p(reinterpret_cast<void**>(&hostOutput),128*8*sizeof(float),0));++pinnedAllocs;
   }
   check(cuCtxSetCurrent_p(previous));ready=true;
  }catch(...){cuCtxSetCurrent_p(previous);throw;}
 }
 CUgraphExec graphFor(unsigned count,bool fused,unsigned stride){
  auto& cached=graphs[(fused?16:0)+count-1];if(cached)return cached;
  U start=now();CUgraph graph=nullptr;CUgraphExec executable=nullptr;bool capturing=false;
  try {
   check(cuStreamBeginCapture_v2_p(stream,CU_STREAM_CAPTURE_MODE_THREAD_LOCAL));capturing=true;
   check(cuMemcpyHtoDAsync_v2_p(input,hostInput,count*8*stride*sizeof(float),stream));
   unsigned samples=count*8;void* args[]={&input,&output,&samples};
   check(cuLaunchKernel_p(fused?fusedKernel:kernel,1,1,1,128,1,1,0,stream,args,nullptr));
   check(cuMemcpyDtoHAsync_v2_p(hostOutput,output,count*8*8*sizeof(float),stream));
   CUresult ended=cuStreamEndCapture_p(stream,&graph);capturing=false;check(ended);++graphCaptures;
   if(std::getenv("XPU2_FILM_FAIL_GRAPH_BUILD"))throw std::runtime_error("Injected captured graph failure");
   check(cuGraphInstantiateWithFlags_p(&executable,graph,0));++graphBuilds;
   check(cuGraphDestroy_p(graph));graph=nullptr;++graphSourcesFreed;
   cached=executable;graphBuildTime+=now()-start;return cached;
  }catch(...){
   if(capturing){CUgraph abandoned=nullptr;CUresult ended=cuStreamEndCapture_p(stream,&abandoned);
    if(abandoned){++graphCaptures;if(cuGraphDestroy_p(abandoned)==CUDA_SUCCESS)++graphSourcesFreed;else ++cleanupErrors;}
    // CUDA_ERROR_STREAM_CAPTURE_INVALIDATED is expected after a capture API fails.
    if(ended!=CUDA_SUCCESS&&ended!=CUDA_ERROR_STREAM_CAPTURE_INVALIDATED)++cleanupErrors;
   }
   if(graph){if(cuGraphDestroy_p(graph)==CUDA_SUCCESS)++graphSourcesFreed;else ++cleanupErrors;}
   if(executable){if(cuGraphExecDestroy_p(executable)==CUDA_SUCCESS)++graphFrees;else ++cleanupErrors;}
   graphBuildTime+=now()-start;throw;
  }
 }
 void run(const float* src,const float* reference,float* dst,const int* masks,int* result,unsigned count,const float* lambert=nullptr,const float* native=nullptr,const int* shaderMasks=nullptr){
  std::lock_guard<std::mutex> guard(mutex);U start=now();closed=false;++calls;
  if(!count||count>16){++errors;total+=now()-start;return;}
  for(unsigned slot=0;slot<count;++slot)result[slot]=0;
  if(count>maxSlots)maxSlots=count;
  const bool fused=lambert!=nullptr;const unsigned stride=fused?64:24;if(fused)++fusedCalls;
  float staged[128*64]={};unsigned selected[16]={};bool any=false;
  const bool corrupt=fused&&std::getenv("XPU2_FUSED_BAD_REFERENCE");
  for(unsigned i=0;i<count*8;++i){std::memcpy(staged+i*stride,src+i*24,24*sizeof(float));
   if(fused){std::memcpy(staged+i*stride+24,lambert+i*24,24*sizeof(float));std::memcpy(staged+i*stride+48,native+i*8,8*sizeof(float));
    if(corrupt)staged[i*stride+51]+=1.f;}}

  for(unsigned slot=0;slot<count;++slot){
   if(masks[slot])++packets;
   for(unsigned lane=0;lane<8;++lane){
    float* a=staged+(slot*8+lane)*stride;a[23]=0;
    if(!(unsigned(masks[slot])&(1u<<lane)))continue;
    bool ok=(!fused||(shaderMasks[slot]&(1<<lane)))&&a[0]>0&&a[1]>=0&&(a[2]==0||a[2]==1)&&a[3]==0&&a[4]==0&&a[5]>0&&a[6]>=0&&a[7]>0;
    for(unsigned j=0;j<24;++j)ok=ok&&std::isfinite(a[j]);
    if(ok){selected[slot]|=1u<<lane;a[23]=1;++eligible;any=true;}else ++unsupported;
   }
  }
  if(!any){total+=now()-start;return;}
  bool pushed=false,queued=false;U t=now();
  try {
   if(!attempted){try{initialize();}catch(...){init+=now()-t;throw;}init+=now()-t;}
   if(!ready)throw std::runtime_error("Contribution device unavailable");
   check(cuCtxPushCurrent_v2_p(context));pushed=true;
   if(fused&&!fusedKernel)check(cuModuleGetFunction_p(&fusedKernel,module,"film_fused"));
   const bool asynchronous=asyncTransfers();
   const size_t inputBytes=count*8*stride*sizeof(float),outputBytes=count*8*8*sizeof(float);
   if(asynchronous){t=now();std::memcpy(hostInput,staged,inputBytes);staging+=now()-t;}
   if(graphReplay()){
    CUgraphExec graph=graphFor(count,fused,stride);
    t=now();check(cuGraphLaunch_p(graph,stream));launch+=now()-t;queued=true;++graphLaunches;++dispatches;++asyncBatches;
    if(std::getenv("XPU2_FILM_FAIL_GRAPH_LAUNCH"))throw std::runtime_error("Injected enqueued graph failure");
   }else{
    if(asynchronous){
     t=now();check(cuMemcpyHtoDAsync_v2_p(input,hostInput,inputBytes,stream));upload+=now()-t;queued=true;++asyncBatches;
     if(std::getenv("XPU2_FILM_FAIL_AFTER_UPLOAD"))throw std::runtime_error("Injected queued upload failure");
    }else{t=now();check(cuMemcpyHtoD_v2_p(input,staged,inputBytes));upload+=now()-t;}
    unsigned samples=count*8;void* args[]={&input,&output,&samples};t=now();check(cuLaunchKernel_p(fused?fusedKernel:kernel,1,1,1,128,1,1,0,stream,args,nullptr));launch+=now()-t;++dispatches;queued=true;
    if(asynchronous){t=now();check(cuMemcpyDtoHAsync_v2_p(hostOutput,output,outputBytes,stream));download+=now()-t;}
   }
   if(asynchronous){
    t=now();++completionWaits;check(cuStreamSynchronize_p(stream));wait+=now()-t;queued=false;++asyncCompleted;
    t=now();std::memcpy(dst,hostOutput,outputBytes);staging+=now()-t;
   }else{
    t=now();check(cuStreamSynchronize_p(stream));wait+=now()-t;queued=false;
    t=now();check(cuMemcpyDtoH_v2_p(dst,output,outputBytes));download+=now()-t;
   }
   CUcontext popped=nullptr;check(cuCtxPopCurrent_v2_p(&popped));pushed=false;if(popped!=context)throw std::runtime_error("Context restore mismatch");
   t=now();
   for(unsigned slot=0;slot<count;++slot)for(unsigned lane=0;lane<8;++lane)if(selected[slot]&(1u<<lane)){
    unsigned b=(slot*8+lane)*8;
    if(fused){
     if(dst[b+7]==0.f){++shaderUnsupported;++unsupported;--eligible;continue;}
     if(dst[b+7]!=1.f){++shaderMismatch;++mismatch;continue;}
     ++shaderChecked;
    }
    bool finite=true;for(unsigned j=0;j<7;++j)finite=finite&&std::isfinite(dst[b+j]);
    if(!finite){++errors;continue;}
    if(mode()<=2 && std::memcmp(reference+b,dst+b,7*sizeof(float))){++mismatch;continue;}
    ++accepted;
    if(mode()>1){result[slot]|=1u<<lane;++replaced;if(mode()>2)++cpuSkipped;
     if(mode()==4)for(unsigned j=1;j<=6;++j)dst[b+j]*=.5f;
    }
   }
   compare+=now()-t;
  }catch(const std::exception& e){
   ++errors;
   // Never reuse or free pinned staging while an enqueued transfer may use it.
   // A failed drain disables further submissions until frame teardown.
   if(queued&&pushed){++errorDrains;if(cuStreamSynchronize_p(stream)!=CUDA_SUCCESS){++cleanupErrors;ready=false;}}
   if(pushed){CUcontext old=nullptr;if(cuCtxPopCurrent_v2_p(&old)!=CUDA_SUCCESS||old!=context)++cleanupErrors;}
   if(errors==1)std::fprintf(stderr,"XPU2_FILM_ERROR %s\n",e.what());
  }
  total+=now()-start;
 }
 void finish(){
  std::lock_guard<std::mutex> guard(mutex);if(closed)return;closed=true;
  if(context){CUcontext previous=nullptr;bool have=cuCtxGetCurrent_p(&previous)==CUDA_SUCCESS;
   auto checked=[&](CUresult r){if(r!=CUDA_SUCCESS){++cleanupErrors;std::fprintf(stderr,"XPU2_FILM_CLEANUP %d\n",int(r));}return r==CUDA_SUCCESS;};
   if(checked(cuCtxPushCurrent_v2_p(context))){
    if(stream){checked(cuStreamSynchronize_p(stream));checked(cuStreamDestroy_v2_p(stream));}
    for(auto& graph:graphs)if(graph&&checked(cuGraphExecDestroy_p(graph))){graph=nullptr;++graphFrees;}
    if(hostInput&&checked(cuMemFreeHost_p(hostInput))){hostInput=nullptr;++pinnedFrees;}
    if(hostOutput&&checked(cuMemFreeHost_p(hostOutput))){hostOutput=nullptr;++pinnedFrees;}
    if(input)checked(cuMemFree_v2_p(input));if(output)checked(cuMemFree_v2_p(output));if(module)checked(cuModuleUnload_p(module));
    CUcontext popped=nullptr;if(checked(cuCtxPopCurrent_v2_p(&popped))&&popped!=context)++cleanupErrors;
   }
   checked(cuCtxDestroy_v2_p(context));CUcontext after=nullptr;if(have&&checked(cuCtxGetCurrent_p(&after))&&after!=previous)++cleanupErrors;
  }
  if(driver&&!FreeLibrary(driver))++cleanupErrors;
  context=nullptr;module=nullptr;kernel=fusedKernel=nullptr;driver=nullptr;input=output=0;stream=nullptr;ready=attempted=false;
  const char* path=std::getenv("XPU2_FILM_PROFILE");FILE* f=path?std::fopen(path,"wb"):nullptr;
  if(f){std::fprintf(f,"{\"graph_enabled\":%llu,\"graph_captures\":%llu,\"graph_sources_freed\":%llu,\"graph_builds\":%llu,\"graph_frees\":%llu,\"graph_launches\":%llu,\"graph_build_ns\":%llu,\"async_enabled\":%llu,\"pinned_allocations\":%llu,\"pinned_frees\":%llu,\"async_batches\":%llu,\"async_completed\":%llu,\"completion_waits\":%llu,\"error_drains\":%llu,\"staging_ns\":%llu,\"fused_calls\":%llu,\"shader_checked\":%llu,\"shader_unsupported\":%llu,\"shader_mismatch\":%llu,\"packets\":%llu,\"dispatches\":%llu,\"max_slots\":%llu,\"calls\":%llu,\"eligible\":%llu,\"accepted\":%llu,\"replaced\":%llu,\"cpu_skipped\":%llu,\"unsupported\":%llu,\"mismatch\":%llu,\"errors\":%llu,\"cleanup_errors\":%llu,\"total_ns\":%llu,\"initialization_ns\":%llu,\"upload_ns\":%llu,\"launch_ns\":%llu,\"wait_ns\":%llu,\"download_ns\":%llu,\"compare_ns\":%llu}\n",U(graphReplay()),graphCaptures,graphSourcesFreed,graphBuilds,graphFrees,graphLaunches,graphBuildTime,U(asyncTransfers()),pinnedAllocs,pinnedFrees,asyncBatches,asyncCompleted,completionWaits,errorDrains,staging,fusedCalls,shaderChecked,shaderUnsupported,shaderMismatch,packets,dispatches,maxSlots,calls,eligible,accepted,replaced,cpuSkipped,unsupported,mismatch,errors,cleanupErrors,total,init,upload,launch,wait,download,compare);std::fclose(f);}
 }
};
State*& storage(){static State* s=nullptr;return s;}
void finish(){if(storage())storage()->finish();}
State& state(){static State* s=[] {auto* p=new State;storage()=p;std::atexit(finish);return p;}();return *s;}
}
extern "C" __declspec(dllexport) int xpu2FilmMode(){return xpu2film::mode();}
extern "C" __declspec(dllexport) void xpu2FilmWindow(const float* src,const float* ref,float* dst,const int* masks,int* accepted,int count){
 if(count<1||count>16)return;
 // Same binary/control flow, optionally dispatch each SIMD packet separately.
 const char* setting=std::getenv("XPU2_FILM_WINDOW");
 if(setting&&!std::strcmp(setting,"1")){
  for(int slot=0;slot<count;++slot)xpu2film::state().run(src+slot*8*24,ref+slot*8*8,dst+slot*8*8,masks+slot,accepted+slot,1);
 }else xpu2film::state().run(src,ref,dst,masks,accepted,unsigned(count));
}

extern "C" __declspec(dllexport) void xpu2FilmFinish(){xpu2film::finish();}

extern "C" __declspec(dllexport) void xpu2FilmFusedWindow(const float* src,const float* ref,float* dst,const int* masks,int* accepted,int count,const float* lambert,const float* native,const int* shaderMasks){
 if(count<1||count>16)return;
 xpu2film::state().run(src,ref,dst,masks,accepted,unsigned(count),lambert,native,shaderMasks);
}
