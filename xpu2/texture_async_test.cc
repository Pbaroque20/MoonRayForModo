#include "texture_async.h"
#include <atomic>
#include <chrono>
#include <iostream>
using namespace xpu2::texture;
using Async=AsyncTextureLoader;
static unsigned checks=0;
static void check(bool ok,const char* why){++checks;if(!ok)throw std::runtime_error(why);}
template<class F> static void until(F ready){auto end=std::chrono::steady_clock::now()+std::chrono::seconds(5);while(!ready()){if(std::chrono::steady_clock::now()>end)throw std::runtime_error("Async wait timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}}
template<class F> static void rejects(F f){bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}check(rejected,"Expected rejection");}
static Key key(unsigned rev=1){return {"fixture","raw",rev};}
static Bytes decode(const Key& k,size_t n){return Bytes(n,uint8_t(k.revision));}
struct Gate {
    std::mutex mutex;std::condition_variable cv;bool open=false;
    void release(){std::lock_guard<std::mutex> lock(mutex);open=true;cv.notify_all();}
    void wait(){std::unique_lock<std::mutex> lock(mutex);if(!cv.wait_for(lock,std::chrono::seconds(5),[&]{return open;}))throw std::runtime_error("Gate timeout");}
};
struct Release {Gate& gate;~Release(){gate.release();}};
struct DecoderLifetime {
    std::thread::id coordinator;std::atomic<bool>& offThread;
    ~DecoderLifetime(){offThread=std::this_thread::get_id()!=coordinator;}
};
struct Page:DevicePage{Bytes data;explicit Page(const Bytes& b):data(b){}bool ready()override{return true;}void wait()override{}uint64_t address()const override{return reinterpret_cast<uint64_t>(data.data());}};
struct BackendTest:Backend{std::shared_ptr<DevicePage> upload(const Bytes& b)override{return std::make_shared<Page>(b);}void drain()override{}};
struct Done:Fence{bool ready()override{return true;}void wait()override{}};
int main(){try{
    const auto mainThread=std::this_thread::get_id();
    {
        std::atomic<bool> destroyedOff{false};
        Async worker([&]{auto lifetime=std::make_shared<DecoderLifetime>(DecoderLifetime{mainThread,destroyedOff});return [lifetime](const Key& k,size_t n){return decode(k,n);};},16,1);
        auto t=*worker.submit(key(),16);until([&]{return worker.state(t)==Async::State::Ready;});
        destroyedOff=false;worker.close();check(destroyedOff,"Decoder destroyed on coordinator");
        check(worker.stats().heldBytes==0&&worker.stats().heldRecords==0,"Close retained ready result");
    }
    {
        Gate gate;std::atomic<bool> factoryOff{false},decodeOff{false};
        Async worker([&]{factoryOff=std::this_thread::get_id()!=mainThread;return [&](const Key& k,size_t n){decodeOff=std::this_thread::get_id()!=mainThread;gate.wait();return decode(k,n);};},32,2);
        Release release{gate};auto old=*worker.submit(key(),16);until([&]{return worker.state(old)==Async::State::Loading&&decodeOff.load();});
        check(factoryOff&&decodeOff,"Decode did not leave coordinator");
        check(worker.submit(key(),16)->id==old.id,"Duplicate job created");rejects([&]{worker.submit(key(),15);});
        auto queued=*worker.submit(key(2),16);check(!worker.submit(key(3),1),"Record/byte limit ignored");
        worker.cancel(queued);check(worker.state(queued)==Async::State::Gone,"Queued cancellation retained work");
        worker.cancel(old);check(worker.state(old)==Async::State::Cancelled&&worker.stats().heldBytes==16,"Active cancellation freed budget too early");
        auto replacement=*worker.submit(key(),16);check(replacement.id!=old.id,"Cancelled key reused old ticket");
        check(!worker.submit(key(3),1),"Cancelled active decode escaped accounting");gate.release();
        until([&]{return worker.state(replacement)==Async::State::Ready;});
        check(worker.state(old)==Async::State::Gone,"Cancelled decode published old result");
        check(worker.submit(key(),16)->id==replacement.id,"Old completion removed replacement mapping");
        check(*worker.take(replacement)==decode(key(),16),"Replacement data wrong");check(!worker.take(old),"Stale ticket produced data");
        auto revision=*worker.submit(key(2),16);until([&]{return worker.state(revision)==Async::State::Ready;});
        check(*worker.take(revision)==decode(key(2),16),"Revision aliased old data");
        auto ready=*worker.submit(key(3),16);until([&]{return worker.state(ready)==Async::State::Ready;});worker.cancel(ready);
        check(worker.stats().heldBytes==0&&worker.stats().peakBytes<=32,"Ready cancellation leaked/exceeded budget");
        rejects([&]{worker.submit(key(),33);});rejects([&]{worker.submit(key(),0);});rejects([&]{worker.state({{},old.id});});
        worker.close();check(worker.stats().heldRecords==0,"Shutdown leaked records");rejects([&]{worker.submit(key(),16);});
    }
    {
        Gate gate;Async worker([&]{return [&](const Key& k,size_t n){gate.wait();return decode(k,n);};},64,4);Release release{gate};
        auto active=*worker.submit(key(),16);until([&]{return worker.state(active)==Async::State::Loading;});
        auto queued=*worker.submit(key(2),16);worker.cancelAll();auto next=*worker.submit(key(3),16);
        check(worker.state(queued)==Async::State::Gone&&worker.stats().heldBytes==32,"Generation cancellation accounting wrong");gate.release();
        until([&]{return worker.state(next)==Async::State::Ready;});check(!worker.take(active),"Old generation published after cancellation");
        check(*worker.take(next)==decode(key(3),16),"New generation lost");worker.close();
    }
    {
        std::atomic<unsigned> calls{0};Async worker([&]{return [&](const Key& k,size_t n){auto call=++calls;if(call==1)throw std::runtime_error("Injected decode failure");if(call==2)return Bytes(1);return decode(k,n);};},16,1);
        for(int i=0;i<2;++i){auto t=*worker.submit(key(),16);until([&]{return worker.state(t)==Async::State::Failed;});check(worker.stats().heldBytes==16,"Failure not bounded until consumed");rejects([&]{worker.take(t);});check(worker.stats().heldBytes==0,"Failure retained budget");}
        auto t=*worker.submit(key(),16);until([&]{return worker.state(t)==Async::State::Ready;});check(*worker.take(t)==decode(key(),16),"Retry failed");check(worker.stats().failures==2,"Failure counter wrong");
        worker.close();
        Async broken([]()->Cache::Loader{throw std::runtime_error("Factory failure");},16,1);auto b=*broken.submit(key(),16);until([&]{return broken.state(b)==Async::State::Failed;});rejects([&]{broken.take(b);});broken.close();
    }
    {
        BackendTest device;Cache cache(device,{16,16,16});Async worker([]{return decode;},32,2);
        auto held=cache.acquire(key(),16,decode,false);check(bool(held),"Initial cache failed");
        check(!acquireAsync(cache,worker,key(2),16,false),"Decode completed synchronously");
        auto ticket=*worker.submit(key(2),16);until([&]{return worker.state(ticket)==Async::State::Ready;});
        check(!acquireAsync(cache,worker,key(2),16,false)&&worker.stats().heldBytes==16,"Blocked cache consumed ready data");
        cache.release(*held);auto next=acquireAsync(cache,worker,key(2),16,false);check(next&&cache.cpu(*next)==decode(key(2),16),"Cache handoff wrong");
        check(worker.stats().heldBytes==0,"Handoff retained queue bytes");cache.release(*next);auto loads=worker.stats().loads;
        auto hit=acquireAsync(cache,worker,key(2),16,false);check(hit&&worker.stats().loads==loads&&worker.stats().heldRecords==0,"Cache hit queued decode");cache.release(*hit);
        std::optional<Cache::Lease> gpu;until([&]{gpu=acquireAsync(cache,worker,key(2),16,true);return bool(gpu);});cache.retire(*gpu,std::make_shared<Done>());
        check(worker.stats().loads==loads,"GPU upload redecoded RAM backing");worker.close();check(cache.close(),"Cache shutdown failed");
    }
    {
        Async worker([]{return decode;},64,4);
        for(unsigned batch=0;batch<250;++batch){std::vector<Async::Ticket> jobs;for(unsigned j=0;j<4;++j)jobs.push_back(*worker.submit(key(1+batch*4+j),16));
            check(!worker.submit(key(2000),1),"Stress budget overflow");
            worker.cancel(jobs[0]);
            for(unsigned j=1;j<4;++j){until([&]{return worker.state(jobs[j])==Async::State::Ready;});check(*worker.take(jobs[j])==decode(key(1+batch*4+j),16),"Stress revision corruption");}
            until([&]{return worker.stats().heldRecords==0;});check(worker.stats().heldBytes==0,"Stress accounting leak");
        }
        check(worker.stats().peakBytes<=64&&worker.stats().peakRecords<=4,"Stress peak overflow");worker.close();
    }
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"lifecycle_jobs\":1000,\"background_decode\":true,\"cancelled_results_discarded\":true}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
