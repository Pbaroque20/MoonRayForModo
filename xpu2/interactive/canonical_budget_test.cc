#include "canonical_session.h"
#include <iostream>
using namespace xpu2::interactive;
using namespace xpu2::rdlindex;
static unsigned checks=0;
static void check(bool b,const char* s){++checks;if(!b)throw std::runtime_error(s);}
int main(int argc,char** argv){try{
    if(argc!=4)throw std::runtime_error("scene dso output");
    rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);
    fs::path out(argv[3]);CanonicalSession service(argv[2],{96,0,0,0},{},{2,size_t(1)<<30});
    auto first=service.prepare(source,out/"first",{96,1,0,0});
    check(service.acknowledge(first)&&service.publish(first),"Initial publish");source.commitAllChanges();
    auto usedFirst=service.retainedUsage();check(usedFirst.versions==1&&usedFirst.bytes>0,"Initial usage");
    auto change=[&]{auto* material=source.getSceneObject("/modo/material/1");rdl::SceneObject::UpdateGuard g(material);
        auto value=material->get<rdl::Rgb>("diffuseColor");value[0]+=.01f;material->set<rdl::Rgb>("diffuseColor",value);};
    change();auto second=service.prepare(source,out/"second",{96,2,0,0});
    check(service.acknowledge(second)&&service.publish(second),"Second publish");source.commitAllChanges();
    auto usedSecond=service.retainedUsage();
    check(usedSecond.versions==2&&usedSecond.bytes>usedFirst.bytes&&usedSecond.bytes<usedFirst.bytes*2,"Unchanged buffers double counted");
    change();bool refused=false;try{service.prepare(source,out/"refused",{96,3,0,0});}catch(const std::length_error&){refused=true;}
    check(refused&&!fs::exists(out/"refused")&&service.acquire()==second,"Version refusal changed native publication");
    // An external scene-index reader remains a lease even after its frame dies.
    auto reader=first->routing->scene;first.reset();refused=false;
    try{service.prepare(source,out/"reader-held",{96,3,0,0});}catch(const std::length_error&){refused=true;}
    check(refused,"External index reader was not counted");reader.reset();
    auto third=service.prepare(source,out/"retry",{96,3,0,0});
    check(service.acknowledge(third)&&service.publish(third),"Release did not restore capacity");
    second.reset();check(service.retainedUsage().versions==1,"Expired version not retired");
    CanonicalSession tiny(argv[2],{97,0,0,0},{},{2,1});refused=false;
    try{tiny.prepare(source,out/"too-large",{97,1,0,0});}catch(const std::length_error&){refused=true;}
    check(refused&&!tiny.acquire()&&!fs::exists(out/"too-large"),"Byte budget bypassed");
    std::cout<<"{\"status\":\"passed\",\"checks\":"<<checks<<",\"first_bytes\":"<<usedFirst.bytes
             <<",\"second_bytes\":"<<usedSecond.bytes<<",\"scope\":\"indexed buffers only; native replicas not metered\"}\n";
    return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
