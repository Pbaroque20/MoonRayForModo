// Real native scenes and disk publication; no native XPU2 shading.
#include "canonical_session.h"
#include <json/json.h>
#include <iostream>
#include <thread>
using namespace xpu2::interactive;
using namespace xpu2::rdlindex;
static unsigned checks=0;
static void check(bool v,const char* what){++checks;if(!v)throw std::runtime_error(what);}
static void same(const rdl::SceneContext& source,const rdl::SceneContext& target){
    for(auto i=source.beginSceneObject();i!=source.endSceneObject();++i){
        auto* b=target.getSceneObject(i->second->getName());
        check(b!=nullptr,"Native object missing");
        for(auto a=i->second->getSceneClass().beginAttributes();a!=i->second->getSceneClass().endAttributes();++a)
            if(encodeAttribute(*i->second,**a).bytes!=encodeAttribute(*b,**a).bytes)
                throw std::runtime_error("Attribute changed: "+i->second->getName()+" / "+(*a)->getName());
            else ++checks;
    }
}
// Compare the exact acknowledged indexed attributes. Reading RDLB again is not
// a byte-stable oracle: MoonRay BinaryReader re-sorts native sets by pointer.
static void sameIndex(const ix::View& expected,const rdl::SceneContext& actual){
    size_t expectedObjects=0,actualObjects=0;
    for(const auto& pair:expected->entities){
        const auto& entity=*pair.second;
        if(entity.kind!=ix::Kind::Attribute){++expectedObjects;continue;}
        const auto& bytes=entity.buffers.begin()->second->source;
        Reader reader{bytes};Codec<uint32_t>::get(reader);
        auto object=Codec<std::string>::get(reader),name=Codec<std::string>::get(reader);
        auto* native=actual.getSceneObject(object);
        check(native!=nullptr,"Recovered object missing");
        check(encodeAttribute(*native,*native->getSceneClass().getAttribute(name)).bytes==bytes,
              "Recovered attribute differs from acknowledged index");
    }
    for(auto i=actual.beginSceneObject();i!=actual.endSceneObject();++i)++actualObjects;
    check(expectedObjects==actualObjects,"Recovery added or lost objects");
}
static void exportStage(const rdl::SceneContext& source,const CanonicalView& frame,
                        const fs::path& out,const char* name,Json::Value& report){
    rdl::BinaryWriter(source).toFile((out/(std::string(name)+"-source.rdlb")).string());
    fs::copy_file(frame->scene,out/(std::string(name)+"-indexed.rdlb"));
    Json::Value stage(Json::objectValue);stage["name"]=name;
    stage["attributes_encoded"]=Json::UInt64(frame->attributesEncoded);
    stage["source_bytes"]=Json::UInt64(frame->sourceBytes);
    stage["mode"]="fallback";report["stages"].append(stage);
}
int main(int argc,char** argv){
 try {
    check(argc==4,"scene, dso, output required");fs::path out(argv[3]);
    rdl::SceneContext source;source.setProxyModeEnabled(true);source.setDsoPath(argv[2]);
    rdl::readSceneFromFile(argv[1],source);
    CanonicalSession service(argv[2],{81,0,0,0});
    Json::Value report(Json::objectValue);report["stages"]=Json::Value(Json::arrayValue);
    auto first=service.prepare(source,out/"first",{81,1,0,0});
    check(!service.acquire()&&!service.publish(first),"Unacknowledged first frame published");
    check(first->routing->mode==Mode::Fallback,"Unqualified scene escaped fallback");
    check(service.acknowledge(first)&&service.publish(first),"Initial publication failed");
    same(source,service.replica());exportStage(source,first,out,"initial",report);
    source.commitAllChanges();
    auto* mesh=source.getSceneObject("/modo/mesh/0");
    {rdl::SceneObject::UpdateGuard update(mesh);auto m=mesh->get<rdl::Mat4d>("node_xform");
     m[3][0]+=.25;mesh->set<rdl::Mat4d>("node_xform",m,rdl::TIMESTEP_BEGIN);
     mesh->set<rdl::Mat4d>("node_xform",m,rdl::TIMESTEP_END);}
    auto second=service.prepare(source,out/"cancelled",{81,2,0,0});
    check(service.acquire()==first,"Preparation changed active snapshot");
    bool overlap=false;try{service.prepare(source,out/"overlap",{81,3,0,0});}
    catch(const std::logic_error&){overlap=true;}
    check(overlap,"Multiple unbounded preparations accepted");
    check(service.reject(second)&&!service.publish(second),"Rejected scene published");
    check(service.acquire()==first,"Rejected scene displaced old snapshot");
    sameIndex(first->routing->scene,service.replica());
    // A staging error must preserve the active replica and permit a later retry.
    bool diskFailure=false;try{service.prepare(source,out/"missing-parent"/"cannot-create",{81,2,0,0});}
    catch(const fs::filesystem_error&){diskFailure=true;}
    check(diskFailure&&service.acquire()==first,"Staging failure changed publication");
    sameIndex(first->routing->scene,service.replica());
    auto retry=service.prepare(source,out/"retry",{81,2,0,0});
    check(retry->attributesEncoded==1,"Retry captured unrelated attributes");
    check(service.acknowledge(retry)&&service.publish(retry),"Retry failed");
    check(!service.acknowledge(second)&&!service.reject(first),"Stale handle accepted");
    same(source,service.replica());exportStage(source,retry,out,"transform",report);
    // Replacing the canonical source must not rely on the old context's dirty
    // flags. All changes in the replacement below are deliberately committed.
    rdl::SceneContext replacement;replacement.setProxyModeEnabled(true);replacement.setDsoPath(argv[2]);
    rdl::readSceneFromFile(first->scene.string(),replacement);
    auto* material=replacement.getSceneObject("/modo/material/1");
    {rdl::SceneObject::UpdateGuard update(material);
     material->set<rdl::Rgb>("diffuseColor",rdl::Rgb(.2f,.4f,.1f));}
    replacement.commitAllChanges();
    auto replaced=service.prepare(replacement,out/"replacement",{81,3,0,0});
    check(replaced->attributesEncoded>1,"Clean replacement context was not captured");
    check(service.acknowledge(replaced)&&service.publish(replaced),"Replacement publication failed");
    same(replacement,service.replica());exportStage(replacement,replaced,out,"replacement",report);
    replacement.commitAllChanges();
    replacement.createSceneObject("ConstantColorMap","/unused-map");
    auto added=service.prepare(replacement,out/"added",{81,4,0,0});
    check(service.acknowledge(added)&&service.publish(added),"Object addition failed");
    replacement.commitAllChanges();
    replacement.deleteSceneObject("/unused-map");
    auto removed=service.prepare(replacement,out/"removed",{81,5,0,0});
    check(!removed->routing->scene->entities.count(objectId("/unused-map")),"Deleted object retained");
    check(service.acknowledge(removed)&&service.publish(removed),"Object removal failed");
    sameIndex(removed->routing->scene,service.replica());
    same(replacement,service.replica());exportStage(replacement,removed,out,"removal",report);
    bool foreign=false;std::thread other([&]{try{service.acquire();}catch(const std::logic_error&){foreign=true;}});other.join();
    check(foreign,"Foreign coordinator allowed");
    report["status"]="passed";report["checks"]=checks;
    report["rejection_and_staging_failure_recovery"]=true;
    report["clean_context_replacement_and_object_removal"]=true;report["native_shading_qualified"]=false;
    Json::StreamWriterBuilder writer;writer["indentation"]="";
    std::cout<<Json::writeString(writer,report)<<std::endl;return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 1;}
}
