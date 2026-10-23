// Real C++ immutable index; synthetic features/buffers, no native render claim.
#include "routing_index.h"
#include <atomic>
#include <iostream>
#include <type_traits>
static_assert(!std::is_copy_constructible_v<xpu2::interactive::Router>);
static_assert(!std::is_copy_assignable_v<xpu2::interactive::Router>);
using namespace xpu2::interactive;
using namespace xpu2::indexed;
static unsigned checks=0;
static void check(bool v){++checks;if(!v)throw std::runtime_error("Routing check failed");}
template<class F> static void rejects(F f){bool caught=false;try{f();}catch(const std::exception&){caught=true;}check(caught);}
static Edit edit(std::string id,Kind k,Bytes data,std::set<std::string> deps={}){
 return {id,k,{{Field::Parameters,data}},deps,{}};
}
static Bytes copy(Kind,Field,const Bytes& b){return b;}
int main(){
 try {
    SceneIndex index; Router router(index,{17,0,0,0});
    auto initial=index.prepare(index.acquire(),{
      edit("texture",Kind::Texture,{1}),
      edit("material",Kind::Material,{1},{"texture"}),
      edit("mesh",Kind::Geometry,{1},{"material"}),
      edit("camera",Kind::Camera,{1})},{},copy);
    auto unknown=router.prepare(initial,{17,1,0,0},0);
    check(unknown.view()->mode==Mode::Fallback);
    check(unknown.view()->totals[0]==4);
    check(!router.commit(unknown));
    check(!router.acknowledge(unknown,Backend::Gpu));
    check(router.acknowledge(unknown,Backend::Fallback));
    check(router.commit(unknown));
    auto old=router.acquire();
    auto noop=index.prepare(index.acquire(),{},{},copy);
    rejects([&]{router.prepare(noop,{17,1,0,1},1,[](const auto&,const auto&){
        return Decision{Support::Both,""};});});
    auto supported=[](const std::string&,const ix::View&){
        return Decision{Support::Both,"synthetic-test-evidence-only"};};
    auto native=router.prepare(noop,{17,1,0,1},1,supported);
    check(native.view()->classified==4);
    check(native.view()->mode==Mode::NativeMixed);
    check(router.acknowledge(native,Backend::Cpu));
    check(!router.commit(native));
    check(router.acquire()==old);
    check(router.acknowledge(native,Backend::Gpu));
    check(router.commit(native));
    check(old->mode==Mode::Fallback && old->scene->entities.size()==4);
    check(!router.commit(native));

    auto changed=index.prepare(index.acquire(),{edit("texture",Kind::Texture,{2})},{},copy);
    auto patch=router.prepare(changed,{17,2,0,1},1,supported);
    check(patch.view()->classified==3); // texture + material + mesh; camera cached
    check(patch.view()->scene->entities.at("camera")==router.acquire()->scene->entities.at("camera"));
    auto stale=router.prepare(changed,{17,2,0,1},1,supported);
    router.acknowledge(patch,Backend::Cpu);router.acknowledge(patch,Backend::Gpu);
    check(router.commit(patch));
    check(!router.acknowledge(stale,Backend::Cpu));
    check(!router.commit(stale));

    auto idle=index.prepare(index.acquire(),{},{},copy);
    auto camera=router.prepare(idle,{17,2,1,1},1,supported);
    check(camera.view()->classified==0);
    router.acknowledge(camera,Backend::Cpu);router.acknowledge(camera,Backend::Gpu);
    check(router.commit(camera));
    rejects([&]{router.prepare(idle,{17,2,1,1},1,supported);});
    rejects([&]{router.prepare(idle,{17,2,2,1},2,supported);});
    auto cpu=router.prepare(idle,{17,2,1,2},2,[](const auto&,const auto&){
        return Decision{Support::Cpu,"synthetic-test-evidence-only"};});
    check(cpu.view()->mode==Mode::NativeCpu);
    check(!router.acknowledge(cpu,Backend::Gpu));
    router.acknowledge(cpu,Backend::Cpu);check(router.commit(cpu));

    std::atomic<unsigned> reads{0},denied{0};
    auto frozen=router.acquire();
    std::vector<std::thread> workers;
    for(unsigned i=0;i<12;++i)workers.emplace_back([&]{
       for(unsigned j=0;j<1000;++j)if(frozen->totals[1]==4)++reads;
       try{router.acquire();}catch(const std::logic_error&){++denied;}
    });
    for(auto& t:workers)t.join();
    check(reads==12000 && denied==12);
    std::cout<<"passed "<<checks<<" routing checks; "<<reads
             <<" concurrent immutable reads; no rendered validation"<<std::endl;
    return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
