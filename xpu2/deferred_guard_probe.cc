// Guard tests with the same bridge and real GPU queue as the native adapter.
#include "deferred_bridge.cc"
#include <fstream>
#include <iostream>
static void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main(int argc,char** argv){
    try{
        require(argc==3,"case and correlated capture required");
        const std::string mode=argv[1];
        std::ifstream file(argv[2],std::ios::binary);
        std::vector<char> raw((std::istreambuf_iterator<char>(file)),{});
        require(raw.size()>=244 && !std::memcmp(raw.data(),"XCL1",4),"Missing native event");
        std::array<float,24> input;std::array<float,8> native;
        std::memcpy(input.data(),raw.data()+4+112,96);std::memcpy(native.data(),raw.data()+4+208,32);
        std::array<float,64> post{};std::copy(native.begin(),native.end(),post.begin());
        int lane=0;
        xpu2DeferredBegin();
        if(mode=="nested"){
            bool rejected=false;try{xpu2DeferredBegin();}catch(const std::runtime_error&){rejected=true;}
            require(rejected,"Nested native scope accepted");
        }
        xpu2DeferredLambert(input.data(),native.data(),&lane,1);
        require(bool(scope.ticket),"Missing ticket");
        if(mode=="multiple")xpu2DeferredLambert(input.data(),native.data(),&lane,1);
        xpu2DeferredSampleEnd();
        if(mode=="transformed")post[3]+=1.f;
        auto original=post;
        xpu2DeferredCollect(post.data(),mode=="mask" ? 0 : 1);
        require(!scope.open && !scope.ticket && activeCpu.load()==0,"Scope leaked");
        auto& q=deferredQueue();
        require(q.stop(std::chrono::milliseconds(5000)) && !q.worker.joinable(),"Queue cleanup failed");
        require(q.retainedAsync==0 && !q.device.cleanupErrors,"Resources retained");
        if(mode=="transformed" || mode=="mask"){
            require(metrics().guardFallback==1 && !metrics().collected && post==original,"Changed post-sampler data published");
        }else if(mode=="multiple"){
            require(metrics().multipleHooks==1 && !metrics().collected && post==original,"Nested lobe output published");
        }else if(mode=="nested" || mode=="positive"){
            for(int i=3;i<6;++i)original[i]*=.5f;
            require(metrics().collected==1 && post==original,"Deferred GPU result not consumed");
        }else throw std::runtime_error("Unknown case");
        std::cout<<"{\"case\":\""<<mode<<"\",\"passed\":true,\"cleanup\":true}\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
