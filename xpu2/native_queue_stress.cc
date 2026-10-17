// Standalone stress harness for the actual diagnostic queue, not a model of it.
#include "native_lambert_queue.cc"
#include <array>
#include <fstream>
#include <iostream>

struct Packet {
    std::array<float,192> input{};
    std::array<float,64> output{}, expected{};
};
static void require(bool condition,const char* message) {
    if(!condition)throw std::runtime_error(message);
}
static Packet packet(const std::vector<unsigned char>& data,size_t first) {
    Packet p;
    for(size_t lane=0;lane<8;++lane) {
        const auto* src=data.data()+4+(first+lane)*164;
        std::memcpy(p.input.data()+lane*24,src,96);
        std::memcpy(p.output.data()+lane*8,src+96,28);
        uint32_t valid;std::memcpy(&valid,src+124,4);
        p.output[lane*8+7]=float(valid);
    }
    p.expected=p.output;
    for(int i=0;i<8;++i)for(int c=3;c<6;++c)p.expected[i*8+c]*=0.5f;
    return p;
}
template<class Predicate> static void waitFor(Queue& q,Predicate predicate) {
    const auto until=std::chrono::steady_clock::now()+std::chrono::seconds(5);
    for(;;) {
        {std::lock_guard<std::mutex> lock(q.mutex);if(predicate())return;}
        require(std::chrono::steady_clock::now()<until,"Queue stage did not arrive within five seconds");
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }
}
int main(int argc,char** argv) {
    try {
        require(argc==3,"case capture required");
        std::ifstream f(argv[2],std::ios::binary);
        std::vector<unsigned char> data((std::istreambuf_iterator<char>(f)),{});
        require(data.size()>=4+66*8*164 && !std::memcmp(data.data(),"XNI1",4),"Missing reference packets");
        if(!std::strcmp(argv[1],"lifecycle") || !std::strcmp(argv[1],"lifecycle_missing_ptx")) {
            const bool missing=!std::strcmp(argv[1],"lifecycle_missing_ptx");
            const std::string queuePath=std::getenv("XPU2_QUEUE_LOG");
            const std::string logPath=std::getenv("XPU2_NATIVE_LAMBERT_LOG");
            const std::string recordPath=std::getenv("XPU2_NATIVE_LAMBERT_RECORDS");
            for(int cycle=0;cycle<4;++cycle) {
                const auto suffix="."+std::to_string(cycle);
                require(!_putenv_s("XPU2_QUEUE_LOG",(queuePath+suffix).c_str()),"Set queue log failed");
                require(!_putenv_s("XPU2_NATIVE_LAMBERT_LOG",(logPath+suffix).c_str()),"Set shader log failed");
                require(!_putenv_s("XPU2_NATIVE_LAMBERT_RECORDS",(recordPath+suffix).c_str()),"Set shader capture failed");
                auto owner=std::make_unique<Queue>();auto p=packet(data,cycle*8);
                if(missing)p.expected=p.output;
                owner->run(p.input.data(),p.output.data(),8);
                require(!std::memcmp(p.output.data(),p.expected.data(),sizeof(p.output)),"Recreated queue changed output");
                require(owner->stop(std::chrono::milliseconds(5000)),"Lifecycle cleanup failed");
                require(!owner->worker.joinable() && owner->cleanupOk && !owner->device.cleanupErrors && !owner->device.context && !owner->device.lib && !owner->device.module && !owner->device.beginEvent && !owner->device.endEvent,"Lifecycle resources still owned");
                for(auto buffer:owner->device.buffers)require(!buffer,"GPU buffer still owned");
                require(owner->stop(std::chrono::milliseconds(0)),"Repeated joined stop failed");
                require(owner->device.errors==(missing ? 1u : 0u),"Unexpected initialization error count");
                // Destroy only after the synchronous caller returned and worker joined.
                owner.reset();
            }
            std::cout<<"{\"case\":\""<<argv[1]<<"\",\"cycles\":4,\"worker_joins\":4,\"cleanup_errors\":0,\"passed\":true}\n";return 0;
        }
        auto* q=new Queue; // Explicitly stopped and deleted by this standalone owner.
        std::unique_lock<std::mutex> hold(q->device.mutex);
        if(!std::strcmp(argv[1],"async") || !std::strcmp(argv[1],"async_cancel") || !std::strcmp(argv[1],"async_missing_ptx")) {
            const bool missing=!std::strcmp(argv[1],"async_missing_ptx");
            const bool cancellation=!std::strcmp(argv[1],"async_cancel");
            std::array<Packet,66> packets;
            std::array<Queue::Ticket,66> tickets;
            for(size_t i=0;i<packets.size();++i){packets[i]=packet(data,i*8);if(missing)packets[i].expected=packets[i].output;}
            tickets[0]=q->submit(packets[0].input.data(),packets[0].output.data(),8,17);
            require(bool(tickets[0]),"First async request declined");
            waitFor(*q,[&]{return q->pending.empty();});
            for(size_t i=1;i<64;++i){tickets[i]=q->submit(packets[i].input.data(),packets[i].output.data(),8,17);require(bool(tickets[i]),"Async credit rejected too soon");}
            std::array<float,64> destination;destination.fill(9876.f);
            require(q->tryCollect(tickets[0],17,destination.data())==Collect::Pending,"Held GPU request did not remain pending");
            require(q->tryCollect(std::make_shared<Request>(),17,destination.data())==Collect::WrongOwner,"Foreign owner accepted");
            if(cancellation) {
                require(q->cancel(tickets[0]),"In-flight cancel failed");
                require(q->cancel(tickets[1]),"Pending cancel failed");
                require(!q->cancel(tickets[1]),"Cancellation was counted twice");
                require(q->tryCollect(tickets[2],18,destination.data())==Collect::Stale,"Stale scene revision accepted");
                for(size_t i=64;i<66;++i){tickets[i]=q->submit(packets[i].input.data(),packets[i].output.data(),8,17);require(bool(tickets[i]),"Pruned credits were not reusable");}
            }
            require(!q->submit(packets[0].input.data(),packets[0].output.data(),8,17),"Async credit limit not enforced");
            for(size_t i=0;i<(cancellation?66u:64u);++i){packets[i].input.fill(-1234.f);packets[i].output.fill(5678.f);}
            require(std::all_of(destination.begin(),destination.end(),[](float v){return v==9876.f;}),"Unready/rejected collection wrote output");
            // All submissions returned with the GPU worker still held by this thread.
            hold.unlock();
            waitFor(*q,[&]{for(size_t i=cancellation?3:0;i<(cancellation?66u:64u);++i)if(!tickets[i]->done)return false;return true;});
            if(!cancellation)require(!q->submit(packets[0].input.data(),packets[0].output.data(),8,17),"Uncollected ready results did not retain credits");
            unsigned collected=0;
            for(int i=cancellation?65:63;i>=(cancellation?3:0);--i) {
                require(q->tryCollect(tickets[i],17,destination.data())==Collect::Ready,"Ready async result not delivered");
                require(!std::memcmp(destination.data(),packets[i].expected.data(),sizeof(destination)),"Async ownership/order corrupted output");
                destination.fill(9876.f);
                require(q->tryCollect(tickets[i],17,destination.data())==Collect::Duplicate,"Duplicate result published");
                require(std::all_of(destination.begin(),destination.end(),[](float v){return v==9876.f;}),"Duplicate collection wrote output");++collected;
            }
            if(cancellation)for(int i=0;i<3;++i)require(q->tryCollect(tickets[i],17,destination.data())==Collect::Cancelled,"Cancelled async result published");
            require(q->stop(std::chrono::milliseconds(5000)),"Async queue did not drain");
            require(!q->submit(packets[0].input.data(),packets[0].output.data(),8,17),"Closed async queue admitted work");
            {std::lock_guard<std::mutex> lock(q->mutex);
             require(q->retainedAsync==0 && q->delivered==collected && q->explicitCancelled==(cancellation?3u:0u),"Async terminal accounting mismatch");
             require(q->pruned==(cancellation?2u:0u) && q->late==(cancellation?1u:0u),"Async cancellation accounting mismatch");q->snapshot();}
            std::cout<<"{\"case\":\""<<argv[1]<<"\",\"submissions_while_gpu_held\":"<<(cancellation?66:64)<<",\"reverse_order_collections\":"<<collected<<",\"pending_and_duplicate_writes\":0,\"retained_credits\":0,\"passed\":true}\n";
        } else if(!std::strcmp(argv[1],"coalesce_timeout")) {
            // Test-only direct field override exceeds the production 1000-us clamp.
            // Keep the real ten-second caller deadline and force its batch to empty.
            {std::lock_guard<std::mutex> lock(q->mutex);q->coalesceUs=11000000;}
            auto p=packet(data,0);auto native=p.output;
            q->run(p.input.data(),p.output.data(),8);
            require(!std::memcmp(p.output.data(),native.data(),sizeof(native)),"Coalescing timeout changed native result");
            hold.unlock();
            require(q->stop(std::chrono::milliseconds(5000)),"Empty coalesced batch did not stop");
            q->run(p.input.data(),p.output.data(),8);
            require(p.output==native,"Post-stop fallback changed native result");
            std::lock_guard<std::mutex> lock(q->mutex);
            require(q->emptyBatches==1 && q->merged==0 && !q->device.attempted && q->pruned==1 && q->timeouts==1 && q->closed==1 && q->workerExited,"Empty-batch path was not exercised");
            q->snapshot();
            std::cout<<"{\"case\":\"coalesce_timeout\",\"test_coalesce_us\":11000000,\"empty_batches_observed\":1,\"gpu_initialized\":false,\"worker_exited\":true,\"passed\":true}\n";
        } else if(!std::strcmp(argv[1],"shutdown")) {
            std::array<Packet,33> packets;
            for(size_t i=0;i<packets.size();++i)packets[i]=packet(data,i*8);
            std::vector<std::thread> producers;
            producers.emplace_back([&]{q->run(packets[0].input.data(),packets[0].output.data(),8);});
            waitFor(*q,[&]{return q->submitted==1 && q->pending.empty();});
            for(size_t i=1;i<packets.size();++i)producers.emplace_back([&,i]{q->run(packets[i].input.data(),packets[i].output.data(),8);});
            waitFor(*q,[&]{return q->submitted==33 && q->pending.size()==32;});
            const auto began=std::chrono::steady_clock::now();
            require(!q->stop(std::chrono::milliseconds(20)),"Blocked worker falsely reported stopped");
            auto waited=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count();
            require(waited<2000,"Stop deadline did not bound caller wait");
            auto declined=packet(data,33*8);auto native=declined.output;
            q->run(declined.input.data(),declined.output.data(),8);
            require(declined.output==native,"Closing queue did not retain native answer");
            hold.unlock();
            for(auto& t:producers)t.join();
            require(q->stop(std::chrono::milliseconds(5000)),"Worker failed to drain and stop");
            require(q->stop(std::chrono::milliseconds(0)),"Repeated stop was not idempotent");
            for(const auto& p:packets)require(!std::memcmp(p.output.data(),p.expected.data(),sizeof(p.output)),"Shutdown lost an accepted result");
            q->run(declined.input.data(),declined.output.data(),8);
            require(declined.output==native,"Stopped queue did not retain native answer");
            std::lock_guard<std::mutex> lock(q->mutex);
            require(q->workerExited && q->pending.empty() && q->submitted==33 && q->delivered==33 && q->closed==2 && !q->timeouts && !q->late && !q->failed,"Incomplete shutdown accounting");
            q->snapshot();
            std::cout<<"{\"case\":\"shutdown\",\"bounded_wait_ms\":"<<waited<<",\"accepted_results_delivered\":33,\"closed_fallbacks\":2,\"worker_exited\":true,\"idempotent_stop\":true,\"passed\":true}\n";
        } else if(!std::strcmp(argv[1],"capacity")) {
            std::array<Packet,65> packets;
            for(size_t i=0;i<packets.size();++i)packets[i]=packet(data,i*8);
            std::vector<std::thread> producers;
            producers.emplace_back([&]{q->run(packets[0].input.data(),packets[0].output.data(),8);});
            waitFor(*q,[&]{return q->submitted==1 && q->pending.empty();});
            for(size_t i=1;i<packets.size();++i)producers.emplace_back([&,i]{q->run(packets[i].input.data(),packets[i].output.data(),8);});
            waitFor(*q,[&]{return q->submitted==65 && q->pending.size()==64;});
            for(int i=0;i<8;++i) {
                auto p=packet(data,65*8);auto native=p.output;
                q->run(p.input.data(),p.output.data(),8);
                require(p.output==native,"Queue-full fallback modified native answer");
            }
            hold.unlock();
            for(auto& t:producers)t.join();
            for(const auto& p:packets)require(p.output==p.expected,"Foreign, missing or incorrect delivered output");
            std::lock_guard<std::mutex> lock(q->mutex);
            require(q->next==73 && q->submitted==65 && q->delivered==65 && q->full==8,"Request accounting failure");
            require(q->maxBatch==512 && q->maxQueue==64 && q->merged==2,"Full batch not exercised");
            require(!q->timeouts && !q->late && !q->failed,"Unexpected queue error");q->snapshot();
            std::cout<<"{\"case\":\"capacity\",\"owned_results_checked\":65,\"fallbacks_checked\":8,\"max_batch_samples\":512,\"passed\":true}\n";
        } else if(!std::strcmp(argv[1],"pending_timeout")) {
            // One held in-flight request + 63 pending requests time out together.
            // Pending cancellations must free queue slots before the worker resumes.
            std::array<Packet,64> packets;
            std::array<std::array<float,64>,64> native;
            for(size_t i=0;i<packets.size();++i){packets[i]=packet(data,i*8);native[i]=packets[i].output;}
            std::vector<std::thread> producers;
            const auto began=std::chrono::steady_clock::now();
            producers.emplace_back([&]{q->run(packets[0].input.data(),packets[0].output.data(),8);});
            waitFor(*q,[&]{return q->submitted==1 && q->pending.empty();});
            for(size_t i=1;i<packets.size();++i)producers.emplace_back([&,i]{q->run(packets[i].input.data(),packets[i].output.data(),8);});
            waitFor(*q,[&]{return q->submitted==64 && q->pending.size()==63;});
            for(auto& t:producers)t.join();
            const auto waited=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count();
            for(size_t i=0;i<packets.size();++i) {
                require(!std::memcmp(packets[i].output.data(),native[i].data(),sizeof(native[i])),"Timed-out output changed");
                packets[i].input.fill(-1234.f-float(i));packets[i].output.fill(5678.f+float(i));
            }
            auto recovery=packet(data,64*8);
            std::thread fresh([&]{q->run(recovery.input.data(),recovery.output.data(),8);});
            waitFor(*q,[&]{return q->submitted==65 && q->pending.size()==1 && q->timeouts==64 && q->pruned==63;});
            hold.unlock();fresh.join();
            waitFor(*q,[&]{return q->late==1 && q->pruned==63;});
            for(size_t i=0;i<packets.size();++i) {
                for(auto v:packets[i].input)require(v==-1234.f-float(i),"Cancelled input buffer overwritten");
                for(auto v:packets[i].output)require(v==5678.f+float(i),"Late output corrupted reused buffer");
            }
            require(!std::memcmp(recovery.output.data(),recovery.expected.data(),sizeof(recovery.output)),"Fresh request corrupted by cancelled batch neighbors");
            std::lock_guard<std::mutex> lock(q->mutex);
            require(q->next==65 && q->submitted==65 && q->delivered==1 && q->timeouts==64 && q->late==1 && q->pruned==63 && !q->failed && !q->full,"Pending-timeout accounting failure");
            require(q->maxBatch==8 && q->maxQueue==63 && q->merged==2,"Cancelled work reached GPU batch");q->snapshot();
            std::cout<<"{\"case\":\"pending_timeout\",\"waited_ms\":"<<waited<<",\"pending_timeouts\":63,\"inflight_timeouts\":1,\"caller_buffers_preserved\":64,\"pending_cancelled_before_dispatch\":63,\"fresh_request_after_pruning\":true,\"passed\":true}\n";
        } else {
            require(!std::strcmp(argv[1],"timeout"),"Unknown case");
            auto p=packet(data,0);auto native=p.output;
            auto began=std::chrono::steady_clock::now();
            std::thread producer([&]{q->run(p.input.data(),p.output.data(),8);});
            waitFor(*q,[&]{return q->submitted==1 && q->pending.empty();});
            producer.join();
            const auto waited=std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-began).count();
            require(p.output==native,"Timed-out caller did not retain native answer");
            p.input.fill(-1234.f);p.output.fill(5678.f); // Caller reuses both buffers before GPU returns.
            hold.unlock();
            waitFor(*q,[&]{return q->late==1;});
            require(std::all_of(p.output.begin(),p.output.end(),[](float v){return v==5678.f;}),"Late publication overwrote caller buffer");
            require(std::all_of(p.input.begin(),p.input.end(),[](float v){return v==-1234.f;}),"Worker overwrote caller input");
            auto recovery=packet(data,8);q->run(recovery.input.data(),recovery.output.data(),8);
            require(recovery.output==recovery.expected,"Queue failed to recover after timeout");
            std::lock_guard<std::mutex> lock(q->mutex);
            require(q->submitted==2 && q->delivered==1 && q->timeouts==1 && q->late==1 && !q->failed,"Timeout accounting failure");q->snapshot();
            std::cout<<"{\"case\":\"timeout\",\"waited_ms\":"<<waited<<",\"caller_buffers_preserved\":true,\"recovery_delivered\":true,\"passed\":true}\n";
        }
        require(q->stop(std::chrono::milliseconds(5000)),"Idle worker failed to stop");
        require(!q->worker.joinable() && q->cleanupOk && !q->device.cleanupErrors && !q->device.context && !q->device.lib,"Worker resources not released");
        delete q;
        std::cout.flush();return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
