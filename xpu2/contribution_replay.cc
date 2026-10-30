// Replays an owned numeric native stage after the capture process has exited.
#include <array>
#include <atomic>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>
#include <cstdint>
extern "C" void xpu2ResumeContribution(float*,float*,int);
struct Record {std::array<uint32_t,8> ids;std::array<float,24> input;std::array<float,8> expected;};
static_assert(sizeof(Record)==160,"Unexpected capture layout");
static void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
int main(int argc,char** argv){try{
    require(argc==6,"capture, workers, order, mode, result required");
    unsigned workers=std::stoul(argv[2]);require(workers==1 || workers==4,"Invalid worker count");
    const bool reverse=std::string(argv[3])=="reverse",sentinel=std::string(argv[4])=="sentinel";
    std::ifstream f(argv[1],std::ios::binary);std::vector<char> raw((std::istreambuf_iterator<char>(f)),{});
    require(raw.size()>4 && (raw.size()-4)%160==0 && !std::memcmp(raw.data(),"XCR1",4),"Invalid contribution capture");
    size_t count=(raw.size()-4)/160;require(count<=4096,"Oversized capture");
    std::vector<Record> owned(count);std::memcpy(owned.data(),raw.data()+4,count*160);
    for(const auto& r:owned){
        require(r.ids[6]<8,"Invalid native SIMD lane");
        for(float v:r.input)require(std::isfinite(v),"Nonfinite input");
        for(float v:r.expected)require(std::isfinite(v),"Nonfinite native answer");
        require(r.input[0]>=1 && r.input[1]>=0 && r.input[7]>0 && r.expected[0]>0,"Invalid numeric stage");
        for(int k:{2,3,4})require(r.input[k]==0 || r.input[k]==1,"Invalid native flags");
        for(int k=17;k<24;++k)require(r.input[k]==0,"Unknown payload version");
        require(r.expected[7]==0,"Unknown output version");
    }
    // None of the original serialized storage survives into the worker stage.
    std::fill(raw.begin(),raw.end(),char(0xa5));raw.clear();raw.shrink_to_fit();
    const size_t jobs=count*64;std::vector<std::array<float,8>> results(jobs);
    std::vector<std::atomic<unsigned>> seen(jobs);for(auto& n:seen)n=0;
    std::atomic<size_t> next{0};std::atomic<bool> invalid{false};std::vector<std::thread> threads;
    for(unsigned w=0;w<workers;++w)threads.emplace_back([&]{
        for(;;){size_t position=next.fetch_add(1);if(position>=jobs)break;
            size_t index=reverse?jobs-1-position:position;const auto& r=owned[index%count];
            const unsigned lane=r.ids[6];std::array<float,192> in{};std::array<float,64> out;out.fill(-9876.f);
            std::copy(r.input.begin(),r.input.end(),in.begin()+lane*24);
            if(sentinel)for(int c=11;c<14;++c)in[lane*24+c]*=.5f;
            xpu2ResumeContribution(in.data(),out.data(),1<<lane);
            for(unsigned other=0;other<8;++other)if(other!=lane)for(unsigned c=0;c<8;++c)
                if(out[other*8+c]!=-9876.f)invalid=true;
            std::copy_n(out.begin()+lane*8,8,results[index].begin());
            for(float v:results[index])if(!std::isfinite(v))invalid=true;
            if(seen[index].fetch_add(1)!=0)invalid=true;
            std::fill(in.begin(),in.end(),-7654.f);
        }
    });
    for(auto& t:threads)t.join();require(!invalid,"Corrupt worker result or inactive lane");
    size_t changed=0;
    for(size_t n=0;n<jobs;++n){require(seen[n]==1,"Missing or duplicate CPU stage");
        if(std::memcmp(results[n].data(),owned[n%count].expected.data(),32))++changed;}
    require(sentinel?changed>0:changed==0,"Native contribution parity/sentinel failed");
    std::ofstream result(argv[5],std::ios::binary);result.write(reinterpret_cast<const char*>(results.data()),results.size()*32);
    result.close();require(bool(result),"Result write failed");
    std::cout<<"{\"passed\":true,\"records\":"<<count<<",\"jobs\":"<<jobs<<",\"workers\":"<<workers
        <<",\"reverse\":"<<(reverse?"true":"false")<<",\"sentinel\":"<<(sentinel?"true":"false")<<",\"changed\":"<<changed<<"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
