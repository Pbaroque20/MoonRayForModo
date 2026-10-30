// Experimental OIIO 3.1 raw mip loader. No GPU filtering or color conversion.
#pragma once
#include "texture_cache.h"
#include <OpenImageIO/imagecache.h>
#include <filesystem>
#include <limits>
namespace xpu2::texture {
class OiioTileLoader {
public:
    struct Tile {Key key;int x=0,y=0,width=0,height=0,channels=0;size_t bytes=0;};
    struct Level {int x=0,y=0,width=0,height=0,tileWidth=0,tileHeight=0,channels=0;};
private:
    struct Stamp {
        uintmax_t size;std::filesystem::file_time_type modified;
        bool operator==(const Stamp& s)const{return size==s.size&&modified==s.modified;}
    };
    struct Asset {std::filesystem::path path;Stamp stamp;std::vector<std::vector<Level>> layers;};
    std::shared_ptr<OIIO::ImageCache> cache_=OIIO::ImageCache::create(false);
    std::map<std::pair<std::string,uint64_t>,Asset> assets_;
    size_t maxAssets_,maxTileBytes_;
    const std::thread::id owner_=std::this_thread::get_id();
    static Stamp stamp(const std::filesystem::path& p){return {std::filesystem::file_size(p),std::filesystem::last_write_time(p)};}
    void check()const{if(std::this_thread::get_id()!=owner_)throw std::logic_error("OIIO loader owner violation");}
    std::runtime_error error(const std::string& operation){return std::runtime_error(operation+": "+cache_->geterror());}
    static void unchanged(const Asset& a){if(!(stamp(a.path)==a.stamp))throw std::runtime_error("Texture source changed; register a new immutable revision");}
    const Asset& asset(const Key& k)const{
        check();if(k.interpretation!=interpretation())throw std::invalid_argument("Unsupported texture interpretation");
        auto i=assets_.find({k.asset,k.revision});if(i==assets_.end())throw std::invalid_argument("Unregistered texture revision");return i->second;
    }
public:
    // Raw decoded native channels, FLOAT output. Gamma/OCIO stays in shading.
    static std::string interpretation(){return std::string("oiio-")+OIIO_VERSION_STRING+"/native-channels/f32/raw/v1";}
    explicit OiioTileLoader(size_t maxAssets=1024,size_t maxTileBytes=16<<20,float oiioMemoryMiB=32):maxAssets_(maxAssets),maxTileBytes_(maxTileBytes){
        if(!maxAssets||!maxTileBytes||!(oiioMemoryMiB>0&&oiioMemoryMiB<=4096))throw std::invalid_argument("Invalid OIIO loader limits");
        if(!cache_->attribute("automip",0)||!cache_->attribute("autotile",0)||!cache_->attribute("accept_untiled",0)||!cache_->attribute("accept_unmipped",0)
           ||!cache_->attribute("max_memory_MB",oiioMemoryMiB)||!cache_->attribute("max_open_files",32))throw error("OIIO cache configuration failed");
    }
    OiioTileLoader(const OiioTileLoader&)=delete;
    OiioTileLoader& operator=(const OiioTileLoader&)=delete;
    Key registerFile(const std::filesystem::path& path,uint64_t revision){
        check();if(!revision)throw std::invalid_argument("An explicit content revision is required");
        auto p=std::filesystem::canonical(path);auto name=p.u8string();Key key{name,interpretation(),revision};
        if(assets_.count({name,revision}))throw std::invalid_argument("Texture revision already registered");
        if(assets_.size()>=maxAssets_)throw std::length_error("Texture registry full");
        Asset a{p,stamp(p),{}};OIIO::ustring file(name);
        // Never use OIIO data retained from a preceding generation at this path.
        cache_->invalidate(file,true);
        int subimages=0;
        if(!cache_->get_image_info(file,0,0,OIIO::ustring("subimages"),OIIO::TypeDesc::INT,&subimages))throw error("Texture metadata read failed");
        if(subimages<1||subimages>64)throw std::length_error("Unsupported texture subimage count");
        for(int layer=0;layer<subimages;++layer){
            int mips=0;if(!cache_->get_image_info(file,layer,0,OIIO::ustring("miplevels"),OIIO::TypeDesc::INT,&mips))throw error("Mip metadata read failed");
            if(mips<1||mips>32)throw std::length_error("Unsupported mip count");
            std::vector<Level> levels;
            for(int mip=0;mip<mips;++mip){
                OIIO::ImageSpec s;
                // OIIO 3.x imagespec() ignores mip. Use actual cache dimensions.
                if(!cache_->get_cache_dimensions(file,s,layer,mip))throw error("Mip dimensions read failed");
                if(s.deep||s.depth!=1||s.z!=0||s.tile_depth>1||s.width<=0||s.height<=0||s.tile_width<=0||s.tile_height<=0||s.nchannels<=0||s.nchannels>64)
                    throw std::invalid_argument("Only tiled, non-deep 2D textures are supported by this loader");
                const auto row=uint64_t(s.tile_width)*uint64_t(s.nchannels);
                if(row>maxTileBytes_/sizeof(float)||uint64_t(s.tile_height)>maxTileBytes_/sizeof(float)/row)throw std::length_error("Texture tile exceeds loader limit");
                // Reject windows whose padded tile coordinates cannot fit OIIO's int API.
                for(auto range:{std::tuple<int,int,int>{s.x,s.width,s.tile_width},{s.y,s.height,s.tile_height}}){
                    auto [start,extent,tile]=range;int64_t end=int64_t(start)+((int64_t(extent)+tile-1)/tile)*tile;
                    if(end>std::numeric_limits<int>::max())throw std::length_error("Texture window overflow");
                }
                levels.push_back({s.x,s.y,s.width,s.height,s.tile_width,s.tile_height,s.nchannels});
            }
            a.layers.push_back(std::move(levels));
        }
        unchanged(a);assets_.emplace(std::make_pair(name,revision),std::move(a));return key;
    }
    size_t layers(const Key& key)const{return asset(key).layers.size();}
    size_t mips(const Key& key)const{const auto& a=asset(key);if(key.layer>=a.layers.size())throw std::out_of_range("Invalid texture layer");return a.layers[key.layer].size();}
    const Level& level(const Key& key)const{
        const auto& a=asset(key);if(key.layer>=a.layers.size()||key.mip>=a.layers[key.layer].size())throw std::out_of_range("Invalid texture mip/layer");return a.layers[key.layer][key.mip];
    }
    Tile tile(const Key& key)const{
        auto s=level(key);if(key.x>=uint32_t((int64_t(s.width)+s.tileWidth-1)/s.tileWidth)||key.y>=uint32_t((int64_t(s.height)+s.tileHeight-1)/s.tileHeight))throw std::out_of_range("Invalid texture tile coordinates");
        return {key,int(int64_t(s.x)+int64_t(key.x)*s.tileWidth),int(int64_t(s.y)+int64_t(key.y)*s.tileHeight),s.tileWidth,s.tileHeight,s.channels,size_t(s.tileWidth)*size_t(s.tileHeight)*size_t(s.channels)*sizeof(float)};
    }
    Bytes load(const Key& key,size_t bytes){
        auto t=tile(key);if(bytes!=t.bytes)throw std::invalid_argument("Texture tile byte count mismatch");
        const auto& a=asset(key);unchanged(a);Bytes result(t.bytes,0);auto s=level(key);
        if(!cache_->get_pixels(OIIO::ustring(key.asset),int(key.layer),int(key.mip),t.x,std::min(t.x+t.width,s.x+s.width),t.y,std::min(t.y+t.height,s.y+s.height),0,1,0,t.channels,OIIO::TypeDesc::FLOAT,result.data(),OIIO::stride_t(t.channels)*sizeof(float),OIIO::stride_t(t.width)*t.channels*sizeof(float)))throw error("Texture tile decode failed");
        unchanged(a);return result;
    }
};
} // namespace xpu2::texture
