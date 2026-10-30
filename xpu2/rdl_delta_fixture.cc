// Produce true binary deltas from two owned native snapshots for live validation.
#include "rdl_scene_index.h"
#include <iostream>
using namespace xpu2::rdlindex;
int main(int argc,char** argv){try{
    if(argc!=5)throw std::invalid_argument("previous, next, dso path, output required");
    rdl::SceneContext prior,next;
    for(auto* context:{&prior,&next}){context->setProxyModeEnabled(true);context->setDsoPath(argv[3]);}
    rdl::readSceneFromFile(argv[1],prior);rdl::readSceneFromFile(argv[2],next);prior.commitAllChanges();
    std::set<std::string> created;size_t changed=0;
    for(auto it=next.beginSceneObject();it!=next.endSceneObject();++it){
        const auto& object=*it->second;
        if(!prior.sceneObjectExists(object.getName())){prior.createSceneObject(object.getSceneClass().getName(),object.getName());created.insert(object.getName());}
    }
    for(auto it=next.beginSceneObject();it!=next.endSceneObject();++it){
        const auto& object=*it->second;const auto* old=prior.getSceneObject(object.getName());
        for(auto attr=object.getSceneClass().beginAttributes();attr!=object.getSceneClass().endAttributes();++attr){
            auto encoded=encodeAttribute(object,**attr);
            if(created.count(object.getName())||encoded.bytes!=encodeAttribute(*old,**attr).bytes){applyAttribute(encoded.bytes,prior);++changed;}
        }
    }
    rdl::BinaryWriter writer(prior);writer.setDeltaEncoding(true);writer.setSkipDefaults(false);writer.toFile(argv[4]);
    std::cout<<"{\"changed_attributes\":"<<changed<<",\"created_objects\":"<<created.size()<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
