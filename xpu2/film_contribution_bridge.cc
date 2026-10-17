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
struct State {
 std::mutex mutex;bool attempted=false,ready=false,closed=false;HMODULE driver=nullptr;
 CUcontext context=nullptr;CUmodule module=nullptr;CUfunction kernel=nullptr;CUdeviceptr input=0,output=0;CUstream stream=nullptr;
 U calls=0,eligible=0,accepted=0,replaced=0,cpuSkipped=0,unsupported=0,mismatch=0,errors=0,cleanupErrors=0;
 U total=0,init=0,upload=0,launch=0,wait=0,download=0,compare=0;
#define FN(n) decltype(&n) n##_p=nullptr;
 FN(cuInit) FN(cuDeviceGet) FN(cuCtxCreate_v2) FN(cuCtxGetCurrent) FN(cuCtxSetCurrent) FN(cuCtxPushCurrent_v2) FN(cuCtxPopCurrent_v2)
 FN(cuModuleLoad) FN(cuModuleGetFunction) FN(cuMemAlloc_v2) FN(cuMemFree_v2) FN(cuModuleUnload) FN(cuCtxDestroy_v2)
 FN(cuMemcpyHtoD_v2) FN(cuMemcpyDtoH_v2) FN(cuLaunchKernel) FN(cuStreamCreate) FN(cuStreamSynchronize) FN(cuStreamDestroy_v2)
#undef FN
 void check(CUresult r){if(r!=CUDA_SUCCESS)throw std::runtime_error("CUDA status "+std::to_string(int(r)));}
 void initialize(){
  attempted=true;driver=LoadLibraryExA("nvcuda.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);if(!driver)throw std::runtime_error("CUDA driver missing");
#define LOAD(n) n##_p=reinterpret_cast<decltype(n##_p)>(GetProcAddress(driver,#n));if(!n##_p)throw std::runtime_error(#n);
  LOAD(cuInit) LOAD(cuDeviceGet) LOAD(cuCtxCreate_v2) LOAD(cuCtxGetCurrent) LOAD(cuCtxSetCurrent) LOAD(cuCtxPushCurrent_v2) LOAD(cuCtxPopCurrent_v2)
  LOAD(cuModuleLoad) LOAD(cuModuleGetFunction) LOAD(cuMemAlloc_v2) LOAD(cuMemFree_v2) LOAD(cuModuleUnload) LOAD(cuCtxDestroy_v2)
  LOAD(cuMemcpyHtoD_v2) LOAD(cuMemcpyDtoH_v2) LOAD(cuLaunchKernel) LOAD(cuStreamCreate) LOAD(cuStreamSynchronize) LOAD(cuStreamDestroy_v2)
#undef LOAD
  check(cuInit_p(0));CUdevice device;check(cuDeviceGet_p(&device,0));CUcontext previous=nullptr;check(cuCtxGetCurrent_p(&previous));
  try {check(cuCtxCreate_v2_p(&context,0,device));
   const char* path=std::getenv("XPU2_FILM_PTX");if(!path)throw std::runtime_error("Missing film PTX");
   check(cuModuleLoad_p(&module,path));check(cuModuleGetFunction_p(&kernel,module,"film_contribution"));
   check(cuMemAlloc_v2_p(&input,8*24*sizeof(float)));check(cuMemAlloc_v2_p(&output,8*8*sizeof(float)));
   check(cuStreamCreate_p(&stream,CU_STREAM_NON_BLOCKING));check(cuCtxSetCurrent_p(previous));ready=true;
  }catch(...){cuCtxSetCurrent_p(previous);throw;}
 }
 int run(const float* src,const float* reference,float* dst,unsigned mask){
  std::lock_guard<std::mutex> guard(mutex);U start=now();closed=false;++calls;unsigned selected=0;
  for(unsigned lane=0;lane<8;++lane)if(mask&(1u<<lane)){
   const float* a=src+lane*24;bool ok=a[0]>0&&a[1]>=0&&(a[2]==0||a[2]==1)&&a[3]==0&&a[4]==0&&a[5]>0&&a[6]>=0&&a[7]>0;
   for(unsigned j=0;j<24;++j)ok=ok&&std::isfinite(a[j]);
   if(ok){selected|=1u<<lane;++eligible;}else ++unsupported;
  }
  if(!selected){total+=now()-start;return 0;}
  bool pushed=false;unsigned resultMask=0;U t=now();
  try {
   if(!attempted){try{initialize();}catch(...){init+=now()-t;throw;}init+=now()-t;}
   if(!ready)throw std::runtime_error("Contribution device unavailable");
   check(cuCtxPushCurrent_v2_p(context));pushed=true;
   t=now();check(cuMemcpyHtoD_v2_p(input,src,8*24*sizeof(float)));upload+=now()-t;
   void* args[]={&input,&output,&selected};t=now();check(cuLaunchKernel_p(kernel,1,1,1,32,1,1,0,stream,args,nullptr));launch+=now()-t;
   t=now();check(cuStreamSynchronize_p(stream));wait+=now()-t;
   t=now();check(cuMemcpyDtoH_v2_p(dst,output,8*8*sizeof(float)));download+=now()-t;
   CUcontext popped=nullptr;check(cuCtxPopCurrent_v2_p(&popped));pushed=false;if(popped!=context)throw std::runtime_error("Context restore mismatch");
   t=now();
   for(unsigned lane=0;lane<8;++lane)if(selected&(1u<<lane)){
    bool finite=true;for(unsigned j=0;j<7;++j)finite=finite&&std::isfinite(dst[lane*8+j]);
    if(!finite){++errors;continue;}
    if(mode()<=2 && std::memcmp(reference+lane*8,dst+lane*8,7*sizeof(float))){++mismatch;continue;}
    ++accepted;
    if(mode()>1){resultMask|=1u<<lane;++replaced;if(mode()>2)++cpuSkipped;
     if(mode()==4)for(unsigned j=1;j<=6;++j)dst[lane*8+j]*=.5f;
    }
   }
   compare+=now()-t;
  }catch(const std::exception& e){++errors;if(pushed){CUcontext old=nullptr;cuCtxPopCurrent_v2_p(&old);}if(errors==1)std::fprintf(stderr,"XPU2_FILM_ERROR %s\n",e.what());}
  total+=now()-start;return int(resultMask);
 }
 void finish(){
  std::lock_guard<std::mutex> guard(mutex);if(closed)return;closed=true;
  if(context){CUcontext previous=nullptr;bool have=cuCtxGetCurrent_p(&previous)==CUDA_SUCCESS;
   auto checked=[&](CUresult r){if(r!=CUDA_SUCCESS){++cleanupErrors;std::fprintf(stderr,"XPU2_FILM_CLEANUP %d\n",int(r));}return r==CUDA_SUCCESS;};
   if(checked(cuCtxPushCurrent_v2_p(context))){
    if(stream){checked(cuStreamSynchronize_p(stream));checked(cuStreamDestroy_v2_p(stream));}
    if(input)checked(cuMemFree_v2_p(input));if(output)checked(cuMemFree_v2_p(output));if(module)checked(cuModuleUnload_p(module));
    CUcontext popped=nullptr;if(checked(cuCtxPopCurrent_v2_p(&popped))&&popped!=context)++cleanupErrors;
   }
   checked(cuCtxDestroy_v2_p(context));CUcontext after=nullptr;if(have&&checked(cuCtxGetCurrent_p(&after))&&after!=previous)++cleanupErrors;
  }
  if(driver&&!FreeLibrary(driver))++cleanupErrors;
  context=nullptr;module=nullptr;kernel=nullptr;driver=nullptr;input=output=0;stream=nullptr;ready=attempted=false;
  const char* path=std::getenv("XPU2_FILM_PROFILE");FILE* f=path?std::fopen(path,"wb"):nullptr;
  if(f){std::fprintf(f,"{\"calls\":%llu,\"eligible\":%llu,\"accepted\":%llu,\"replaced\":%llu,\"cpu_skipped\":%llu,\"unsupported\":%llu,\"mismatch\":%llu,\"errors\":%llu,\"cleanup_errors\":%llu,\"total_ns\":%llu,\"initialization_ns\":%llu,\"upload_ns\":%llu,\"launch_ns\":%llu,\"wait_ns\":%llu,\"download_ns\":%llu,\"compare_ns\":%llu}\n",calls,eligible,accepted,replaced,cpuSkipped,unsupported,mismatch,errors,cleanupErrors,total,init,upload,launch,wait,download,compare);std::fclose(f);}
 }
};
State*& storage(){static State* s=nullptr;return s;}
void finish(){if(storage())storage()->finish();}
State& state(){static State* s=[] {auto* p=new State;storage()=p;std::atexit(finish);return p;}();return *s;}
}
extern "C" __declspec(dllexport) int xpu2FilmMode(){return xpu2film::mode();}
extern "C" __declspec(dllexport) int xpu2FilmContribution(const float* src,const float* ref,float* dst,int mask){return xpu2film::state().run(src,ref,dst,unsigned(mask));}

extern "C" __declspec(dllexport) void xpu2FilmFinish(){xpu2film::finish();}
