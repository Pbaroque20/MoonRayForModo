// Calls the original native AVX8 sampler, EnvLight and contribution functions.
#include <array>
#include <fstream>
#include <vector>
#include <cstring>
#include <stdexcept>
#include <iostream>
extern "C" void xpu2_lambert_sample(float*,int,int,float*);
extern "C" void xpu2NativeEnv(float*,float*,float*);
extern "C" void xpu2ResumeContribution(float*,float*,int);
int main(int argc,char** argv){try{
    if(argc!=3)throw std::runtime_error("input/output required");
    std::ifstream f(argv[1],std::ios::binary);std::vector<char> data((std::istreambuf_iterator<char>(f)),{});
    if(data.empty() || data.size()%256 || data.size()>256*4096)throw std::runtime_error("Invalid input");
    std::ofstream out(argv[2],std::ios::binary);
    for(size_t pos=0;pos<data.size();pos+=256){
        std::array<float,192> samples{},contribution{};std::array<float,64> sampled{},light{},result{};
        std::array<float,32> rays{};std::array<float,16> params{};
        unsigned reflection;std::memcpy(&reflection,data.data()+pos+80,4);
        std::memcpy(params.data(),data.data()+pos+192,64);
        for(unsigned lane=0;lane<8;++lane){std::memcpy(samples.data()+lane*24,data.data()+pos,96);
            std::memcpy(contribution.data()+lane*24,data.data()+pos+96,96);
            for(unsigned k=20;k<24;++k){unsigned u;std::memcpy(&u,&samples[lane*24+k],4);samples[lane*24+k]=float(u);}}
        xpu2_lambert_sample(samples.data(),8,int(reflection),sampled.data());
        for(unsigned lane=0;lane<8;++lane){for(unsigned k=0;k<3;++k)rays[lane*4+k]=sampled[lane*8+k];rays[lane*4+3]=params[10];}
        xpu2NativeEnv(params.data(),rays.data(),light.data());
        for(unsigned lane=0;lane<8;++lane){auto* a=contribution.data()+lane*24;auto* l=light.data()+lane*8;auto* s=sampled.data()+lane*8;
            a[4]=l[0]==0?1.f:0.f;a[5]=l[1];a[6]=l[2];a[7]=s[6];
            for(unsigned c=0;c<3;++c){a[11+c]=s[3+c];a[14+c]=l[3+c];}}
        xpu2ResumeContribution(contribution.data(),result.data(),255);
        out.write(reinterpret_cast<const char*>(sampled.data()),32);
        out.write(reinterpret_cast<const char*>(result.data()),32);
        out.write(reinterpret_cast<const char*>(light.data()),32);
    }
    out.close();if(!out)throw std::runtime_error("Write failed");return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
