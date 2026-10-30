"""Add diagnostic host intervals and calibrated CUDA intervals to frozen sources."""
from .native_gpu_paths import once

def patch(out):
    q=(out/'early_queue.inc').read_text(encoding='utf-8')
    q='#include "native_timeline.h"\n'+q
    q=once(q,'CUevent begin=nullptr,end=nullptr,done=nullptr;', 'CUevent begin=nullptr,end=nullptr,done=nullptr,upload=nullptr;\n    uint64_t traceId=0;')
    q=once(q,'FlightSlot slots[4];','FlightSlot slots[4];\nCUevent traceAnchor=nullptr;uint64_t traceHostAnchor=0,traceSequence=0;')
    q=once(q,'check(fn_cuEventCreate(&s.done,CU_EVENT_DISABLE_TIMING));','''check(fn_cuEventCreate(&s.done,xpu2trace::enabled?0:CU_EVENT_DISABLE_TIMING));
        if(xpu2trace::enabled)check(fn_cuEventCreate(&s.upload,0));''')
    q=once(q,'    flightLimit=limit;flightsReady=true;', '''    if(xpu2trace::enabled){
        check(fn_cuEventCreate(&traceAnchor,0));
        const uint64_t lo=xpu2trace::now();
        check(fn_cuEventRecord(traceAnchor,slots[0].stream));
        check(fn_cuEventSynchronize(traceAnchor));
        const uint64_t hi=xpu2trace::now();traceHostAnchor=lo+(hi-lo)/2;
        xpu2trace::record(20,lo,hi); // Correlation uncertainty bracket.
    }
    flightLimit=limit;flightsReady=true;''')
    q=once(q,'        if(s.done && release(fn_cuEventDestroy_v2(s.done)))s.done=nullptr;', '''        if(s.done && release(fn_cuEventDestroy_v2(s.done)))s.done=nullptr;
        if(s.upload && release(fn_cuEventDestroy_v2(s.upload)))s.upload=nullptr;''')
    q=once(q,'    for(auto& s:slots){\n        for(auto& p:s.device)', r"""    if(traceAnchor){
        CUevent last=nullptr;
        if(fn_cuEventCreate(&last,0)==CUDA_SUCCESS){
            const auto lo=xpu2trace::now();
            if(fn_cuEventRecord(last,slots[0].stream)==CUDA_SUCCESS && fn_cuEventSynchronize(last)==CUDA_SUCCESS){
                const auto hi=xpu2trace::now();float ms=0;
                if(fn_cuEventElapsedTime(&ms,traceAnchor,last)==CUDA_SUCCESS)
                    xpu2trace::record(25,lo,hi,traceHostAnchor+uint64_t(double(ms)*1000000.0)-xpu2trace::origin);
            }
            release(fn_cuEventDestroy_v2(last));
        }
    }
    for(auto& s:slots){
        for(auto& p:s.device)""")
    q=once(q,'    flightsReady=false;','    if(traceAnchor && release(fn_cuEventDestroy_v2(traceAnchor)))traceAnchor=nullptr;\n    flightsReady=false;')
    q=once(q,'        std::memcpy(s.input(),input,count*96);','''        s.traceId=++traceSequence;
        xpu2trace::Scope submitTrace(13,s.traceId);
        std::memcpy(s.input(),input,count*96);''')
    q=once(q,'        if(packed){\n            check(fn_cuMemcpyHtoDAsync_v2', '''        if(xpu2trace::enabled)check(fn_cuEventRecord(s.upload,s.stream));
        if(packed){
            check(fn_cuMemcpyHtoDAsync_v2''')
    anchor='            kernelMicroseconds.fetch_add((unsigned long long)(ms*1000));'
    split=q.index('void finishFlight(');tail=q.index('    bool close(',split) if '    bool close(' in q[split:] else q.index('    void initialize(',split)
    head,body,rest=q[:split],q[split:tail],q[tail:]
    body=once(body,anchor,anchor+'''
            if(xpu2trace::enabled){
                float a=0,b=0,c=0,d=0;
                check(fn_cuEventElapsedTime(&a,traceAnchor,s.upload));
                check(fn_cuEventElapsedTime(&b,traceAnchor,s.begin));
                check(fn_cuEventElapsedTime(&c,traceAnchor,s.end));
                check(fn_cuEventElapsedTime(&d,traceAnchor,s.done));
                auto stamp=[&](float t){return traceHostAnchor+uint64_t(double(t)*1000000.0);};
                xpu2trace::record(21,stamp(a),stamp(b),s.traceId,index+1);
                xpu2trace::record(22,stamp(b),stamp(c),s.traceId,index+1);
                xpu2trace::record(23,stamp(c),stamp(d),s.traceId,index+1);
            }''')
    q=head+body+rest
    q=once(q,'            const auto retireStart=std::chrono::steady_clock::now();','            xpu2trace::Scope retireTrace(14,device.slots[i].traceId);\n            const auto retireStart=std::chrono::steady_clock::now();')
    q=once(q,'                const auto packStart=std::chrono::steady_clock::now();','                const auto tracePack=xpu2trace::now();\n                const auto packStart=std::chrono::steady_clock::now();')
    q=once(q,'                f.started=std::chrono::steady_clock::now();','                xpu2trace::end(12,tracePack);\n                f.started=std::chrono::steady_clock::now();')
    q=once(q,'                const bool started=device.startFlight(i,flights,f.inputData(),f.count);','                const auto traceDispatch=xpu2trace::now();\n                const bool started=device.startFlight(i,flights,f.inputData(),f.count);\n                xpu2trace::end(11,traceDispatch);')
    q=once(q,'                if(status){retire(i,status<0);progress=true;}', '                if(status){const auto seen=xpu2trace::now();xpu2trace::record(16,seen,seen,device.slots[i].traceId);retire(i,status<0);progress=true;}')
    begin=q.index('    void workFlights()');end=q.index('    void work() ',begin)
    part=q[begin:end]
    part=once(part,'                available.wait(lock,[&]{return stopping || !pending.empty();});','''                const auto traceIdle=xpu2trace::now();
                available.wait(lock,[&]{return stopping || !pending.empty();});
                xpu2trace::end(15,traceIdle);''')
    q=q[:begin]+part+q[end:]
    (out/'early_queue.inc').write_text(q,encoding='utf-8')
    h=(out/'native_gpu_early.h').read_text(encoding='utf-8')
    h=once(h,'    if(!integrationProfile)return 0;','    if(!integrationProfile && !xpu2trace::enabled)return 0;')
    h=once(h,'    integrationNs[phase]+=integrationBegin()-start;++integrationCalls[phase];','''    const auto ended=integrationBegin();
    if(xpu2trace::enabled && (phase==0 || phase==3 || phase==4))xpu2trace::record(phase,start,ended);
    if(integrationProfile){integrationNs[phase]+=ended-start;++integrationCalls[phase];}''')
    h=once(h,'        ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return ticket->done||ticket->cancelled;});','''        const auto traceWait=xpu2trace::now();
        ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return ticket->done||ticket->cancelled;});
        xpu2trace::end(10,traceWait,ticket->id);''')
    (out/'native_gpu_early.h').write_text(h,encoding='utf-8')
    s=(out/'native_gpu_shading.h').read_text(encoding='utf-8')
    s=once(s,'    shaderQueue=std::make_unique<Queue>();','    xpu2trace::reset();\n    shaderQueue=std::make_unique<Queue>();')
    s=once(s,'    shaderQueue.reset();','    shaderQueue.reset();\n    xpu2trace::finish();')
    (out/'native_gpu_shading.h').write_text(s,encoding='utf-8')
