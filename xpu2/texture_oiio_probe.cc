// Native OIIO tile/cache parity probe. GPU consumers copy bytes; no GPU sampler.
#include "texture_oiio_loader.h"
#include "texture_cuda_backend.h"
#include <OpenImageIO/texture.h>
#include <chrono>
#include <cstring>
#include <fstream>
#include <iostream>
using namespace xpu2::texture;
static unsigned checks=0,tiles=0,levels=0,points=0,gpuJobs=0;
static void require(bool ok,const std::string& why){++checks;if(!ok)throw std::runtime_error(why);}
template<class F> static void rejects(F f,const char* why){bool failed=false;try{f();}catch(const std::exception&){failed=true;}require(failed,why);}
struct CpuBackend:Backend {
    std::shared_ptr<DevicePage> upload(const Bytes&)override{throw std::logic_error("Unexpected GPU use");}
    void drain()override{}
};
static void fixtures(const std::filesystem::path& root){
    struct Spec {const char* name;int w,h,c;OIIO::TypeDesc format;};
    for(auto c:{Spec{"rgba.exr",37,23,4,OIIO::TypeDesc::FLOAT},Spec{"rgb.exr",32,16,3,OIIO::TypeDesc::HALF},Spec{"gray.tif",35,19,1,OIIO::TypeDesc::UINT8},Spec{"rg.exr",17,11,2,OIIO::TypeDesc::FLOAT}}){
        auto file=(root/c.name).u8string();auto out=OIIO::ImageOutput::create(file);require(bool(out),"Fixture writer unavailable");
        OIIO::ImageSpec spec(c.w,c.h,c.c,c.format);spec.attribute("compression","zip");
        require(out->open(file,spec),"Cannot open fixture "+out->geterror());
        std::vector<float> pixels(size_t(c.w)*c.h*c.c);
        for(int y=0;y<c.h;++y)for(int x=0;x<c.w;++x)for(int ch=0;ch<c.c;++ch)
            pixels[(y*c.w+x)*c.c+ch]=(float((x*13+y*7+ch*31)%251)+.125f)/256;
        require(out->write_image(OIIO::TypeDesc::FLOAT,pixels.data()),"Cannot write fixture");require(out->close(),"Cannot close fixture");
    }
}
static std::shared_ptr<OIIO::TextureSystem> reference(){
    auto t=OIIO::TextureSystem::create(false);
    require(t->attribute("automip",0)&&t->attribute("autotile",0)&&t->attribute("accept_untiled",0)&&t->attribute("accept_unmipped",0)&&t->attribute("gray_to_rgb",1),"Reference texture configuration failed");return t;
}
int main(int argc,char** argv){try{
    require(argc>=2,"Fixture directory required");std::filesystem::path root(argv[1]);OIIO::attribute("threads",1);OIIO::attribute("exr_threads",-1);
    if(argc>2&&std::string(argv[2])=="--fixtures"){fixtures(root);std::cout<<"{\"passed\":true}\n";return 0;}
    const bool gpu=argc>2&&std::string(argv[2])=="--gpu";
    OiioTileLoader loader;CpuBackend cpu;std::unique_ptr<CudaBackend> device;if(gpu)device=std::make_unique<CudaBackend>(8192,8192);
    Cache cache(gpu?static_cast<Backend&>(*device):static_cast<Backend&>(cpu),{8192,8192,8192});
    auto load=[&](const Key& k,size_t n){return loader.load(k,n);};
    auto ref=reference();size_t totalBytes=0;Key first;
    for(const auto* name:{"rgba.tx","rgb.tx","gray.tx","rg.tx"}){
        auto base=loader.registerFile(root/name,1);if(first.asset.empty())first=base;
        require(loader.layers(base)==1,"Unexpected fixture layer count");
        require(loader.mips(base)>1,"Fixture must contain actual mip levels");
        for(uint32_t mip=0;mip<loader.mips(base);++mip){
            Key k=base;k.mip=mip;auto s=loader.level(k);++levels;
            auto in=OIIO::ImageInput::open(k.asset);require(bool(in),"Cannot reopen mip fixture");require(in->seek_subimage(0,int(mip)),"Expected mip missing from file");auto native=in->spec();
            require(s.width==native.width&&s.height==native.height&&s.channels==native.nchannels,"Mip metadata mismatch");in->close();
            for(uint32_t y=0;y<uint32_t((s.height+s.tileHeight-1)/s.tileHeight);++y)for(uint32_t x=0;x<uint32_t((s.width+s.tileWidth-1)/s.tileWidth);++x){
                k.x=x;k.y=y;auto t=loader.tile(k);auto lease=cache.acquire(k,t.bytes,load,false);require(bool(lease),"CPU tile blocked");
                const auto& data=cache.cpu(*lease);Bytes expected(t.bytes);OIIO::TextureOpt opt;opt.subimage=int(k.layer);
                require(ref->get_texels(OIIO::ustring(k.asset),opt,int(k.mip),t.x,t.x+t.width,t.y,t.y+t.height,0,1,0,t.channels,OIIO::TypeDesc::FLOAT,expected.data()),"Reference texels failed: "+ref->geterror());
                if(data!=expected){for(size_t i=0;i<t.bytes;i+=sizeof(float)){float a,b;std::memcpy(&a,data.data()+i,4);std::memcpy(&b,expected.data()+i,4);if(std::memcmp(&a,&b,4)){std::cerr<<"tile="<<x<<","<<y<<" float="<<i/4<<" loader="<<a<<" reference="<<b<<"\n";break;}}}require(data==expected,"Raw OIIO texels differ: "+std::string(name)+" mip "+std::to_string(mip));++tiles;totalBytes+=t.bytes;
                // Check the existing OIIO point sampler at valid base-level texel centers.
                // This is not a replacement filtering implementation.
                if(mip==0){
                    opt.mipmode=OIIO::TextureOpt::MipModeNoMIP;opt.interpmode=OIIO::TextureOpt::InterpClosest;opt.swrap=opt.twrap=OIIO::TextureOpt::WrapBlack;
                    for(int yy=0;yy<t.height&&t.y+yy<s.y+s.height;++yy)for(int xx=0;xx<t.width&&t.x+xx<s.x+s.width;++xx){
                        float result[4]={};require(ref->texture(OIIO::ustring(k.asset),opt,(t.x+xx-s.x+.5f)/s.width,(t.y+yy-s.y+.5f)/s.height,0,0,0,0,t.channels,result),"Point lookup failed");
                        float raw[4]={};std::memcpy(raw,data.data()+size_t(yy*t.width+xx)*t.channels*sizeof(float),t.channels*sizeof(float));
                        require(std::memcmp(raw,result,t.channels*sizeof(float))==0,"Point lookup differs from raw tile");++points;
                    }
                }
                if(gpu&&x==0&&y==0&&(mip==0||mip==1)){
                    std::optional<Cache::Lease> gl;auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(10);
                    while(!(gl=cache.acquire(k,t.bytes,load,true))){require(std::chrono::steady_clock::now()<deadline,"GPU admission timeout");std::this_thread::sleep_for(std::chrono::milliseconds(1));}
                    CudaBackend::Consumer job(*device,cache.gpu(*gl),t.bytes);cache.retire(*gl,job.completion);
                    require(job.result()==expected,"CUDA OIIO tile differs from reference");cache.poll();++gpuJobs;
                }
                auto loads=cache.stats().loads;auto hit=cache.acquire(k,t.bytes,load,false);require(bool(hit)&&cache.stats().loads==loads,"CPU tile hit reloaded source");cache.release(*hit);cache.release(*lease);
            }
        }
    }
    auto t=loader.tile(first);auto bad=first;
    rejects([&]{loader.load(first,t.bytes-1);},"Wrong size accepted");
    bad.mip=999;rejects([&]{loader.tile(bad);},"Invalid mip accepted");bad=first;bad.layer=999;rejects([&]{loader.tile(bad);},"Invalid layer accepted");
    bad=first;bad.x=UINT32_MAX;rejects([&]{loader.tile(bad);},"Invalid tile accepted");bad=first;bad.interpretation="sRGB";rejects([&]{loader.tile(bad);},"Unsupported color conversion accepted");
    bad=first;bad.revision=9;rejects([&]{loader.load(bad,t.bytes);},"Unknown revision accepted");
    rejects([&]{loader.registerFile(root/"rgba.tx",1);},"Duplicate revision accepted");
    rejects([&]{loader.registerFile(root/"missing.tx",1);},"Missing file accepted");
    rejects([&]{loader.registerFile(root/"rgba.exr",1);},"Untiled unmipped source accepted");
    rejects([&]{loader.registerFile(root/"unmipped.tx",1);},"Unmipped source accepted");
    OiioTileLoader tiny(1,32);rejects([&]{tiny.registerFile(root/"rgba.tx",1);},"Oversized tile accepted");
    OiioTileLoader limited(1);limited.registerFile(root/"rgba.tx",1);rejects([&]{limited.registerFile(root/"rgb.tx",1);},"Registry cap exceeded");
    // File changes must never be silently loaded into an existing immutable key.
    auto changing=root/"changing.tx";std::filesystem::copy_file(root/"rgba.tx",changing);
    auto old=loader.registerFile(changing,10);auto oldTile=loader.tile(old);auto held=cache.acquire(old,oldTile.bytes,load,false);require(bool(held),"Old revision admission failed");auto oldBytes=cache.cpu(*held);
    auto stamp=std::filesystem::last_write_time(changing);std::filesystem::copy_file(root/"rgb.tx",changing,std::filesystem::copy_options::overwrite_existing);
    std::filesystem::last_write_time(changing,stamp+std::chrono::seconds(2));
    rejects([&]{loader.load(old,oldTile.bytes);},"Changed file loaded under old revision");
    auto fresh=loader.registerFile(changing,11);auto freshTile=loader.tile(fresh);auto freshBytes=loader.load(fresh,freshTile.bytes);
    require(freshBytes!=oldBytes&&cache.cpu(*held)==oldBytes,"Revision retention failed");cache.release(*held);
    const auto stats=cache.stats();require(stats.cpuEvictions>0,"RAM eviction not exercised");require(!gpu||stats.gpuEvictions>0,"GPU eviction not exercised");require(stats.peakRam<=8192&&stats.peakVram<=8192&&stats.peakStaging<=8192,"Cache memory limit exceeded");require(stats.d2hBytes==0,"Clean tile eviction read back GPU");
    require(cache.close(),"Texture cache failed to drain");
    uint64_t readback=0;if(device){readback=device->verificationReadbackBytes;require(device->close()&&!device->cleanupErrors,"CUDA cleanup failed");}
    std::cout<<"{\"passed\":true,\"oiio_version\":\""<<OIIO_VERSION_STRING<<"\",\"checks\":"<<checks<<",\"tiles\":"<<tiles<<",\"mip_levels\":"<<levels<<",\"point_samples\":"<<points<<",\"compared_bytes\":"<<totalBytes<<",\"cuda_consumers\":"<<gpuJobs<<",\"loads\":"<<stats.loads<<",\"cpu_evictions\":"<<stats.cpuEvictions<<",\"gpu_evictions\":"<<stats.gpuEvictions<<",\"h2d_bytes\":"<<stats.h2dBytes<<",\"eviction_d2h_bytes\":"<<stats.d2hBytes<<",\"verification_d2h_bytes\":"<<readback<<",\"peak_ram\":"<<stats.peakRam<<",\"peak_vram\":"<<stats.peakVram<<",\"peak_staging\":"<<stats.peakStaging<<"}\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
