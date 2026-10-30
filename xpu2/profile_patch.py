"""Guarded instrumentation of a frozen diagnostic; default builds stay unchanged."""
def replace(text, old, new, count=1):
    if text.count(old)!=count:
        raise ValueError('Profiling patch anchor drift: '+old[:90])
    return text.replace(old,new)

def apply(queue, bridge, header):
    # Header is embedded after cstring and before the implementation namespaces.
    queue=replace(queue,'namespace {\nusing U=uint32_t;',header+'\nnamespace {\nusing U=uint32_t;')
    def q(old,new,count=1):
        nonlocal queue
        queue=replace(queue,old,new,count)
    q('void summary() {\n        if(!log)return;', 'void summary() {\n        xpu2profile::Span timing(xpu2profile::metrics().diagnostic_io_ns);\n        if(xpu2profile::quiet() || !log)return;')
    q('if(path) {records=std::fopen(path,"wb");','if(path && !xpu2profile::quiet()) {records=std::fopen(path,"wb");')
    q('void initialize() {','void initialize() {\n        xpu2profile::Span timing(xpu2profile::metrics().initialization_ns);')
    q('void run(float* input,float* output,int count) {\n        if(!mode', 'void run(float* input,float* output,int count) {\n        auto& prof=xpu2profile::metrics();xpu2profile::Span timing(prof.device_total_ns);\n        if(!mode')
    q('++batches;samples+=count;','++batches;samples+=count;xpu2profile::add(prof.batches);xpu2profile::add(prof.samples,count);')
    q('check(fn_cuMemcpyHtoD_v2(buffers[0],input,count*96));','{xpu2profile::Span t(prof.htod_ns);check(fn_cuMemcpyHtoD_v2(buffers[0],input,count*96));')
    q('check(fn_cuMemcpyHtoD_v2(buffers[1],lengths,count*4));','check(fn_cuMemcpyHtoD_v2(buffers[1],lengths,count*4));}')
    q('check(fn_cuEventRecord(beginEvent,nullptr));','{xpu2profile::Span t(prof.launch_ns);check(fn_cuEventRecord(beginEvent,nullptr));')
    q('check(fn_cuEventRecord(endEvent,nullptr));\n            for(;;)', 'check(fn_cuEventRecord(endEvent,nullptr));}\n            {xpu2profile::Span t(prof.device_wait_ns);for(;;)')
    q('gpuPending.store(false);\n            float ms','}gpuPending.store(false);\n            float ms')
    q('kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));','kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));xpu2profile::add(prof.kernel_gpu_ns,(unsigned long long)(ms*1000000));')
    q('check(fn_cuMemcpyDtoH_v2(returned,buffers[2],count*96));','{xpu2profile::Span t(prof.dtoh_ns);check(fn_cuMemcpyDtoH_v2(returned,buffers[2],count*96));')
    q('check(fn_cuMemcpyDtoH_v2(result,buffers[3],count*36));','check(fn_cuMemcpyDtoH_v2(result,buffers[3],count*36));}')
    q('for(int i=0;i<count;++i) {\n                U native', '{xpu2profile::Span t(prof.validation_ns);for(int i=0;i<count;++i) {\n                U native')
    q('if(records) {std::fwrite(input','if(records) {xpu2profile::Span io(prof.diagnostic_io_ns);std::fwrite(input')
    for name in ('unsupported','invalid','mismatch'):
        q('++'+name+';continue;', '++'+name+';xpu2profile::add(prof.'+name+');continue;')
    q('++accepted;','++accepted;xpu2profile::add(prof.accepted);')
    q('++replaced;','++replaced;xpu2profile::add(prof.replaced);')
    q('++errors;', '++errors;xpu2profile::add(prof.errors);',5)
    q('} catch(const std::exception& e)', '} } catch(const std::exception& e)')
    q('uint64_t revision=0;', 'uint64_t revision=0;\n    unsigned long long queuedAt=0;')
    q('void snapshot() {\n        if(!log)return;', 'void snapshot() {\n        xpu2profile::Span timing(xpu2profile::metrics().diagnostic_io_ns);\n        if(xpu2profile::quiet() || !log)return;')
    q('pending.push_back(request);++submitted;++retainedAsync;', 'request->queuedAt=xpu2profile::stamp();xpu2profile::add(xpu2profile::metrics().submitted);\n        pending.push_back(request);++submitted;++retainedAsync;')
    q('request->consumed=true;++delivered;releaseCredit(request);','request->consumed=true;++delivered;releaseCredit(request);xpu2profile::add(xpu2profile::metrics().collected);')
    q('if(log)std::fprintf(log,"{\\\"delivered_id', 'if(log && !xpu2profile::quiet())std::fprintf(log,"{\\\"delivered_id',2)
    q('int count=0;for(auto &r:batch)count+=r->count;', 'auto& prof=xpu2profile::metrics();\n            for(auto &r:batch)xpu2profile::elapsed(prof.queue_residence_ns,r->queuedAt);\n            const auto packStart=xpu2profile::stamp();\n            int count=0;for(auto &r:batch)count+=r->count;')
    q('bool failure=false;', 'xpu2profile::elapsed(prof.worker_pack_ns,packStart);\n            bool failure=false;')
    q('if(device.records)std::fflush(device.records);','if(device.records){xpu2profile::Span io(prof.diagnostic_io_ns);std::fflush(device.records);}')
    bridge=replace(bridge,'#include "native_lambert_queue.cc"',queue)
    bridge=replace(bridge,'bool open=false, sampling=false, light=false;', 'bool open=false, sampling=false, light=false;\n    unsigned long long lightStart=0;')
    bridge=replace(bridge,'void write(){\n        if(!file)return;', 'void write(){\n        xpu2profile::Span timing(xpu2profile::metrics().diagnostic_io_ns);\n        if(xpu2profile::quiet() || !file)return;')
    bridge=replace(bridge,'current().light=true;++activeCpu;', 'current().light=true;++activeCpu;current().lightStart=xpu2profile::stamp();')
    bridge=replace(bridge,'if(current().light){--activeCpu;', 'if(current().light){xpu2profile::elapsed(xpu2profile::metrics().cpu_light_ns,current().lightStart);--activeCpu;')
    bridge=replace(bridge,'void xpu2BatchedCollect(float* post,int mask,int slot){', 'void xpu2BatchedCollect(float* post,int mask,int slot){\n    xpu2profile::Span timing(xpu2profile::metrics().collect_ns);')
    bridge=replace(bridge,'std::unique_lock<std::mutex> lock(q.mutex);', 'xpu2profile::Span waitTiming(xpu2profile::metrics().collect_wait_ns);\n                std::unique_lock<std::mutex> lock(q.mutex);')
    return bridge
