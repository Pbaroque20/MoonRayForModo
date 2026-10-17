// Isolated combined native sampler/AVX8 shading endpoint; not a renderer protocol.
#pragma once
#include "sampler_exchange.h"
#include "lambert_sample_ispc.h"
#include <cmath>
namespace xpu2 {
struct ShadingRecord {
    std::vector<uint8_t> state;
    uint32_t length;
    std::array<uint32_t,12> result{};
};
inline uint32_t shadeWord(const std::vector<uint8_t>& data,unsigned word) {
    uint32_t v=0;for(unsigned i=0;i<4;++i)v|=uint32_t(data[4*word+i])<<(8*i);return v;
}
inline void shadePut(std::vector<uint8_t>& data,unsigned word,uint32_t value) {
    for(unsigned i=0;i<4;++i)data[4*word+i]=uint8_t(value>>(8*i));
}
inline float shadeFloat(uint32_t word){float f;std::memcpy(&f,&word,4);return f;}
inline uint32_t shadeBits(float value){uint32_t u;std::memcpy(&u,&value,4);return u;}
inline unsigned shadeMaterial(const std::vector<uint8_t>& data) {
    // Same measured Lambert packet domain as the standalone CUDA sampler.
    if(shadeWord(data,0)!=0x32535058u || shadeWord(data,1)!=1 || shadeWord(data,13)!=0 ||
       shadeWord(data,20)>1 || shadeWord(data,21)>1)return 2;
    float v[18];for(unsigned j=0;j<18;++j){v[j]=shadeFloat(shadeWord(data,j+2));if(!std::isfinite(v[j]))return 2;}
    for(unsigned j=12;j<18;++j)if(v[j]<0)return 2;
    for(unsigned j=0;j<9;j+=3)if(std::fabs((v[j]*v[j]+v[j+1]*v[j+1])+v[j+2]*v[j+2]-1.f)>.0001f)return 2;
    if(v[9]<0 || v[9]>1 || v[10]<0 || v[10]>1)return 2;
    if(shadeWord(data,22) || shadeWord(data,23))return 1;
    for(unsigned j=12;j<15;++j)if(v[j]>8)return 1;
    for(unsigned j=15;j<18;++j)if(v[j]>2)return 1;
    return 0;
}
inline int shadingExchange(const char* input,const char* output,unsigned workers) {
    try {
        std::ifstream in(input,std::ios::binary);
        if(readWord(in)!=0x31424858u)throw std::runtime_error("Bad shading batch magic"); // XHB1
        auto count=readWord(in);if(!count || count>32768)throw std::runtime_error("Bad shading batch count");
        std::vector<ShadingRecord> records(count);
        for(auto& r:records){r.length=readWord(in);r.state.resize(208);r.result[0]=2;
            if(!in.read(reinterpret_cast<char*>(r.state.data()),208))throw std::runtime_error("Truncated shading state");}
        if(in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("Trailing shading data");
        std::atomic<size_t> next{0};std::vector<std::thread> threads;
        for(unsigned worker=0;worker<workers;++worker)threads.emplace_back([&]{
            for(size_t base;(base=next.fetch_add(8))<records.size();){
                std::array<std::vector<uint8_t>,8> pending;
                bool active[8]{};
                for(unsigned j=0;j<8 && base+j<records.size();++j){auto& r=records[base+j];
                    if(r.length!=208 || shadeWord(r.state,0)!=0x31485358u || shadeWord(r.state,1)!=1 || shadeWord(r.state,3)!=0)continue;
                    if(shadeWord(r.state,2)!=1){r.result[0]=1;continue;} // Explicit native AVX8 profile.
                    try {
                        std::vector<uint8_t> sampler(r.state.begin()+16,r.state.begin()+80);
                        auto s=decodeWindow(sampler);
                        if(s.sampler.dimensions!=2)continue;
                        if(s.sampler.total!=0xffffffffu || s.sampler.pseudo || (s.sampler.depth!=0 && s.sampler.depth!=2) ||
                           s.sampler.next<1000 || s.sampler.next>=1048){r.result[0]=1;continue;}
                        WindowCursor<2> cursor(s);auto draw=cursor.draw();auto returned=encodeWindow(cursor.snapshot());
                        std::vector<uint8_t> material(r.state.begin()+80,r.state.begin()+176);
                        // Validate incoming material before replacing random fields.
                        auto status=shadeMaterial(material);if(status){r.result[0]=status;continue;}
                        pending[j]=r.state;
                        std::copy(returned.begin(),returned.end(),pending[j].begin()+16);
                        shadePut(pending[j],31,shadeBits(draw[0]));shadePut(pending[j],32,shadeBits(draw[1]));
                        r.result[1]=s.sampler.sid().private_test();r.result[2]=shadeBits(draw[0]);r.result[3]=shadeBits(draw[1]);
                        active[j]=true;
                    }catch(const std::invalid_argument&){}catch(const std::out_of_range&){}
                }
                // Original constructor has a uniform reflection flag: pack each kind separately.
                for(unsigned reflection=0;reflection<2;++reflection){
                    std::vector<float> params;std::vector<unsigned> selected;
                    for(unsigned j=0;j<8 && base+j<records.size();++j)if(active[j] && shadeWord(pending[j],40)==reflection){
                        selected.push_back(j);for(unsigned k=0;k<24;++k){auto u=shadeWord(pending[j],20+k);params.push_back(k>=20?float(u):shadeFloat(u));}}
                    if(selected.empty())continue;
                    std::vector<float> values(selected.size()*8);
                    ispc::xpu2_lambert_sample(params.data(),int(selected.size()),int(reflection),values.data());
                    for(unsigned n=0;n<selected.size();++n){unsigned j=selected[n];auto& r=records[base+j];
                        for(unsigned k=0;k<8;++k){uint32_t value=k==7?(values[n*8+k]!=0?1u:0u):shadeBits(values[n*8+k]);
                            r.result[k+4]=value;shadePut(pending[j],44+k,value);}
                        // Feed the actual sampled direction into the next shading operation's eye vector.
                        for(unsigned k=0;k<3;++k)shadePut(pending[j],28+k,r.result[k+4]);
                        r.state=std::move(pending[j]);r.result[0]=0;active[j]=false;
                    }
                }
            }
        });
        for(auto& t:threads)t.join();
        std::ofstream out(output,std::ios::binary);writeWord(out,0x314f4858u);writeWord(out,count); // XHO1
        for(auto& r:records){out.write(reinterpret_cast<const char*>(r.state.data()),208);for(auto v:r.result)writeWord(out,v);}
        out.close();if(!out)throw std::runtime_error("Cannot write shading batch");return 0;
    }catch(const std::exception& e){std::fprintf(stderr,"%s\n",e.what());return 3;}
}
}
