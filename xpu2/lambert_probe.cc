// Native Lambert evaluation oracle. Original MoonRay code, not a copied formula.
#include <moonray/rendering/shading/bsdf/BsdfLambert.h>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>
using namespace moonray::shading;
using namespace scene_rdl2::math;
struct Row {std::vector<unsigned> key,input,output;};
static unsigned bits(float v){unsigned u;std::memcpy(&u,&v,4);return u;}
static void vec(std::vector<unsigned>& out,const Vec3f& v){out.push_back(bits(v.x));out.push_back(bits(v.y));out.push_back(bits(v.z));}
static void color(std::vector<unsigned>& out,const Color& c){out.push_back(bits(c.r));out.push_back(bits(c.g));out.push_back(bits(c.b));}
static void values(const char* name,const std::vector<unsigned>& v){std::printf(",\"%s\":[",name);for(size_t i=0;i<v.size();++i)std::printf("%s%u",i?",":"",v[i]);std::printf("]");}
int main(int argc,char** argv){
    unsigned workers=argc==2?unsigned(std::atoi(argv[1])):1;if(workers<1||workers>16)return 2;
    const Vec3f normals[]={Vec3f(0,0,1),Vec3f(0,1,0),Vec3f(1,0,0),normalize(Vec3f(1,2,3)),Vec3f(0,0,-1)};
    const Vec3f incoming[]={Vec3f(0,0,1),Vec3f(0,0,-1),Vec3f(1,0,0),normalize(Vec3f(1,0,0.000001f)),normalize(Vec3f(1,0,-0.000001f)),normalize(Vec3f(1,2,3)),normalize(Vec3f(-2,1,-3)),Vec3f(0,-1,0)};
    const Vec3f outgoing[]={Vec3f(0,0,1),Vec3f(0,0,-1),normalize(Vec3f(2,-1,3))};
    const Color colors[]={Color(0),Color(1),Color(.7f,.03f,.4f),Color(8.f,.125f,1.f)};
    const Color scales[]={Color(0),Color(1),Color(2.f,.25f,.5f)};
    std::vector<Row> rows;
    for(unsigned n=0;n<5;++n)for(unsigned g=0;g<2;++g)for(unsigned i=0;i<8;++i)
    for(unsigned o=0;o<3;++o)for(unsigned a=0;a<4;++a)for(unsigned s=0;s<3;++s)
    for(unsigned r=0;r<2;++r)for(unsigned c=0;c<2;++c){
        Row row;row.key={n,g,i,o,a,s,r,c};
        row.input={0x324c5058u,1}; // XPL2, version1 (evaluation packet, not sampler state).
        vec(row.input,normals[n]);vec(row.input,g?Vec3f(0,0,1):normals[n]);
        vec(row.input,outgoing[o]);vec(row.input,incoming[i]);color(row.input,colors[a]);color(row.input,scales[s]);
        row.input.insert(row.input.end(),{r,c,0,0}); // reflection, cosine, terminator off, no Fresnel
        rows.push_back(std::move(row));
    }
    std::atomic<size_t> next{0};std::vector<std::thread> threads;
    for(unsigned w=0;w<workers;++w)threads.emplace_back([&]{
        for(size_t j;(j=next.fetch_add(1))<rows.size();){
            auto& row=rows[j];auto k=row.key;
            const Vec3f N=normals[k[0]],Ng=k[1]?Vec3f(0,0,1):N;
            LambertBsdfLobe lobe(N,colors[k[4]],k[6]!=0);lobe.setScale(scales[k[5]]);
            BsdfSlice slice(Ng,outgoing[k[3]],k[7]!=0,true,ispc::SHADOW_TERMINATOR_FIX_OFF);
            float pdf;const auto result=lobe.eval(slice,incoming[k[2]],&pdf);
            color(row.output,result);row.output.push_back(bits(pdf));color(row.output,lobe.albedo(slice));
            row.output.push_back(slice.isSampleGeometricallyInvalid(lobe,incoming[k[2]])?1:0);
        }
    });
    for(auto& t:threads)t.join();
    std::printf("{\"schema\":1,\"kind\":\"lambert_eval\",\"cases\":%zu}\n",rows.size());
    for(size_t i=0;i<rows.size();++i){std::printf("{\"id\":%zu",i);values("key",rows[i].key);values("input",rows[i].input);values("output",rows[i].output);std::printf("}\n");}
}
