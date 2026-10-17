// Original C++/ISPC Lambert sample oracles. No reimplementation of either formula.
#include <moonray/rendering/shading/bsdf/BsdfLambert.h>
#include <moonray/rendering/pbr/sampler/IntegratorSample.h>
#include "lambert_sample_ispc.h"
#include <array>
#include <cmath>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>
using namespace moonray::shading;using namespace scene_rdl2::math;
struct Row{std::vector<unsigned> key,input,cpp,vector;};
static unsigned bits(float f){unsigned u;std::memcpy(&u,&f,4);return u;}
static float value(unsigned u){float f;std::memcpy(&f,&u,4);return f;}
static void vec(std::vector<unsigned>& a,const Vec3f& v){for(auto f:{v.x,v.y,v.z})a.push_back(bits(f));}
static void col(std::vector<unsigned>& a,const Color& v){for(auto f:{v.r,v.g,v.b})a.push_back(bits(f));}
static void print(const char* n,const std::vector<unsigned>& a){std::printf(",\"%s\":[",n);for(size_t i=0;i<a.size();++i)std::printf("%s%u",i?",":"",a[i]);std::printf("]");}
int main(int argc,char** argv){
    unsigned workers=argc>=2?unsigned(std::atoi(argv[1])):1;if(workers<1||workers>16)return 2;
    bool stress=argc==3 && std::strcmp(argv[2],"stress")==0;if(argc>3 || (argc==3 && !stress))return 2;
    const Vec3f normals[]={Vec3f(0,0,1),Vec3f(0,1,0),Vec3f(1,0,0),normalize(Vec3f(1,2,3)),Vec3f(0,0,-1),
        Vec3f(0,-1,0),Vec3f(-1,0,0),normalize(Vec3f(-1,-2,-3)),normalize(Vec3f(1e-4f,0,-1)),
        normalize(Vec3f(.31f,-.72f,.62f)),normalize(Vec3f(-.91f,.13f,-.44f))};
    const Vec3f eyes[]={Vec3f(0,0,1),normalize(Vec3f(2,-1,3))};
    const Color colors[]={Color(0),Color(.7f,.03f,.4f),Color(8.f,.125f,1.f)};
    const Color scales[]={Color(1),Color(2.f,.25f,.5f)};
    std::vector<std::array<float,2>> random{{0,0},{1,0},{.5f,0},{.5f,.25f},{.5f,.5f},{.5f,.75f},{1e-8f,.99999994f},{.99999994f,1},{0,1},{.5f,.1234567f}};
    moonray::pbr::SequenceID sid(0u,(77u<<16)|96u,0u,0u,0u,19u);
    moonray::pbr::IntegratorSample<2> sampler(sid);
    for(unsigned i=0;i<6;++i){std::array<float,2> v;sampler.getSample(v.data(),0);random.push_back(v);}
    if(stress){
        for(unsigned i=0;i<48;++i){std::array<float,2> v;sampler.getSample(v.data(),0);random.push_back(v);}
        unsigned q=16;
        for(float boundary:{.25f,.5f,.75f})for(float toward:{0.f,1.f})random[q++]={.5f,std::nextafter(boundary,toward)};
        random[q++]={std::nextafter(0.f,1.f),.1234567f};
        random[q++]={std::nextafter(1.f,0.f),.1234567f};
        random[q++]={.5f,std::nextafter(0.f,1.f)};
        random[q++]={.5f,std::nextafter(1.f,0.f)};
        random[q++]={std::nextafter(.5f,0.f),.25f};
        random[q++]={std::nextafter(.5f,1.f),.75f};
    }
    unsigned normalCount=stress?11:5;
    std::vector<Row> rows;
    for(unsigned r=0;r<2;++r)for(unsigned n=0;n<normalCount;++n)for(unsigned g=0;g<2;++g)for(unsigned o=0;o<2;++o)
    for(unsigned a=0;a<3;++a)for(unsigned s=0;s<2;++s)for(unsigned c=0;c<2;++c)for(unsigned q=0;q<random.size();++q){
        Row row;row.key={r,n,g,o,a,s,c,q};row.input={0x32535058u,1};
        vec(row.input,normals[n]);vec(row.input,g?Vec3f(0,0,1):normals[n]);vec(row.input,eyes[o]);
        row.input.insert(row.input.end(),{bits(random[q][0]),bits(random[q][1]),0});
        col(row.input,colors[a]);col(row.input,scales[s]);row.input.insert(row.input.end(),{r,c,0,0});rows.push_back(std::move(row));
    }
    std::atomic<size_t> next{0};std::vector<std::thread> threads;
    for(unsigned w=0;w<workers;++w)threads.emplace_back([&]{for(size_t i;(i=next.fetch_add(1))<rows.size();){
        auto& row=rows[i];auto k=row.key;const auto N=normals[k[1]];
        LambertBsdfLobe lobe(N,colors[k[4]],k[0]!=0);lobe.setScale(scales[k[5]]);
        BsdfSlice slice(k[2]?Vec3f(0,0,1):N,eyes[k[3]],k[6]!=0,true,ispc::SHADOW_TERMINATOR_FIX_OFF);
        Vec3f wi;float pdf;auto v=lobe.sample(slice,random[k[7]][0],random[k[7]][1],wi,pdf);
        vec(row.cpp,wi);col(row.cpp,v);row.cpp.push_back(bits(pdf));row.cpp.push_back(slice.isSampleGeometricallyInvalid(lobe,wi)?1:0);
    }});
    for(auto& t:threads)t.join();
    // Reflection is uniform per original ISPC constructor. Each half has 3840
    // records (33792 in stress mode), divisible by eight, with varying samples.
    for(unsigned r=0;r<2;++r){
        size_t count=rows.size()/2,base=r*count;std::vector<float> input(count*24),output(count*8);
        for(size_t i=0;i<count;++i)for(unsigned j=0;j<24;++j)
            input[i*24+j]=j>=20?float(rows[base+i].input[j]):value(rows[base+i].input[j]);
        ispc::xpu2_lambert_sample(input.data(),int(count),int(r),output.data());
        for(size_t i=0;i<count;++i){for(unsigned j=0;j<7;++j)rows[base+i].vector.push_back(bits(output[i*8+j]));rows[base+i].vector.push_back(output[i*8+7]!=0?1:0);}
    }
    std::printf("{\"schema\":1,\"kind\":\"%s\",\"simd_width\":8,\"cases\":%zu}\n",stress?"lambert_sample_stress":"lambert_sample",rows.size());
    for(size_t i=0;i<rows.size();++i){auto& r=rows[i];std::printf("{\"id\":%zu",i);print("key",r.key);print("input",r.input);print("cpp",r.cpp);print("vector",r.vector);std::printf("}\n");}
}
