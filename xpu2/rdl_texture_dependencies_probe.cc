#include "rdl_texture_dependencies.h"
#include "texture_oiio_loader.h"
#include "texture_async.h"
#include <chrono>
#include <iostream>
using namespace xpu2;
using namespace xpu2::rdlindex;
static unsigned checks=0;
static void check(bool ok,const char* why){++checks;if(!ok)throw std::runtime_error(why);}
static indexed::Bytes identity(indexed::Kind,indexed::Field,const indexed::Bytes& b){return b;}
struct CpuBackend:texture::Backend{std::shared_ptr<texture::DevicePage> upload(const texture::Bytes&)override{throw std::logic_error("CPU-only dependency probe");}void drain()override{}};
int main(int argc,char** argv){try{
    check(argc==3,"Expected DSO path and immutable fixture directory");std::filesystem::path fixtures(argv[2]);
    rdl::SceneContext context;context.setProxyModeEnabled(true);context.setDsoPath(argv[1]);
    auto* image=context.createSceneObject("ImageMap","/texture");auto* a=context.createSceneObject("UsdPreviewSurface","/material/a");auto* b=context.createSceneObject("UsdPreviewSurface","/material/b");
    auto* mesh=context.createSceneObject("RdlMeshGeometry","/mesh");auto* layer=context.createSceneObject("Layer","/layer")->asA<rdl::Layer>();
    {rdl::SceneObject::UpdateGuard guard(image);image->set<rdl::String>("texture",(fixtures/"rgba.tx").u8string());}
    for(auto* m:{a,b}){rdl::SceneObject::UpdateGuard guard(m);m->setBinding("diffuseColor",image);}
    {rdl::SceneObject::UpdateGuard guard(layer);layer->assign(mesh->asA<rdl::Geometry>(),"skin",a->asA<rdl::Material>(),nullptr);layer->assign(mesh->asA<rdl::Geometry>(),"eyes",b->asA<rdl::Material>(),nullptr);}
    texture::OiioTileLoader metadata;uint64_t revision=1;std::map<std::pair<std::string,uint64_t>,texture::Key> registered;
    auto resolve=[&](const std::string&,const std::string&,const std::string& path){texture::TextureSource result;
        if(path.find("<UDIM>")!=std::string::npos||!std::filesystem::is_regular_file(std::filesystem::u8path(path))){result.unresolved.insert(path);return result;}
        auto id=std::make_pair(path,revision);auto found=registered.find(id);if(found==registered.end())found=registered.emplace(id,metadata.registerFile(std::filesystem::u8path(path),revision)).first;
        result.resources.insert(found->second);return result;
    };
    indexed::SceneIndex index;auto dependencies=texture::emptyDependencies(index.acquire());unsigned stages=0;size_t lastAttributes=0;
    auto stage=[&]{auto captured=capture(context,index.acquire());lastAttributes=captured.attributes;auto next=index.prepare(index.acquire(),captured.edits,{},identity);auto inputs=textureInputs(context,resolve);
        auto proposed=texture::prepareDependencies(dependencies,next,std::move(inputs.sources),std::move(inputs.assignments));check(index.commit(next),"Index commit failed");check(texture::publishDependencies(dependencies,proposed,index.acquire()),"Dependency publish failed");context.commitAllChanges();++stages;return proposed;};
    auto initial=stage();check(initial->users.size()==1&&initial->assignments.size()==2,"Native shared file or layer parts lost");
    auto key=initial->users.begin()->first;auto aid=objectId(a->getName()),bid=objectId(b->getName());
    check(initial->users.at(key)==std::set<std::string>{aid,bid},"Native binding traversal failed");
    auto tile=metadata.tile(key);auto requests=texture::indexedTileRequests(initial,key,tile.bytes,false);auto plan=texture::planTextures({},requests,{65536,65536,0,65536});
    check(requests.size()==2&&plan.admit.size()==1&&plan.ram==tile.bytes,"Native shared demand not deduplicated");
    CpuBackend backend;texture::Cache cache(backend,{65536,65536,65536});
    texture::AsyncTextureLoader worker([]{auto decoder=std::make_shared<texture::OiioTileLoader>();auto files=std::make_shared<std::set<std::pair<std::string,uint64_t>>>();
        return [decoder,files](const texture::Key& k,size_t n){auto id=std::make_pair(k.asset,k.revision);if(!files->count(id)){decoder->registerFile(std::filesystem::u8path(k.asset),k.revision);files->insert(id);}return decoder->load(k,n);};},65536,8);
    auto acquire=[&](const texture::Key& k){auto t=metadata.tile(k);std::optional<texture::Cache::Lease> lease;auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
        while(!(lease=texture::acquireAsync(cache,worker,k,t.bytes,false))){if(std::chrono::steady_clock::now()>=deadline)throw std::runtime_error("Decode timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
        check(cache.cpu(*lease)==metadata.load(k,t.bytes),"Indexed background decoded tile mismatch");return *lease;};
    auto oldLease=acquire(key);auto oldBytes=cache.cpu(oldLease);
    auto idle=stage();check(lastAttributes==0&&idle->rebuiltMaterials==0,"Native idle rescanned graph");
    {rdl::SceneObject::UpdateGuard guard(mesh);auto matrix=mesh->get<rdl::Mat4d>("node_xform");matrix[3][0]=2;mesh->set<rdl::Mat4d>("node_xform",matrix);}
    auto moved=stage();check(lastAttributes==1&&moved->rebuiltMaterials==0&&moved->visitedEntities==0,"Mesh transform rescanned materials");
    ++revision;auto revised=stage();auto nextKey=revised->users.begin()->first;
    check(lastAttributes==0&&revised->retiredResources.count(key)&&revised->addedResources.count(nextKey)&&nextKey.revision==2,"External content revision failed");
    auto newLease=acquire(nextKey);check(cache.cpu(oldLease)==oldBytes&&initial->users.count(key),"Retained old scene/page changed");cache.release(newLease);
    {rdl::SceneObject::UpdateGuard guard(a);a->setBinding("diffuseColor",nullptr);}
    auto detached=stage();check(detached->users.at(nextKey)==std::set<std::string>{bid}&&detached->retiredResources.empty(),"Native detach retired shared file");
    {rdl::SceneObject::UpdateGuard guard(layer);layer->assign(mesh->asA<rdl::Geometry>(),"eyes",a->asA<rdl::Material>(),nullptr);}
    auto reassigned=stage();check(reassigned->affectedObjects==std::set<std::string>{objectId(mesh->getName())}&&reassigned->rebuiltMaterials==0,"Native reassignment invalidation wrong");
    {rdl::SceneObject::UpdateGuard guard(image);image->set<rdl::String>("texture",(fixtures/"gray.tx").u8string());}
    auto switched=stage();check(switched->users.size()==1&&switched->users.begin()->first.asset!=nextKey.asset&&switched->affectedMaterials==std::set<std::string>{bid},"Native filename edit affected unrelated material");
    auto grayLease=acquire(switched->users.begin()->first);cache.release(grayLease);
    {rdl::SceneObject::UpdateGuard guard(image);image->set<rdl::String>("texture",(fixtures/"missing.<UDIM>.tx").u8string());}
    auto missing=stage();check(missing->users.empty()&&!missing->materials.at(bid)->unresolved.empty(),"Unresolved native path accepted as ready");
    cache.release(oldLease);worker.close();check(cache.close(),"Cache close failed");
    std::cout<<"{\"passed\":true,\"checks\":"<<checks<<",\"native_stages\":"<<stages<<",\"background_tiles\":"<<worker.stats().loads<<",\"native_metadata_only\":true,\"rendered_validation\":false}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
