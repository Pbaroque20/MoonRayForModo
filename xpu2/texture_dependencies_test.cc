#include "texture_dependencies.h"
#include <iostream>
using namespace xpu2;
static unsigned checks=0;
static void check(bool ok,const char* msg){++checks;if(!ok)throw std::runtime_error(msg);}
template<class F>static void rejects(F fn){bool caught=false;try{fn();}catch(const std::exception&){caught=true;}check(caught,"Expected invalid dependency rejection");}
static indexed::Bytes identity(indexed::Kind,indexed::Field,const indexed::Bytes& b){return b;}
static indexed::Edit entity(std::string id,indexed::Kind k,std::set<std::string> deps={}){return {id,k,{{indexed::Field::Parameters,{1}}},deps,{}};}
static texture::Key key(unsigned rev=1){return {"texture.tx","raw-f32",rev};}
int main(){try{
    using namespace indexed;using namespace texture;
    SceneIndex index;auto state=emptyDependencies(index.acquire());
    SourceCatalog catalog{{"file",{{key()}, {}}}};
    Assignments bindings{{{"layer","mesh-a","skin"},"a"},{{"layer","mesh-b",""},"b"},{{"layer-2","mesh-a","skin"},"b"}};
    auto candidate=index.prepare(index.acquire(),{entity("file",Kind::Attribute),entity("map",Kind::Texture,{"file"}),entity("a",Kind::Material,{"map"}),entity("b",Kind::Material,{"map"}),entity("other",Kind::Material),entity("mesh-a",Kind::Geometry),entity("mesh-b",Kind::Geometry),entity("layer",Kind::Auxiliary),entity("layer-2",Kind::Auxiliary)}, {},identity);
    auto first=prepareDependencies(state,candidate,catalog,bindings);
    check(first->users.size()==1&&first->users.at(key())==std::set<std::string>{"a","b"},"Shared source not deduplicated");
    check(first->assignments.size()==3&&first->affectedObjects==std::set<std::string>{"mesh-a","mesh-b"},"Layer/part assignment lost");
    check(state->users.empty()&&index.acquire()==state->scene,"Prepare published early");check(!publishDependencies(state,first,index.acquire()),"Published before scene commit");check(index.commit(candidate),"Initial commit failed");check(publishDependencies(state,first,index.acquire()),"Dependency publish failed");
    auto tile=key();tile.mip=2;tile.x=4;auto requests=indexedTileRequests(state,tile,16,true);auto plan=planTextures({},requests,{64,64,0,64});
    check(requests.size()==2&&plan.admit.size()==1&&plan.gpu==16&&plan.hierarchy.size()==2,"Indexed requests duplicated memory");
    auto idle=index.prepare(index.acquire(),{}, {},identity);auto idleDeps=prepareDependencies(state,idle,catalog,bindings);
    check(idleDeps->rebuiltMaterials==0&&idleDeps->affectedObjects.empty()&&idleDeps->materials.at("a")==state->materials.at("a"),"Idle rescanned material graph");
    auto move=index.prepare(index.acquire(),{{"mesh-a",Kind::Geometry,{{Field::Transform,{2}}},{},{}}},{},identity);auto moved=prepareDependencies(state,move,catalog,bindings);
    check(moved->rebuiltMaterials==0&&moved->visitedEntities==0&&moved->addedResources.empty(),"Transform invalidated texture graph");check(index.commit(move),"Move commit failed");state=moved;
    rejects([&]{prepareDependencies(first,index.prepare(index.acquire(),{}, {},identity),catalog,bindings);});
    auto before=state;catalog["file"].resources={key(2)};auto unchanged=index.prepare(index.acquire(),{}, {},identity);auto revised=prepareDependencies(state,unchanged,catalog,bindings);
    check(revised->addedResources==std::set<Key>{key(2)}&&revised->retiredResources==std::set<Key>{key()},"Content revision did not retire old demand");
    check(revised->affectedMaterials==std::set<std::string>{"a","b"}&&revised->affectedObjects==std::set<std::string>{"mesh-a","mesh-b"},"Content change invalidation wrong");
    check(before->users.count(key())&&before->materials.at("other")==revised->materials.at("other"),"Old reader or unrelated material changed");check(publishDependencies(state,revised,index.acquire()),"Content-only publication failed");check(!publishDependencies(state,moved,index.acquire()),"Stale content-only dependency view published");
    bindings[{"layer","mesh-a","skin"}]="other";bindings.erase({"layer-2","mesh-a","skin"});auto assigned=prepareDependencies(state,unchanged,catalog,bindings);
    check(assigned->rebuiltMaterials==0&&assigned->affectedObjects==std::set<std::string>{"mesh-a"},"Assignment change rescanned textures/wrong objects");state=assigned;
    auto detach=index.prepare(index.acquire(),{{"a",Kind::Material,{},std::set<std::string>{},{}}},{},identity);auto detached=prepareDependencies(state,detach,catalog,bindings);
    check(detached->users.at(key(2))==std::set<std::string>{"b"}&&detached->retiredResources.empty(),"Shared file retired with remaining user");check(index.commit(detach),"Detach commit failed");state=detached;
    auto malformed=catalog;malformed["bad"]={};rejects([&]{prepareDependencies(state,index.prepare(index.acquire(),{}, {},identity),malformed,bindings);});
    malformed=catalog;auto invalid=key();invalid.mip=1;malformed["file"].resources={invalid};rejects([&]{prepareDependencies(state,index.prepare(index.acquire(),{}, {},identity),malformed,bindings);});
    auto badBindings=bindings;badBindings[{"layer","mesh-a",""}]="map";rejects([&]{prepareDependencies(state,index.prepare(index.acquire(),{}, {},identity),catalog,badBindings);});
    catalog["file"]={{},{"missing.tx"}};auto unresolved=prepareDependencies(state,index.prepare(index.acquire(),{}, {},identity),catalog,bindings);
    check(unresolved->materials.at("b")->unresolved.count("missing.tx")&&unresolved->retiredResources.count(key(2)),"Missing source kept stale ready resource");
    catalog["file"]={{key(2)},{"missing-udim.tx"}};auto partial=prepareDependencies(state,index.prepare(index.acquire(),{}, {},identity),catalog,bindings);rejects([&]{indexedTileRequests(partial,key(2),16,true);});
    // Repeated content-only revisions reuse scene/geometry and retain old readers.
    catalog["file"]={{key(2)},{}};
    for(unsigned revision=3;revision<1003;++revision){auto old=state;catalog["file"].resources={key(revision)};auto next=prepareDependencies(state,index.prepare(index.acquire(),{}, {},identity),catalog,bindings);
        check(next->users.size()==1&&next->users.at(key(revision))==std::set<std::string>{"b"},"Revision reverse users corrupt");
        check(next->rebuiltMaterials==1&&next->affectedMaterials==std::set<std::string>{"b"},"Unrelated material rescanned");
        check(next->affectedObjects==std::set<std::string>{"mesh-b"}&&old->materials.at("other")==next->materials.at("other"),"Unrelated object invalidation");
        check(old->users.count(key(revision-1))&&next->scene==old->scene,"Revision mutated retained reader");state=next;
    }
    auto remove=index.prepare(index.acquire(),{{"b",Kind::Material,{},std::set<std::string>{},{}}},{"map","file"},identity);catalog.clear();auto removed=prepareDependencies(state,remove,catalog,bindings);
    check(removed->users.empty()&&removed->retiredResources.size()==1,"Detach/remove retained source");check(index.commit(remove),"Remove commit failed");state=removed;
    bindings.erase({"layer","mesh-b",""});
    auto removeMaterial=index.prepare(index.acquire(),{}, {"b"},identity);auto withoutMaterial=prepareDependencies(state,removeMaterial,{},bindings);
    check(!withoutMaterial->materials.count("b")&&withoutMaterial->affectedObjects==std::set<std::string>{"mesh-b"},"Removed material retained assignment/user");
    check(index.commit(removeMaterial),"Material removal commit failed");state=withoutMaterial;
    rejects([&]{indexedTileRequests(state,key(5000),16,false);});
    auto cycle=index.prepare(index.acquire(),{entity("map",Kind::Texture,{"a"}),{"a",Kind::Material,{},std::set<std::string>{"map"},{}}},{},identity);auto cyclic=prepareDependencies(state,cycle,{},bindings);check(cyclic->visitedEntities==2,"Cyclic dependency traversal did not terminate");
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"revision_updates\":1000}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
