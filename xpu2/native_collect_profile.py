"""Opt-in bounded spin before sleeping for native GPU completion."""
from pathlib import Path
from . import native_integration_profile as base
from .native_gpu_paths import once
HERE=Path(__file__).resolve().parent
adapter=base.adapter
cpp=base.cpp
queue=base.queue
profile=base.profile
cuda=base.cuda
shadow_header=base.shadow_header
driver=base.driver
ispc=base.ispc
multisampler=base.multisampler
bundled=base.bundled

def header(text):
    text=base.header(text)
    text=once(text,'inline void integrationReset(){','inline void integrationReset(){collectReset();')
    text=once(text,'inline void integrationFinish(){','inline void integrationFinish(){collectFinish();')
    anchor='    xpu2::nativepath::IntegrationTimer timer(5);'
    text=once(text,anchor,anchor+r'''
    using namespace xpu2::nativepath;
    if(collectSpinUs){
        ++collectFastCalls;
        std::fill(result,result+64,std::numeric_limits<float>::quiet_NaN());
        if(!token){++collectZero;earlyFallback+=8;return;}
        std::unique_ptr<Queue::Ticket> owner(reinterpret_cast<Queue::Ticket*>(token));
        const auto& ticket=*owner;
        if(tls->isCanceled()){shaderQueue->cancel(ticket);++collectCanceled;earlyFallback+=8;return;}
        auto status=shaderQueue->tryCollect(ticket,epoch,result);
        if(status==Collect::Ready){++collectImmediate;}
        else {
            if(status!=Collect::Pending)throw std::logic_error("Invalid early GPU completion");
            ++earlyWaits;
            const auto start=std::chrono::steady_clock::now();
            const auto spinEnd=start+std::chrono::microseconds(collectSpinUs);
            const auto deadline=start+std::chrono::seconds(10);
            unsigned polls=0;bool slept=false;
            while(status==Collect::Pending){
                if(tls->isCanceled()){shaderQueue->cancel(ticket);++collectCanceled;collectPolls+=polls;earlyFallback+=8;return;}
                auto now=std::chrono::steady_clock::now();
                if(now>=deadline){shaderQueue->cancel(ticket);++collectCanceled;collectPolls+=polls;earlyFallback+=8;++earlyTimeouts;return;}
                if(now<spinEnd){
                    const auto next=std::min(spinEnd,now+std::chrono::microseconds(2));
                    do {_mm_pause();}while(std::chrono::steady_clock::now()<next);
                }else{
                    if(!slept){slept=true;++collectSlept;}
                    std::unique_lock<std::mutex> lock(shaderQueue->mutex);
                    ticket->completed.wait_for(lock,std::chrono::milliseconds(2),[&]{return ticket->done||ticket->cancelled;});
                }
                status=shaderQueue->tryCollect(ticket,epoch,result);++polls;
                if(status!=Collect::Pending && status!=Collect::Ready)throw std::logic_error("Invalid early GPU completion");
            }
            collectPolls+=polls;
            if(!slept)++collectSpinReady;
        }
        unsigned collected=0;
        for(unsigned lane=0;lane<8;++lane)collected+=finiteBits(result[lane*8+3]);
        earlyCollected+=collected;earlyFallback+=8-collected;
        return;
    }
''')
    return (HERE/'native_collect_profile.inc').read_text(encoding='utf-8-sig')+'\n'+text
