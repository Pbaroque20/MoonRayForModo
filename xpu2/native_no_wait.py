'Opt-in opportunistic GPU admission and immediate native fallback on late results.'
import shutil
from pathlib import Path
from .native_gpu_paths import once

def patch(out):
 shutil.copyfile(Path(__file__).with_name('no_wait.h'),out/'no_wait.h')
 p=out/'early_queue.inc';s='#include "no_wait.h"\n'+p.read_text()
 s=once(s,'    unsigned producers=0;','    bool noWait=xpu2::nowait::enabled();unsigned admissionFlights=0;\n    uint64_t noWaitRefused=0,noWaitMiss=0;\n    unsigned producers=0;')
 s=once(s,'        // Credit includes completed but uncollected results, not just pending work.', '''        if(noWait && !xpu2::nowait::admit(admissionFlights,flights,pending.size(),1,batchLimit)){++noWaitRefused;++full;return {};}
        // Credit includes completed but uncollected results, not just pending work.''')
 s=once(s,'    // Caller holds mutex. A null output reserves', '''    Collect collectOrCancel(const Ticket& request,uint64_t revision,float* output){
        std::lock_guard<std::mutex> lock(mutex);
        const auto status=tryCollectLocked(request,revision,output);
        if(status==Collect::Pending){cancelLocked(request);++noWaitMiss;}
        return status;
    }
    // Caller holds mutex. A null output reserves''')
 s=once(s,'                    selectionNs+=', '                    if(!f.requests.empty())++admissionFlights;\n                    selectionNs+=')
 s=once(s,'            f.packed=false;f.requests.clear();','            if(!admissionFlights)std::terminate();--admissionFlights;\n            f.packed=false;f.requests.clear();')
 s=once(s,'    ~Queue(){if(worker.joinable())std::terminate();if(log)std::fclose(log);}', '''    ~Queue(){if(worker.joinable()||admissionFlights)std::terminate();if(log)std::fclose(log);
        xpu2::nowait::report("sampler",noWait,noWaitRefused,noWaitMiss,admissionFlights,pending.size(),retainedAsync);
    }''')
 s=once(s,'        unsigned active=0;','        bool noWaitHeld=false;\n        unsigned active=0;')
 s=once(s,'                bool started=false;','''                if(noWait && !noWaitHeld && xpu2::nowait::flag("XPU2_NO_WAIT_HOLD_FIRST")){
                    noWaitHeld=true;std::fprintf(stdout,"@@XPU2_NO_WAIT_HELD\\n");std::fflush(stdout);
                    std::this_thread::sleep_for(std::chrono::milliseconds(150));
                }
                bool started=false;''')
 p.write_text(s)
 p=out/'native_gpu_early.h';s=p.read_text()
 s=once(s,'    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);bool waited=false,helped=false;', '''    if(shaderQueue->noWait){
        if(tls->isCanceled()){shaderQueue->cancel(ticket);earlyFallback+=8;return;}
        const auto status=shaderQueue->collectOrCancel(ticket,epoch,result);
        if(status==Collect::Pending){earlyFallback+=8;return;}
        if(status!=Collect::Ready)throw std::logic_error("Invalid opportunistic completion");
        for(unsigned lane=0;lane<8;++lane){if(finiteBits(result[lane*8+3]))++earlyCollected;else ++earlyFallback;}
        return;
    }
    const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);bool waited=false,helped=false;''')
 s=once(s,'    bool stopping=false,broken=false;unsigned credits=0,capacity=4096,mode=0;uint64_t next=0;', '''    bool stopping=false,broken=false;unsigned credits=0,capacity=4096,mode=0;uint64_t next=0;
    bool noWait=xpu2::nowait::enabled();unsigned admissionFlights=0;uint64_t noWaitRefused=0,noWaitMiss=0;
    bool canAdmit(unsigned count){
        if(!noWait)return true;
        size_t queued=0;for(const auto& j:pending)queued+=j->count;
        if(xpu2::nowait::admit(admissionFlights,2,queued,count,512))return true;
        ++noWaitRefused;return false;
    }''')
 s=once(s,'bool busy=false;std::vector<std::shared_ptr<Job>> jobs;', 'bool busy=false,reserved=false;std::vector<std::shared_ptr<Job>> jobs;')
 s=once(s,'if(stopping||broken||count>capacity-std::min(credits,capacity))', 'if(stopping||broken||!canAdmit(count)||count>capacity-std::min(credits,capacity))')
 s=once(s,'if(stopping||broken||lanes>capacity-std::min(credits,capacity))', 'if(stopping||broken||!canAdmit(lanes)||lanes>capacity-std::min(credits,capacity))')
 s=once(s,'            slot.jobs.push_back(j);slot.count+=j->count;', '''            if(!slot.reserved){slot.reserved=true;++admissionFlights;}
            slot.jobs.push_back(j);slot.count+=j->count;''')
 s=once(s,'        bool waited=false;const auto deadline=Clock::now()+std::chrono::seconds(15);', '''        if(noWait && !j->done){
            j->canceled=true;j->consumed=true;++canceled;++noWaitMiss;owners.erase(it);
            auto queued=std::find(pending.begin(),pending.end(),j);
            if(queued!=pending.end()){pending.erase(queued);j->done=true;}
            release(j);changed.notify_all();return;
        }
        bool waited=false;const auto deadline=Clock::now()+std::chrono::seconds(15);''')
 s=once(s,'        s.jobs.clear();s.count=0;s.busy=false;changed.notify_all();', '''        if(s.reserved){if(!admissionFlights)std::terminate();--admissionFlights;s.reserved=false;}
        s.jobs.clear();s.count=0;s.busy=false;changed.notify_all();''')
 s=once(s,'        if(lazy.active)throw std::logic_error("Lazy native owner did not retire its window");', '''        if(admissionFlights)throw std::logic_error("Light flight admission retained");
        xpu2::nowait::report("light",noWait,noWaitRefused,noWaitMiss,admissionFlights,pending.size(),credits);
        if(lazy.active)throw std::logic_error("Lazy native owner did not retire its window");''')
 p.write_text(s)
