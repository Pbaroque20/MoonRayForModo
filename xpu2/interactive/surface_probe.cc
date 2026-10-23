// Component oracle calls the actual MoonRay filter and BSDF implementation.
#include "surface_core.h"
#include "sample_tree.h"
#include <moonray/rendering/pbr/sampler/PixelFilter.h>
#include <moonray/rendering/shading/bsdf/BsdfLambert.h>
#include <scene_rdl2/common/math/Mat4.h>
#include <cstdio>
#include <memory>
#include <thread>
#include <atomic>
using namespace xpu2::interactive;
static double err(float a,float b){return std::abs(double(a)-b);}
int main(){
    double filterError=0,bsdfError=0,cameraError=0;unsigned fc=0,bc=0,cc=0,checks=0;
    auto require=[&](bool ok){++checks;if(!ok)throw std::runtime_error("check "+std::to_string(checks));};
    for(unsigned kind=0;kind<3;++kind)for(float width:{.25f,1.f,3.f,4.f}){
        std::unique_ptr<moonray::pbr::PixelFilter> ref;
        if(kind==0)ref.reset(new moonray::pbr::BoxPixelFilter(width));
        if(kind==1)ref.reset(new moonray::pbr::CubicBSplinePixelFilter(width));
        if(kind==2)ref.reset(new moonray::pbr::QuadraticBSplinePixelFilter(width));
        std::vector<float> a;for(unsigned i=0;i<=65536;++i)a.push_back(float(i)/65536);
        for(float b:{1.f/24,1.f/6,.5f,5.f/6,23.f/24})for(float to:{0.f,1.f})a.push_back(std::nextafter(b,to));
        auto b=a;ref->apply(unsigned(b.size()),b.data());
        for(unsigned i=0;i<a.size();++i){float value=-99;require(surface::filter(surface::Filter(kind),width,a[i],value));filterError=std::max(filterError,err(value,b[i]));++fc;}
    }
    namespace math=scene_rdl2::math;using math::Vec3f;using math::Color;
    for(Vec3f n:{Vec3f(0,0,1),Vec3f(0,0,-1),math::normalize(Vec3f(1,2,3)),math::normalize(Vec3f(-.1f,.7f,-.3f))}){
        moonray::shading::LambertBsdfLobe ref(n,Color(.7f,.03f,.4f),true);
        moonray::shading::BsdfSlice slice(n,n,true,true,ispc::SHADOW_TERMINATOR_FIX_OFF);
        for(unsigned i=0;i<65536;++i){sample::Identity id{19,i,23,0};float u=sample::unit(sample::word(id,0)),v=sample::unit(sample::word(id,1));
            Vec3f wi;float pdf;auto color=ref.sample(slice,u,v,wi,pdf);surface::Sample candidate;
            require(surface::lambert({{.7f,.03f,.4f}},{n.x,n.y,n.z},u,v,candidate));
            float a[]={wi.x,wi.y,wi.z,color.r,color.g,color.b,pdf};float b[]={candidate.wi.x,candidate.wi.y,candidate.wi.z,candidate.f.x,candidate.f.y,candidate.f.z,candidate.pdf};
            for(int j=0;j<7;++j)bsdfError=std::max(bsdfError,err(a[j],b[j]));++bc;
        }
    }
    // Independent scene_rdl2 projective transform vs shared matrix operation.
    math::Mat4f raster(math::one),render(math::one);raster[0][0]=.01125f;raster[1][1]=.01125f;raster[3][0]=-.36f;raster[3][1]=-.27f;render[3][2]=4;
    surface::Camera cam{};for(int i=0;i<4;++i)for(int j=0;j<4;++j){cam.rasterToCamera.m[i][j]=raster[i][j];cam.cameraToRender.m[i][j]=render[i][j];}cam.nearClip=.001f;cam.farClip=1000;
    for(int i=0;i<64*48;++i){float x=(i%64)+.31f,y=(i/64)+.73f;surface::Ray ray;require(surface::cameraRay(cam,x,y,ray));
        Vec3f d=math::normalize(math::transformH(raster,Vec3f(x,y,-1)));
        cameraError=std::max({cameraError,err(d.x,ray.direction.x),err(d.y,ray.direction.y),err(d.z,ray.direction.z)});++cc;}
    float sentinel=42;require(!surface::filter(surface::Filter(99),1,.5f,sentinel)&&sentinel==42);
    require(!surface::filter(surface::Filter::Box,-1,.5f,sentinel));
    require(surface::frameSeed(0,0,true)==0 && surface::frameSeed(999,2,true)==0);
    require(surface::frameSeed(0,0,false)==3034297317u); // uint32 arithmetic known answer, independently computed by Python harness
    film::Tree tree({1,2,3,4},1,1);film::Handle root,other;sample::Identity id,id2;
    require(tree.begin(0,5,root,id)==film::Status::Ok);require(tree.begin(0,5,other,id2)==film::Status::Capacity);
    path::Record record{};record.epoch=root.epoch;record.id=id;path::Stage stage(record);
    require(stage.emit({0,{.1,.2,.3,1}}));require(stage.spawn(0,{},0));require(stage.spawn(1,{},0));
    path::Effects effects;require(stage.commit(record,effects,root.epoch,true));std::array<film::Handle,15> children;
    require(tree.finish(root,effects,children)==film::Status::Ok);require(tree.snapshot()[0].count==0);
    auto a=children[0],b=children[1];require(tree.finish(root,effects,children)==film::Status::Replay);
    path::Effects invalid{};invalid.valueCount=1;invalid.values[0].rgba[0]=NAN;
    require(tree.finish(a,invalid,children)==film::Status::Invalid);require(tree.audit().active==1);
    path::Effects end{};end.valueCount=1;end.values[0]={0,{.5,.5,.5,0}};
    require(tree.finish(b,end,children)==film::Status::Ok);require(tree.snapshot()[0].count==0);
    require(tree.finish(a,end,children)==film::Status::Ok);auto image=tree.snapshot();require(image[0].count==1&&std::abs(image[0].sum[0]-1.1)<1e-12);
    require(tree.finish(a,end,children)==film::Status::Replay);require(tree.begin(0,5,other,id2)==film::Status::Ok&&id2.index==1);
    require(tree.finish(root,end,children)==film::Status::Replay);require(tree.invalidate({1,2,4,4}));require(tree.finish(other,end,children)==film::Status::Stale);
    require(tree.audit().invalidated==2&&tree.snapshot()[0].count==0);
    film::Tree concurrent({7,1,1,1},12,12);std::atomic<unsigned> failures{0};std::vector<std::thread> workers;
    for(unsigned w=0;w<12;++w)workers.emplace_back([&,w]{for(unsigned s=0;s<1000;++s){film::Handle h;sample::Identity key;std::array<film::Handle,15> out;
        if(concurrent.begin(w,5,h,key)!=film::Status::Ok||key.index!=s||concurrent.finish(h,end,out)!=film::Status::Ok)++failures;}});
    for(auto& worker:workers)worker.join();auto audit=concurrent.audit();require(!failures&&audit.started==12000&&audit.completed==12000&&audit.active==0);
    for(auto& pixel:concurrent.snapshot())require(pixel.count==1000&&pixel.sum[0]==500);
    // Capacity rejection is transactional even when a whole tree is live.
    film::Tree capped({8,1,1,1},1,1);film::Handle h;sample::Identity key;require(capped.begin(0,0,h,key)==film::Status::Ok);
    std::array<film::Handle,15> first,grand,unused;
    auto spawn=[&](sample::Identity parent,unsigned count){path::Effects e{};e.childCount=count;for(unsigned i=0;i<count;++i){e.children[i].id=parent;require(sample::child(parent.branch,i,e.children[i].id.branch));}return e;};
    auto fan=spawn(key,15);require(capped.finish(h,fan,first)==film::Status::Ok);
    for(unsigned i=0;i<3;++i){auto k=key;k.branch=i+1;auto e=spawn(k,15);require(capped.finish(first[i],e,grand)==film::Status::Ok);}
    // 61 nodes have been used. A 15-child expansion cannot fit in 64.
    auto branch=key;branch.branch=4;auto tooMany=spawn(branch,15);
    require(capped.finish(first[3],tooMany,unused)==film::Status::Capacity);
    require(capped.audit().active==1&&capped.snapshot()[0].count==0);
    require(capped.finish(first[3],end,unused)==film::Status::Ok);
    require(capped.invalidate({8,2,1,1})&&capped.audit().invalidated==1);
    // Two consumers racing to retire one path cannot count it twice.
    film::Tree race({9,1,1,1},1,1);require(race.begin(0,0,h,key)==film::Status::Ok);
    std::atomic<unsigned> accepted{0};workers.clear();
    for(unsigned i=0;i<12;++i)workers.emplace_back([&]{std::array<film::Handle,15> output;if(race.finish(h,end,output)==film::Status::Ok)++accepted;});
    for(auto& w:workers)w.join();require(accepted==1&&race.snapshot()[0].count==1);
    bool badBudget=false;try{film::Tree impossible({1,1,1,1},0,1);}catch(const std::invalid_argument&){badBudget=true;}require(badBudget);
    std::printf("{\"filter_cases\":%u,\"filter_error\":%.17g,\"lambert_cases\":%u,\"lambert_error\":%.17g,\"camera_cases\":%u,\"camera_error\":%.17g,\"checks\":%u,\"concurrent_samples\":12000}\n",fc,filterError,bc,bsdfError,cc,cameraError,checks);
}
