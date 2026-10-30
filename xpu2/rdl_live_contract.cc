#include "rdl_live_bridge.h"
#include <iostream>
using namespace xpu2::rdllive;
static void check(bool ok,const char* why){if(!ok)throw std::runtime_error(why);}
int main(int argc,char** argv){try{
    if(argc!=3)throw std::invalid_argument("fixture and dso path required");
    rdl::SceneContext target;target.setProxyModeEnabled(true);target.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],target);target.commitAllChanges();
    auto* material=target.getSceneObject("/modo/material/1");
    auto attr=material->getSceneClass().getAttribute("diffuseColor");
    auto original=encodeAttribute(*material,*attr).bytes;
    bool refused=false;try{update(target,true,[](auto&){});}catch(const std::logic_error&){refused=true;}
    check(refused&&states().empty(),"Rendering mutation accepted");
    update(target,false,[](auto& source){auto* m=source.getSceneObject("/modo/material/1");rdl::SceneObject::UpdateGuard guard(m);m->set("diffuseColor",rdl::Rgb(.2f,.3f,.4f));});
    check(material->get<rdl::Rgb>("diffuseColor")==rdl::Rgb(.2f,.3f,.4f),"Material update not applied");
    check(material->isDirty(),"Native update flags lost before startFrame");
    auto snapshot=states().at(&target)->index.acquire();target.commitAllChanges();
    update(target,false,[](auto&){});
    check(states().at(&target)->index.acquire()==snapshot&&!material->isDirty(),"Noop dirtied target");
    auto good=encodeAttribute(*material,*attr).bytes;
    refused=false;try{update(target,false,[](auto& source){
        auto* m=source.getSceneObject("/modo/material/1");rdl::SceneObject::UpdateGuard guard(m);m->set("diffuseColor",rdl::Rgb(1.f,0.f,0.f));
        throw std::runtime_error("Injected reader failure after partial proxy edit");
    });}catch(const std::runtime_error&){refused=true;}
    check(refused&&encodeAttribute(*material,*attr).bytes==good,"Read failure modified native target");
    check(states().at(&target)->index.acquire()==snapshot,"Failure published candidate");
    refused=false;try{healthy(target);}catch(const std::runtime_error&){refused=true;}check(refused,"Invalid context could start frame");
    refused=false;try{update(target,false,[](auto&){});}catch(const std::runtime_error&){refused=true;}check(refused,"Invalid context accepted update");
    forget(&target);check(states().empty(),"Teardown retained index");
    // Controlled rebuild from a known-good target. Production uses a new context.
    update(target,false,[](auto&){});healthy(target);
    check(encodeAttribute(*material,*attr).bytes==good,"Rebuild changed material");
    forget(&target);
    check(good!=original,"Fixture edit was a no-op");
    std::cout<<"{\"passed\":true,\"active_render_rejected\":true,\"dirty_flags_preserved\":true,\"noop_shared\":true,\"partial_read_rejected\":true,\"invalid_start_rejected\":true,\"invalid_update_rejected\":true,\"teardown_released\":true,\"rebuild_exact\":true}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

