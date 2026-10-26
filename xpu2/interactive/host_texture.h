// Private Windows host-only ImageMap subset. No GPU level-0 copy or hardware filtering.
#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <OpenImageIO/texture.h>
#include <OpenImageIO/imageio.h>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include "surface_core.h"
#include "texture_core.h"
#include <vector>
namespace xpu2::interactive::texture {
inline void need(bool v,const char* s){if(!v)throw std::runtime_error(s);}
inline std::shared_ptr<OIIO::TextureSystem> system(){
 auto s=OIIO::TextureSystem::create(false);need(bool(s),"OIIO texture system unavailable");
 for(auto n:{"automip","autotile","accept_untiled","accept_unmipped"})need(s->attribute(n,0),"OIIO option");
 need(s->attribute("gray_to_rgb",1)&&s->attribute("max_memory_MB",1024.0f),"OIIO budget option");return s;
}
inline void admittedPath(const std::filesystem::path& path,const std::filesystem::path& root){
 need(path.is_absolute()&&root.is_absolute()&&path.extension()==".tx","Frozen absolute TX required");
 auto rel=std::filesystem::weakly_canonical(path).lexically_relative(std::filesystem::canonical(root));
 need(!rel.empty()&&!rel.is_absolute()&&*rel.begin()!="..","Texture outside frozen asset root");
}
// MOONRAY_MODO_OPAQUE_ALPHA (BasicTexture, UdimTexture): a missing channel is filled with one (opaque), else with
// OpenImageIO's fill, zero. Read once, as MoonRay reads it.
inline bool modoOpaqueAlpha(){static const bool on=[]{const char* v=std::getenv("MOONRAY_MODO_OPAQUE_ALPHA");return v&&v[0]=='1';}();return on;}
// A texel as MoonRay's TextureSampler looks up four channels (gray_to_rgb): a grey image's channel in red, green and
// blue, a grey and alpha image's (alpha channel 1) grey in all three and its alpha fourth, and any channel the file
// lacks the fill.
inline void texelChannels(const float* d,int n,int alphaChannel,surface::V3& c,float& a){
 const float fill=modoOpaqueAlpha()?1.0f:0.0f;
 if(n==1){c={d[0],d[0],d[0]};a=fill;}
 else if(n==2){if(alphaChannel==1){c={d[0],d[0],d[0]};a=d[1];}else{c={d[0],d[1],fill};a=fill;}}
 else{c={d[0],d[1],d[2]};a=n>3?d[3]:fill;}}
// alpha: the texture's alpha as each texel's three channels (ImageMap's alpha_only; texelChannels' where the file has
// none).
struct Pyramid {
 tex::Image image;std::vector<std::vector<surface::V3>> tiles;
 std::vector<std::vector<const surface::V3*>> pages;uint64_t bytes=0;
 explicit Pyramid(const std::string& name,bool alpha=false){auto in=OIIO::ImageInput::open(name);need(bool(in),"Pyramid read");pages.reserve(tex::MaxLevels);
  for(unsigned level=0;level<tex::MaxLevels&&in->seek_subimage(0,level);++level){auto spec=in->spec();need(spec.get_int_attribute("sampleborder",0)==0&&spec.get_int_attribute("oiio:sampleborder",0)==0,"Border-sampled TX unsupported");
   unsigned w=spec.width,h=spec.height,nx=(w+tex::Tile-1)/tex::Tile,ny=(h+tex::Tile-1)/tex::Tile;std::vector<float> decoded(size_t(w)*h*spec.nchannels);
   need(in->read_image(0,int(level),0,spec.nchannels,OIIO::TypeDesc::FLOAT,decoded.data()),"Stored mip decode");pages.emplace_back(nx*ny,nullptr);auto& page=pages.back();
   for(unsigned y=0;y<ny;++y)for(unsigned x=0;x<nx;++x){unsigned tw=std::min(tex::Tile,w-x*tex::Tile),th=std::min(tex::Tile,h-y*tex::Tile);tiles.emplace_back(tw*th);auto& tile=tiles.back();
    for(unsigned j=0;j<th;++j)for(unsigned i=0;i<tw;++i){size_t idx=(size_t(y*tex::Tile+j)*w+x*tex::Tile+i)*spec.nchannels;surface::V3 c;float a;
     texelChannels(&decoded[idx],spec.nchannels,spec.alpha_channel,c,a);
     // Negative values are kept, as MoonRay's texture sampler keeps them (a signed displacement or vector map).
     if(alpha)c={a,a,a};need(surface::finite(c),"Invalid TX sample");tile[j*tw+i]=c;}
    page[y*nx+x]=tile.data();bytes+=tile.size()*sizeof(surface::V3);
   }image.levels[level]={w,h,page.data()};++image.count;
  }need(image.count&&image.levels[image.count-1].width==1&&image.levels[image.count-1].height==1,"Software mip level bound");
 }
};
struct File {
 std::shared_ptr<OIIO::TextureSystem> system;OIIO::ustring name;HANDLE lock=INVALID_HANDLE_VALUE;bool eightBit=false;unsigned levels=0;uint64_t decodedBytes=0;std::shared_ptr<const Pyramid> pyramid;
 bool alpha=false;  // its alpha as its colour (ImageMap's alpha_only), a texture of its own beside the file's colour
 File(const std::filesystem::path& path,const std::filesystem::path& root,std::shared_ptr<OIIO::TextureSystem> s,bool alphaOnly=false):system(std::move(s)),name(path.string()),alpha(alphaOnly){
  admittedPath(path,root);
  // Retain a read lease: no writer or delete can change the file under OIIO's cache.
  lock=CreateFileW(path.c_str(),GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
  need(lock!=INVALID_HANDLE_VALUE,"Cannot lease immutable texture");
  try{LARGE_INTEGER bytes{};need(GetFileSizeEx(lock,&bytes)&&bytes.QuadPart>0&&bytes.QuadPart<=(1ll<<30),"Texture file budget");
   auto in=OIIO::ImageInput::open(path.string());need(bool(in),"TX open failed");
   int w=0,h=0;for(int level=0;level<32;++level){if(!in->seek_subimage(0,level))break;const auto& spec=in->spec();
    need(spec.depth==1&&spec.x==0&&spec.y==0&&spec.z==0&&spec.full_x==0&&spec.full_y==0&&spec.full_width==spec.width&&spec.full_height==spec.height&&spec.width>0&&spec.height>0&&spec.tile_width>0&&spec.tile_height>0&&spec.nchannels>=1&&spec.nchannels<=4&&spec.channelformats.empty()&&!spec.deep,"Unsupported TX layout");
    if(level==0){eightBit=spec.format==OIIO::TypeDesc::UINT8;need(eightBit||spec.format==OIIO::TypeDesc::HALF||spec.format==OIIO::TypeDesc::FLOAT,"Unsupported TX format");}
    else need(spec.width==std::max(1,w/2)&&spec.height==std::max(1,h/2),"Invalid stored mip pyramid");
    w=spec.width;h=spec.height;decodedBytes+=uint64_t(w)*h*spec.nchannels*4;need(decodedBytes<=(2ull<<30),"Decoded texture budget");++levels;
   }need(levels>0&&w==1&&h==1,"Complete stored mip pyramid required");need(!in->seek_subimage(1,0),"Multipart texture unsupported");
   OIIO::ImageSpec spec;need(system->get_imagespec(name,spec),"OIIO texture admission failed");
  }catch(...){CloseHandle(lock);lock=INVALID_HANDLE_VALUE;throw;}
 }
 ~File(){if(lock!=INVALID_HANDLE_VALUE)CloseHandle(lock);}File(const File&)=delete;
};
struct Binding {
 std::shared_ptr<File> file;float sx=1,sy=1,ox=0,oy=0,mipBias=0;bool wrap=true,gamma=false;
 tex::Binding descriptor()const{return {file->pyramid?&file->pyramid->image:nullptr,sx,sy,ox,oy,mipBias,wrap?1u:0u,gamma&&file->eightBit?1u:0u};}
 surface::V3 lookup(float u,float v,float dudx,float dvdx,float dudy,float dvdy)const{
  OIIO::TextureOpt options;options.anisotropic=4;options.mipmode=OIIO::TextureOpt::MipModeAniso;options.interpmode=OIIO::TextureOpt::InterpBilinear;
  options.swrap=options.twrap=wrap?OIIO::TextureOpt::WrapPeriodic:OIIO::TextureOpt::WrapClamp;
  float out[4];float bias=1+mipBias;
  // ImageMap's primary-hit derivative scaling and T flip, including its cross-axis convention.
  need(file->system->texture(file->name,options,sx*u+ox,1-(sy*v+oy),dudx*sx*bias,-dvdx*sx*bias,dudy*sy*bias,-dvdy*sy*bias,4,out),"Texture lookup failed; invalidate whole epoch");
  surface::V3 c{out[0],out[1],out[2]};if(gamma&&file->eightBit){c={powf(std::max(c.x,0.f),2.2f),powf(std::max(c.y,0.f),2.2f),powf(std::max(c.z,0.f),2.2f)};}
  need(surface::finite(c)&&c.x>=0&&c.y>=0&&c.z>=0,"Invalid texture radiance");return c;
 }
};
}
