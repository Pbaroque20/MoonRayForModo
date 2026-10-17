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
        auto* q=new Queue; // Same process-owned lifecycle as the native diagnostic.
        std::unique_lock<std::mutex> hold(q->device.mutex);
        if(!std::strcmp(argv[1],"capacity")) {
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
            // A fresh request then shares the 512-sample batch with cancelled work.
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
            waitFor(*q,[&]{return q->submitted==65 && q->pending.size()==64 && q->timeouts==64;});
            hold.unlock();fresh.join();
            waitFor(*q,[&]{return q->late==64;});
            for(size_t i=0;i<packets.size();++i) {
                for(auto v:packets[i].input)require(v==-1234.f-float(i),"Cancelled input buffer overwritten");
                for(auto v:packets[i].output)require(v==5678.f+float(i),"Late output corrupted reused buffer");
            }
            require(!std::memcmp(recovery.output.data(),recovery.expected.data(),sizeof(recovery.output)),"Fresh request corrupted by cancelled batch neighbors");
            std::lock_guard<std::mutex> lock(q->mutex);
            require(q->next==65 && q->submitted==65 && q->delivered==1 && q->timeouts==64 && q->late==64 && !q->failed && !q->full,"Pending-timeout accounting failure");
            require(q->maxBatch==512 && q->maxQueue==64 && q->merged==2,"Mixed cancelled/live batch not exercised");q->snapshot();
            std::cout<<"{\"case\":\"pending_timeout\",\"waited_ms\":"<<waited<<",\"pending_timeouts\":63,\"inflight_timeouts\":1,\"caller_buffers_preserved\":64,\"fresh_request_in_cancelled_batch\":true,\"passed\":true}\n";
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
        std::cout.flush();return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
