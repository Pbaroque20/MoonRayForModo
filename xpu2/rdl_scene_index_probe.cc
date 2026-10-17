// Round-trip real native RDL scenes through the owned index, then apply dirty edits.
#include "rdl_replica.h"
#include <filesystem>
#include <iostream>
#include <json/json.h>
#include <chrono>
using namespace xpu2::rdlindex;
static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static Bytes identity(Kind,Field,const Bytes& bytes){return bytes;}
static void compare(const rdl::SceneContext& source,const rdl::SceneContext& target){
    size_t count=0,targetCount=0;
    for(auto it=source.beginSceneObject();it!=source.endSceneObject();++it){
        ++count;const auto& a=*it->second;const auto* b=target.getSceneObject(a.getName());
        check(a.getSceneClass().getName()==b->getSceneClass().getName(),"Class changed");
        for(auto attr=a.getSceneClass().beginAttributes();attr!=a.getSceneClass().endAttributes();++attr)
            check(encodeAttribute(a,**attr).bytes==encodeAttribute(*b,**attr).bytes,"Native attribute round-trip mismatch");
    }
    for(auto it=target.beginSceneObject();it!=target.endSceneObject();++it)++targetCount;
    check(count==targetCount,"Native object count changed");
}
static void write(const rdl::SceneContext& context,const std::filesystem::path& path){rdl::BinaryWriter(context).toFile(path.string());}
int main(int argc,char** argv){
 try{
    check(argc==4,"scene, dso path and output directory required");
    std::filesystem::path out(argv[3]);
    rdl::SceneContext source;source.setProxyModeEnabled(true);
    source.setDsoPath(argv[2]);rdl::readSceneFromFile(argv[1],source);
    SceneIndex index;NativeReplica replica(argv[2],index.acquire());Json::Value report(Json::objectValue);report["stages"]=Json::Value(Json::arrayValue);
    auto stage=[&](const char* name,bool initial){
        auto begin=std::chrono::steady_clock::now();
        auto captured=capture(source,index.acquire());
        auto mid=std::chrono::steady_clock::now();
        auto candidate=index.prepare(index.acquire(),captured.edits,{},identity);
        auto prepared=std::chrono::steady_clock::now();
        replica.applyCandidate(candidate);
        auto applied=std::chrono::steady_clock::now();
        compare(source,replica.context());
        check(index.commit(candidate),"Index commit rejected");
        Json::Value row(Json::objectValue);row["name"]=name;row["objects"]=Json::UInt64(captured.objects);
        row["attributes_encoded"]=Json::UInt64(captured.attributes);row["source_bytes"]=Json::UInt64(captured.bytes);
        row["prepared_buffers"]=Json::UInt64(candidate.view()->changes.preparedBuffers);
        row["direct_changes"]=Json::UInt64(candidate.view()->changes.direct.size());
        row["affected_entities"]=Json::UInt64(candidate.view()->changes.affected.size());
        row["capture_us"]=Json::Int64(std::chrono::duration_cast<std::chrono::microseconds>(mid-begin).count());
        row["prepare_us"]=Json::Int64(std::chrono::duration_cast<std::chrono::microseconds>(prepared-mid).count());
        row["apply_us"]=Json::Int64(std::chrono::duration_cast<std::chrono::microseconds>(applied-prepared).count());
        row["exact_native_attributes"]=true;report["stages"].append(row);
        std::cerr<<"indexed stage "<<name<<": "<<captured.attributes<<" attributes, "<<captured.bytes<<" bytes\n";
        write(source,out/(std::string(name)+"-source.rdlb"));write(replica.context(),out/(std::string(name)+"-indexed.rdlb"));
        source.commitAllChanges();
        return candidate.view();
    };
    auto first=stage("initial",true);
    auto unchanged=capture(source,index.acquire());
    check(unchanged.attributes==0&&unchanged.edits.empty(),"Idle capture touched attributes");
    auto noChange=index.prepare(index.acquire(),unchanged.edits,{},identity);
    check(noChange.view()==index.acquire(),"Idle capture changed revision");
    auto* mesh=source.getSceneObject("/modo/mesh/0");
    std::string positionName;
    for(auto attr=mesh->getSceneClass().beginAttributes();attr!=mesh->getSceneClass().endAttributes();++attr)
        if(field(**attr)==Field::Positions&&(*attr)->getType()==rdl::TYPE_VEC3F_VECTOR &&
           !mesh->get<rdl::Vec3fVector>((*attr)->getName()).empty())positionName=(*attr)->getName();
    check(!positionName.empty(),"Fixture has no position field");
    auto positionId=attributeId(mesh->getName(),positionName);
    auto positionBuffer=first->entities.at(positionId)->buffers.at(Field::Positions);
    {rdl::SceneObject::UpdateGuard guard(mesh);auto matrix=mesh->get<rdl::Mat4d>("node_xform");matrix[3][0]+=.25;
     mesh->set<rdl::Mat4d>("node_xform",matrix,rdl::TIMESTEP_BEGIN);mesh->set<rdl::Mat4d>("node_xform",matrix,rdl::TIMESTEP_END);}
    auto moved=stage("transform",false);
    check(moved->entities.at(positionId)->buffers.at(Field::Positions)==positionBuffer,"Transform rebuilt geometry buffer");
    auto* material=source.getSceneObject("/modo/material/1");
    {rdl::SceneObject::UpdateGuard guard(material);material->set<rdl::Rgb>("diffuseColor",rdl::Rgb(.1f,.5f,.8f));}
    auto shaded=stage("material",false);
    check(shaded->entities.at(positionId)->buffers.at(Field::Positions)==positionBuffer,"Material rebuilt geometry buffer");
    {rdl::SceneObject::UpdateGuard guard(mesh);auto positions=mesh->get<rdl::Vec3fVector>(positionName);
     for(auto& p:positions)p[1]*=.8f;mesh->set<rdl::Vec3fVector>(positionName,positions);}
    auto deformed=stage("deformation",false);
    check(deformed->entities.at(positionId)->buffers.at(Field::Positions)!=positionBuffer,"Deformation reused stale geometry");
    for(unsigned i=1;i<report["stages"].size();++i){
        check(report["stages"][i]["attributes_encoded"].asUInt64()==1,"Dirty edit encoded unrelated native attributes");
        check(report["stages"][i]["prepared_buffers"].asUInt64()==1,"Dirty edit prepared unrelated buffers");
    }
    auto* map=source.createSceneObject("ConstantColorMap","/index-test/constant");
    {rdl::SceneObject::UpdateGuard guard(map);map->set<rdl::Rgb>("color_value",rdl::Rgb(.2f,.8f,.1f));}
    {rdl::SceneObject::UpdateGuard guard(material);material->setBinding("diffuseColor",map);}
    auto bound=stage("binding",false);
    {rdl::SceneObject::UpdateGuard guard(material);material->setBinding("diffuseColor",nullptr);}
    auto unbound=stage("unbinding",false);
    check(report["stages"][5]["attributes_encoded"].asUInt64()==1,"Unbinding re-encoded unrelated attributes");
    check(unbound->entities.at(positionId)->buffers==deformed->entities.at(positionId)->buffers,"Binding edit copied geometry");
    // Wrong/foreign bases never mutate an acknowledged native replica.
    SceneIndex foreign;
    auto foreignCandidate=foreign.prepare(foreign.acquire(),{}, {},identity);
    bool foreignRejected=false;try{replica.applyCandidate(foreignCandidate);}catch(const std::invalid_argument&){foreignRejected=true;}
    check(foreignRejected&&replica.valid()&&replica.acknowledged()==index.acquire(),"Foreign candidate changed replica");
    // Malformed data must invalidate the replica without committing its index.
    auto bytes=deformed->entities.at(positionId)->buffers.at(Field::Positions)->prepared;bytes.pop_back();
    auto bad=index.prepare(index.acquire(),{{positionId,Kind::Attribute,{{Field::Positions,bytes}},{},{}}},{},identity);
    auto beforeFailure=index.acquire();
    bool rejected=false;try{replica.applyCandidate(bad);}catch(const std::exception&){rejected=true;}
    check(rejected&&!replica.valid()&&index.current(beforeFailure),"Failed native application changed index or remained usable");
    replica.rebuild(beforeFailure);compare(source,replica.context());
    report["replica_base_guard_and_recovery"]=true;
    report["status"]="passed";report["idle_attributes_encoded"]=0;
    report["geometry_reused_for_transform_and_material"]=true;report["truncated_payload_rejected"]=true;
    Json::StreamWriterBuilder writer;writer["indentation"]="";std::cout<<Json::writeString(writer,report)<<'\n';return 0;
 }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
