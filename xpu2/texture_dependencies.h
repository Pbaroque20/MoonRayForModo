// Immutable projection of indexed shader graphs onto exact texture identities.
#pragma once
#include "indexed_scene.h"
#include "texture_residency.h"
namespace xpu2::texture {
struct TextureSource {
    std::set<Key> resources;
    std::set<std::string> unresolved;
    bool operator==(const TextureSource& s)const{return resources==s.resources&&unresolved==s.unresolved;}
};
using SourceCatalog=std::map<std::string,TextureSource>; // indexed filename-attribute ID -> resolved resources
using Assignment=std::tuple<std::string,std::string,std::string>; // layer, geometry, part
using Assignments=std::map<Assignment,std::string>; // assignment -> material ID
struct MaterialTextures {
    std::set<Key> resources;
    std::set<std::string> unresolved;
    bool operator==(const MaterialTextures& m)const{return resources==m.resources&&unresolved==m.unresolved;}
};
struct DependencySnapshot {
    std::shared_ptr<const int> token=std::make_shared<const int>(0),baseToken;
    indexed::View scene;
    SourceCatalog sources;
    Assignments assignments;
    indexed::PersistentMap<std::string,std::shared_ptr<const MaterialTextures>> materials;
    indexed::PersistentMap<Key,std::set<std::string>> users;
    std::set<std::string> affectedMaterials,affectedObjects;
    std::set<Key> addedResources,retiredResources;
    size_t rebuiltMaterials=0,visitedEntities=0;
};
using DependencyView=std::shared_ptr<const DependencySnapshot>;
inline Key resourceKey(Key key){key.mip=key.x=key.y=key.layer=0;return key;}
inline DependencyView emptyDependencies(indexed::View scene){
    if(!scene||!scene->entities.empty())throw std::invalid_argument("Dependency index requires empty starting scene");
    auto out=std::make_shared<DependencySnapshot>();out->scene=std::move(scene);return out;
}
// Pure preparation. Publish this view only after the native adapter acknowledges
// candidate and SceneIndex commits its matching view. Old readers retain old keys.
inline DependencyView prepareDependencies(const DependencyView& previous,const indexed::SceneIndex::Candidate& candidate,
                                          SourceCatalog sources,Assignments assignments){
    if(!previous||previous->scene!=candidate.baseView())throw std::invalid_argument("Stale texture dependency base");
    auto scene=candidate.view();
    if(sources.size()>65536||assignments.size()>1000000)throw std::length_error("Dependency input limit");
    for(const auto& [slot,source]:sources){
        if(!scene->entities.count(slot))throw std::invalid_argument("Unknown texture source slot");
        for(const auto& k:source.resources)if(k.asset.empty()||k.interpretation.empty()||!k.revision||!(resourceKey(k)==k))throw std::invalid_argument("Expected immutable base texture identity");
        if(source.resources.size()+source.unresolved.size()>65536)throw std::length_error("Texture source expansion limit");
    }
    for(const auto& [assignment,material]:assignments){
        auto [layer,object,part]=assignment;
        if(!scene->entities.count(layer)||!scene->entities.count(object)||!scene->entities.count(material)||scene->entities.at(material)->kind!=indexed::Kind::Material)
            throw std::invalid_argument("Invalid indexed material assignment");
        auto kind=scene->entities.at(object)->kind;if(kind!=indexed::Kind::Geometry&&kind!=indexed::Kind::Instance)throw std::invalid_argument("Assignment is not geometry");
    }
    auto out=std::make_shared<DependencySnapshot>();out->scene=scene;out->baseToken=previous->token;out->sources=std::move(sources);out->assignments=std::move(assignments);
    out->materials=previous->materials;out->users=previous->users;
    std::set<std::string> touched;
    if(scene!=previous->scene){touched=scene->changes.affected;for(const auto& id:scene->changes.removed)touched.insert(id);}
    for(const auto& [id,s]:out->sources){auto old=previous->sources.find(id);if(old==previous->sources.end()||!(old->second==s))touched.insert(id);}
    for(const auto& [id,s]:previous->sources)if(!out->sources.count(id))touched.insert(id);
    // Include old reverse edges as well as new ones for detach/remove transactions.
    for(const auto& graph:{previous->scene,scene}){
        std::deque<std::string> queue(touched.begin(),touched.end());std::set<std::string> seen=touched;
        while(!queue.empty()){auto id=queue.front();queue.pop_front();
            auto e=graph->entities.find(id);if(e!=graph->entities.end()&&e->second->kind==indexed::Kind::Material)out->affectedMaterials.insert(id);
            auto users=graph->consumers.find(id);if(users!=graph->consumers.end())for(const auto& user:users->second)if(seen.insert(user).second)queue.push_back(user);
        }
    }
    std::map<Key,std::set<std::string>> changedUsers;
    auto usersFor=[&](const Key& key)->std::set<std::string>&{
        auto i=changedUsers.find(key);if(i==changedUsers.end())i=changedUsers.emplace(key,previous->users.count(key)?previous->users.at(key):std::set<std::string>{}).first;return i->second;
    };
    for(const auto& material:out->affectedMaterials){
        auto old=previous->materials.find(material);std::shared_ptr<const MaterialTextures> prior=old==previous->materials.end()?nullptr:old->second;
        std::shared_ptr<MaterialTextures> next;
        if(scene->entities.count(material)){
            next=std::make_shared<MaterialTextures>();std::deque<std::string> queue{material};std::set<std::string> seen{material};++out->rebuiltMaterials;
            while(!queue.empty()){auto id=queue.front();queue.pop_front();++out->visitedEntities;
                auto source=out->sources.find(id);if(source!=out->sources.end()){next->resources.insert(source->second.resources.begin(),source->second.resources.end());next->unresolved.insert(source->second.unresolved.begin(),source->second.unresolved.end());}
                for(const auto& dependency:scene->entities.at(id)->dependencies)if(seen.insert(dependency).second)queue.push_back(dependency);
            }
            if(next->resources.size()+next->unresolved.size()>65536)throw std::length_error("Material texture dependency limit");
        }
        if(prior)for(const auto& key:prior->resources)if(!next||!next->resources.count(key))usersFor(key).erase(material);
        if(next){for(const auto& key:next->resources)if(!prior||!prior->resources.count(key))usersFor(key).insert(material);
            out->materials.set(material,prior&&*prior==*next?prior:next);
        }else out->materials.erase(material);
    }
    for(const auto& [key,users]:changedUsers){
        bool existed=previous->users.count(key)!=0;
        if(users.empty()){out->users.erase(key);if(existed)out->retiredResources.insert(key);}
        else{out->users.set(key,users);if(!existed)out->addedResources.insert(key);}
    }
    for(const auto& [a,m]:previous->assignments){auto next=out->assignments.find(a);if(next==out->assignments.end()||next->second!=m||out->affectedMaterials.count(m))out->affectedObjects.insert(std::get<1>(a));}
    for(const auto& [a,m]:out->assignments){auto old=previous->assignments.find(a);if(old==previous->assignments.end()||old->second!=m||out->affectedMaterials.count(m))out->affectedObjects.insert(std::get<1>(a));}
    return out;
}
// Coordinator-only publication. A file revision can change without a scene
// revision, so the dependency base token must also match, not just scene identity.
inline bool publishDependencies(DependencyView& current,const DependencyView& next,const indexed::View& committedScene){
    if(!current||!next||next->baseToken!=current->token||next->scene!=committedScene)return false;
    current=next;return true;
}
// Translate an explicit sampled tile demand into existing residency-policy input.
// Mip choice, bounds validation and device capability checks belong to the sampler.
inline std::vector<TextureRequest> indexedTileRequests(const DependencyView& dependencies,const Key& tile,size_t bytes,bool gpu){
    if(!dependencies||!bytes)throw std::invalid_argument("Missing dependency snapshot/tile bytes");
    auto users=dependencies->users.find(resourceKey(tile));if(users==dependencies->users.end())throw std::invalid_argument("Unreferenced texture demand");
    std::vector<TextureRequest> result;
    for(const auto& material:users->second){if(!dependencies->materials.at(material)->unresolved.empty())throw std::runtime_error("Material has unresolved texture sources");
        result.push_back({material,tile,bytes,gpu,true,1,1,0,0,0});}
    return result;
}
} // namespace xpu2::texture
