"""Opt-in host overhead scopes; no queue, ownership or numeric policy changes."""
from .native_gpu_paths import once

HEADER=r'''#pragma once
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <utility>
namespace xpu2oh {
inline bool enabled=false;
inline std::atomic<unsigned long long> ns[24]{},calls[24]{};
inline const char* names[]={"cold_initialize","slot_allocate","request_allocate","ticket_allocate","queue_payload_copy","window_record_copy","native_packet_record","native_packet_replay","pinned_copy","context_push","context_pop","upload_enqueue","launch_enqueue","readback_enqueue","event_record","event_query","event_elapsed","bridge_lock_wait","bridge_lock_hold","queue_lock_wait","queue_lock_hold","request_submit","replay_compare","empty_scope"};
inline unsigned long long begin(){return enabled?std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count():0;}
inline void end(unsigned id,unsigned long long start){if(start){auto stop=begin();ns[id].fetch_add(stop-start,std::memory_order_relaxed);calls[id].fetch_add(1,std::memory_order_relaxed);}}
struct Scope {unsigned id;unsigned long long start;explicit Scope(unsigned i):id(i),start(begin()){}~Scope(){end(id,start);}};
template<class F> decltype(auto) measure(unsigned id,F&& f){Scope s(id);return std::forward<F>(f)();}
inline void reset(){enabled=std::getenv("XPU2_OVERHEAD_PROFILE")!=nullptr;for(unsigned i=0;i<24;++i){ns[i]=0;calls[i]=0;}if(enabled)for(unsigned i=0;i<10000;++i){Scope s(23);}}
inline void finish(){if(!enabled)return;if(FILE* f=std::fopen(std::getenv("XPU2_OVERHEAD_PROFILE"),"a")){std::fputs("{",f);for(unsigned i=0;i<24;++i)std::fprintf(f,"%s\"%s\":{\"ns\":%llu,\"calls\":%llu}",i?",":"",names[i],ns[i].load(),calls[i].load());std::fputs("}\n",f);std::fclose(f);}}
}
'''

def patch(out):
 (out/'native_overhead.h').write_text(HEADER)
 p=out/'early_queue.inc';s=p.read_text();s='#include "native_overhead.h"\n'+s
 s=once(s,'        if(!attempted)initialize();','        if(!attempted)xpu2oh::measure(0,[&]{initialize();});') if s.count('        if(!attempted)initialize();')==1 else s.replace('        if(!attempted)initialize();','        if(!attempted)xpu2oh::measure(0,[&]{initialize();});')
 s=once(s,'        if(!flightsReady)allocateFlights(limit);','        if(!flightsReady)xpu2oh::measure(1,[&]{allocateFlights(limit);});')
 assert s.count('auto request=std::make_shared<Request>();')==2
 s=s.replace('auto request=std::make_shared<Request>();','auto request=xpu2oh::measure(2,[&]{return std::make_shared<Request>();});')
 line='        std::memcpy(request->input,input,count*96);std::memcpy(request->output,native,count*32);'
 s=once(s,line,'        xpu2oh::measure(4,[&]{std::memcpy(request->input,input,count*96);std::memcpy(request->output,native,count*32);});')
 line='        std::memcpy(request->input,input,count*96);std::memcpy(request->output,output,count*32);'
 s=once(s,line,'        xpu2oh::measure(4,[&]{std::memcpy(request->input,input,count*96);std::memcpy(request->output,output,count*32);});')
 s=once(s,'        std::memcpy(s.input(),input,count*96);','        xpu2oh::measure(8,[&]{std::memcpy(s.input(),input,count*96);});')
 # Instrument only the asynchronous bridge methods, retaining lock lifetime.
 a=s.index('bool startFlight(');b=s.index('    void summary()',a);part=s[a:b]
 lock='    std::lock_guard<std::mutex> lock(mutex);'
 assert part.count(lock)==3
 part=part.replace(lock,'    auto lockStart=xpu2oh::begin();std::lock_guard<std::mutex> lock(mutex);xpu2oh::end(17,lockStart);xpu2oh::Scope lockHeld(18);')
 part=part.replace('fn_cuCtxPushCurrent_v2(context)','xpu2oh::measure(9,[&]{return fn_cuCtxPushCurrent_v2(context);})')
 part=part.replace('fn_cuCtxPopCurrent_v2(&popped)','xpu2oh::measure(10,[&]{return fn_cuCtxPopCurrent_v2(&popped);})')
 # Calls are one line in the frozen source, so balanced matching is explicit.
 import re
 ids={'cuMemcpyHtoDAsync_v2':11,'cuLaunchKernel':12,'cuMemcpyDtoHAsync_v2':13,'cuEventRecord':14,'cuEventQuery':15,'cuEventElapsedTime':16}
 for api,ident in ids.items():
  pattern=r'fn_'+api+r'\('
  starts=[m.start() for m in re.finditer(pattern,part)]
  for start in reversed(starts):
   end=start+len('fn_'+api);level=0
   for pos in range(end,len(part)):
    if part[pos]=='(':level+=1
    elif part[pos]==')':
     level-=1
     if level==0:end=pos+1;break
   call=part[start:end];part=part[:start]+f'xpu2oh::measure({ident},[&]{{return {call};}})'+part[end:]
 s=s[:a]+part+s[b:]
 # Queue publication locks; never change ownership or notification order.
 a=s.index('    Ticket submit(');b=s.index('    void releaseCredit(',a);part=s[a:b]
 part=part.replace('        std::lock_guard<std::mutex> lock(mutex);','        auto lockStart=xpu2oh::begin();std::lock_guard<std::mutex> lock(mutex);xpu2oh::end(19,lockStart);xpu2oh::Scope lockHeld(20);')
 anchor='                        std::shared_ptr<const void> resources,const uint32_t* pixels,bool notify=true) {'
 part=once(part,anchor,anchor+'\n        xpu2oh::Scope submitScope(21);')
 s=s[:a]+part+s[b:];p.write_text(s)
 p=out/'native_gpu_early.h';s=p.read_text()
 s=s.replace('std::make_unique<Queue::Ticket>()','xpu2oh::measure(3,[&]{return std::make_unique<Queue::Ticket>();})')
 line='        std::memcpy(p.input,input,sizeof(p.input));std::memcpy(p.pixels,pixels,sizeof(p.pixels));'
 s=once(s,line,'        xpu2oh::measure(5,[&]{std::memcpy(p.input,input,sizeof(p.input));std::memcpy(p.pixels,pixels,sizeof(p.pixels));});')
 compare='std::memcmp(p.input,input,sizeof(p.input)) || std::memcmp(p.pixels,pixels,sizeof(p.pixels))'
 s=once(s,compare,'xpu2oh::measure(22,[&]{return '+compare+';})')
 s+='''\nextern "C" uint64_t CPP_gpuOverheadBegin(){return xpu2oh::begin();}
extern "C" void CPP_gpuOverheadPacketEnd(uint64_t start){xpu2oh::end(xpu2::nativepath::recordingWindow()?6:7,start);}
''';p.write_text(s)
 p=out/'native_gpu_paths.inc';s=p.read_text();s=once(s,'    shaderBegin();earlyReset();','    xpu2oh::reset();shaderBegin();earlyReset();');s=once(s,'    earlyFinish();shaderFinish(epoch);','    earlyFinish();shaderFinish(epoch);xpu2oh::finish();');p.write_text(s)
 p=out/'PathIntegratorUtil.ispc';s=p.read_text();anchor='inline uniform bool xpu2PrepareLobe('
 s=once(s,anchor,'extern "C" uniform uint64 CPP_gpuOverheadBegin();\nextern "C" void CPP_gpuOverheadPacketEnd(uniform uint64 start);\n'+anchor)
 s=once(s,'            uniform float xpu2GroupInput[16*192];','            uniform uint64 overheadStart=CPP_gpuOverheadBegin();\n            uniform float xpu2GroupInput[16*192];')
 anchor='            if(xpu2Grouped)CPP_gpuEarlySubmitGroup(xpu2GroupInput,xpu2GroupPixels,reduce_max(lobeSampleCount),xpu2Tokens);'
 s=once(s,anchor,'            CPP_gpuOverheadPacketEnd(overheadStart);\n'+anchor);p.write_text(s)
