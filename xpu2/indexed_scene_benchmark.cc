// Compare metadata-update cost; not a renderer or a cold-load benchmark.
#include "indexed_scene.h"
#include <chrono>
#include <iostream>
using namespace xpu2::indexed;
int main(){try{
    SceneIndex index;auto encode=[](Kind,Field,const Bytes& b){return b;};
    std::vector<Edit> edits;
    edits.push_back({"geometry",Kind::Geometry,{{Field::Positions,Bytes(1024*1024,42)}},{},{}});
    for(unsigned i=0;i<10000;++i)edits.push_back({"instance"+std::to_string(i),Kind::Instance,{{Field::Transform,Bytes(128)}},std::set<std::string>{"geometry"},{}});
    {auto initial=index.prepare(index.acquire(),edits,{},encode);if(!index.commit(initial))return 2;}
    auto geometry=index.acquire()->entities.at("geometry")->buffers.at(Field::Positions);
    std::vector<long long> micros;
    for(unsigned repeat=0;repeat<101;++repeat){
        Bytes matrix(128);matrix[0]=uint8_t(repeat+1);
        auto start=std::chrono::steady_clock::now();
        auto next=index.prepare(index.acquire(),{{"instance5000",Kind::Instance,{{Field::Transform,matrix}},{},{}}},{},encode);
        if(!index.commit(next))return 3;
        auto elapsed=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
        if(next.view()->changes.preparedBuffers!=1||next.view()->entities.at("geometry")->buffers.at(Field::Positions)!=geometry)return 4;
        if(repeat)micros.push_back(elapsed); // One warmup, then 100 measured edits.
    }
    std::sort(micros.begin(),micros.end());
    std::cout<<"{\"passed\":true,\"entities\":10001,\"updates\":100,\"median_ns\":"<<micros[50]<<",\"p95_ns\":"<<micros[95]<<",\"prepared_bytes_per_edit\":128,\"geometry_reused\":true}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
