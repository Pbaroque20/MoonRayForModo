// Diagnostic process-exit aggregate. No production DLL-unload lifecycle implied.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
namespace xpu2profile {
using Clock=std::chrono::steady_clock;
#define PROFILE_FIELDS(X) \
 X(device_total_ns) X(initialization_ns) X(htod_ns) X(launch_ns) X(device_wait_ns) \
 X(dtoh_ns) X(validation_ns) X(diagnostic_io_ns) X(worker_pack_ns) \
 X(queue_residence_ns) X(collect_ns) X(collect_wait_ns) X(cpu_light_ns) X(kernel_gpu_ns) \
 X(submitted) X(collected) X(batches) X(samples) X(accepted) X(replaced) \
 X(unsupported) X(invalid) X(mismatch) X(errors)
struct Metrics {
 bool enabled=false, quiet=false;
 FILE* file=nullptr;
#define FIELD(n) std::atomic<unsigned long long> n{0};
 PROFILE_FIELDS(FIELD)
#undef FIELD
 Metrics() {
  const char* path=std::getenv("XPU2_PROFILE_FILE");
  enabled=path && *path;
  const char* q=std::getenv("XPU2_PROFILE_QUIET");
  quiet=enabled && q && !std::strcmp(q,"1");
  if(enabled)file=std::fopen(path,"wb");
 }
 void write() {
  if(!file)return;
  std::fprintf(file,"{\"quiet\":%s",quiet?"true":"false");
#define WRITE(n) std::fprintf(file,",\"" #n "\":%llu",n.load());
  PROFILE_FIELDS(WRITE)
#undef WRITE
  std::fprintf(file,"}\n");std::fclose(file);file=nullptr;
 }
};
Metrics*& storage(){static Metrics* value=nullptr;return value;}
void finish(){if(storage())storage()->write();}
Metrics& metrics(){static Metrics* value=[](){auto* m=new Metrics;storage()=m;if(m->enabled)std::atexit(finish);return m;}();return *value;}
bool quiet(){return metrics().quiet;}
void add(std::atomic<unsigned long long>& v,unsigned long long n=1){if(metrics().enabled)v.fetch_add(n,std::memory_order_relaxed);}
unsigned long long stamp(){return metrics().enabled ? std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count() : 0;}
void elapsed(std::atomic<unsigned long long>& v,unsigned long long start){if(start)add(v,stamp()-start);}
struct Span {
 std::atomic<unsigned long long>& target; unsigned long long start;
 explicit Span(std::atomic<unsigned long long>& v):target(v),start(stamp()){}
 ~Span(){elapsed(target,start);}
};
#undef PROFILE_FIELDS
}
