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
#include <atomic>
#include <mutex>
#include <deque>
#include <thread>
#include <chrono>
#include <cstdio>
#include <psapi.h>
#include <OpenImageIO/imagecache.h>
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
// Whether an 8-bit value can be kept as its byte: OpenImageIO's conversion of each of the 256 to float is the byte times
// 1/255 (tex::texel's decoding), and 0 and 1 (a missing channel's fill) are bytes 0 and 255. Checked once.
inline bool bytesExact(){static const bool exact=[]{unsigned char in[256];float out[256];for(int i=0;i<256;++i)in[i]=(unsigned char)i;
  if(!OIIO::convert_pixel_values(OIIO::TypeDesc::UINT8,in,OIIO::TypeDesc::FLOAT,out,256))return false;
  for(int i=0;i<256;++i)if(out[i]!=float(i)*(1.0f/255.0f))return false;return 255.0f*(1.0f/255.0f)==1.0f;}();return exact;}
// The image cache the finest levels' tiles are read through (thread-safe; half a gigabyte of the files' own tiles).
inline std::shared_ptr<OIIO::ImageCache> lazyCache(){static std::shared_ptr<OIIO::ImageCache> c=[]{auto s=OIIO::ImageCache::create(true);
  s->attribute("max_memory_MB",512.0f);return s;}();return c;}
// Whether the finest level is read when first used (XPU2_SESSION_EAGER_TEXTURES=1: every level decoded at once).
inline bool lazyTextures(){static const bool on=[]{const char* v=std::getenv("XPU2_SESSION_EAGER_TEXTURES");return !(v&&v[0]=='1');}();return on;}
// Texture overflow mode: the largest side a texture has for the rest of the session (0: as stored), where a scene's load ran
// out of memory on the machine or the card: finer levels are neither decoded nor sent. The session halves it until the
// scene loads (nextOverflowSide) and says so in the preview.
inline std::atomic<unsigned>& overflowSide(){static std::atomic<unsigned> side{0};return side;}
inline std::atomic<unsigned>& largestTexture(){static std::atomic<unsigned> side{0};return side;}
constexpr unsigned SmallestOverflowSide=256;
inline bool nextOverflowSide(){
 const unsigned now=overflowSide().load(),from=now?now:largestTexture().load();
 if(from<=SmallestOverflowSide)return false;
 unsigned next=SmallestOverflowSide;while(next*2<from)next*=2;
 overflowSide().store(next);return true;}
inline bool canOverflow(){const unsigned now=overflowSide().load();return (now?now:largestTexture().load())>SmallestOverflowSide;}
// Set by the pressure watch where tiles were let go, all of them, and memory did not come back (RAM still short).
inline std::atomic<bool>& pressureShort(){static std::atomic<bool> s{false};return s;}
struct Pyramid;
// Every texture whose tiles can be let go; a list never freed, as the pressure watch outlives what ends at exit.
inline std::mutex& spillLock(){static auto* m=new std::mutex;return *m;}
inline std::vector<Pyramid*>& spillList(){static auto* l=new std::vector<Pyramid*>;return *l;}
struct Pyramid {
 tex::Image image;std::vector<std::vector<surface::V3>> tiles;
 // An 8-bit file's tiles as bytes (tex::Mip::format 1); XPU2_SESSION_FLOAT_TEXTURES=1 keeps every file in floats.
 std::vector<std::vector<unsigned char>> byteTiles;
 std::vector<std::vector<const surface::V3*>> pages;std::atomic<uint64_t> bytes{0};
 // The finest level on demand (lazyTextures): its tiles decoded when first read (loadTile), each into a block of its own.
 std::string file;int channels=0,alphaChannel=-1,fileBase=0;bool alphaOnly=false,lazyEight=false;std::mutex lazyLock;
 // Loaded tiles, oldest first: under memory pressure the oldest are let go (letGo), and read again if asked for again.
 struct LazyTile {std::unique_ptr<unsigned char[]> block;unsigned level,tile;size_t size;};
 std::deque<LazyTile> lazyTiles;size_t lazyBytes=0;std::atomic<unsigned> lazyLoaded{0};
 // One texel of the file as kept (channels mapped, alpha as colour), into a float tile or three bytes.
 void keep(const float* d,surface::V3* toFloat,unsigned char* toBytes){surface::V3 c;float a;texelChannels(d,channels,alphaChannel,c,a);if(alphaOnly)c={a,a,a};
  if(toBytes){const float v[3]={c.x,c.y,c.z};for(int k=0;k<3;++k){const long b=std::lround(v[k]*255.0f);need(b>=0&&b<=255&&float(b)*(1.0f/255.0f)==v[k],"8-bit texel not its byte");toBytes[k]=(unsigned char)b;}}
  else{need(surface::finite(c),"Invalid TX sample");*toFloat=c;}}
 // A finest-level tile decoded now (tex::Mip::load): the same values the whole level gave, through OIIO's conversion.
 static void loadTile(const void* self,unsigned level,unsigned tile){auto* p=const_cast<Pyramid*>(static_cast<const Pyramid*>(self));
  // Decoded outside the lock (tiles of one texture decode side by side); the first to finish publishes its page.
  auto& page=p->pages[level][tile];if(page)return;
  const tex::Mip& m=p->image.levels[level];const unsigned nx=(m.width+tex::Tile-1)/tex::Tile,tx=tile%nx,ty=tile/nx;
  const unsigned tw=std::min(tex::Tile,m.width-tx*tex::Tile),th=std::min(tex::Tile,m.height-ty*tex::Tile);
  std::vector<float> decoded(size_t(tw)*th*p->channels);
  need(lazyCache()->get_pixels(OIIO::ustring(p->file),0,int(level)+p->fileBase,int(tx*tex::Tile),int(tx*tex::Tile+tw),int(ty*tex::Tile),int(ty*tex::Tile+th),0,1,
                               OIIO::TypeDesc::FLOAT,decoded.data()),"Texture tile read");
  const size_t size=size_t(tw)*th*(p->lazyEight?3u:unsigned(sizeof(surface::V3)));
  std::unique_ptr<unsigned char[]> block(new unsigned char[size]);
  for(unsigned j=0;j<th;++j)for(unsigned i=0;i<tw;++i){const size_t at=size_t(j)*tw+i;
   p->keep(&decoded[at*p->channels],p->lazyEight?nullptr:reinterpret_cast<surface::V3*>(block.get())+at,p->lazyEight?block.get()+3*at:nullptr);}
  std::lock_guard<std::mutex> g(p->lazyLock);if(page)return;
  std::atomic_thread_fence(std::memory_order_release);
  page=reinterpret_cast<const surface::V3*>(block.get());p->lazyTiles.push_back({std::move(block),level,tile,size});p->lazyBytes+=size;p->bytes+=size;p->lazyLoaded++;}
 size_t lazyHeld(){std::lock_guard<std::mutex> g(lazyLock);return lazyBytes;}
 // The oldest tiles, up to want bytes: their pages cleared, their blocks handed over to free once no reader has them.
 size_t letGo(size_t want,std::vector<std::unique_ptr<unsigned char[]>>& out){
  std::lock_guard<std::mutex> g(lazyLock);size_t freed=0;
  while(freed<want&&!lazyTiles.empty()){auto& t=lazyTiles.front();pages[t.level][t.tile]=nullptr;freed+=t.size;out.push_back(std::move(t.block));lazyTiles.pop_front();lazyLoaded--;}
  lazyBytes-=freed;bytes-=freed;return freed;}
 ~Pyramid();
 Pyramid(const Pyramid&)=delete;
 explicit Pyramid(const std::string& name,bool alpha=false):file(name),alphaOnly(alpha){auto in=OIIO::ImageInput::open(name);need(bool(in),"Pyramid read");pages.reserve(tex::MaxLevels);
  for(unsigned level=0;level<tex::MaxLevels&&in->seek_subimage(0,level);++level){auto spec=in->spec();need(spec.get_int_attribute("sampleborder",0)==0&&spec.get_int_attribute("oiio:sampleborder",0)==0,"Border-sampled TX unsupported");
   unsigned w=spec.width,h=spec.height,nx=(w+tex::Tile-1)/tex::Tile,ny=(h+tex::Tile-1)/tex::Tile;
   // Texture overflow mode: the levels over its side left out, the first one under it this pyramid's finest.
   if(const unsigned side=overflowSide().load();side&&std::max(w,h)>side&&!image.count){fileBase=int(level)+1;continue;}
   static const bool floats=[]{const char* v=std::getenv("XPU2_SESSION_FLOAT_TEXTURES");return v&&v[0]=='1';}();
   const bool eight=spec.format==OIIO::TypeDesc::UINT8&&bytesExact()&&!floats;
   channels=spec.nchannels;alphaChannel=spec.alpha_channel;
   if(!image.count&&lazyTextures()&&spec.tile_width>0){
    // The finest level read when first used (loadTile): its pages empty for now.
    lazyEight=eight;pages.emplace_back(size_t(nx)*ny,nullptr);
    image.levels[image.count]={w,h,pages.back().data(),0,eight?1u:0u,&Pyramid::loadTile,this};++image.count;continue;}
   std::vector<float> decoded(size_t(w)*h*spec.nchannels);
   need(in->read_image(0,int(level),0,spec.nchannels,OIIO::TypeDesc::FLOAT,decoded.data()),"Stored mip decode");pages.emplace_back(nx*ny,nullptr);auto& page=pages.back();
   for(unsigned y=0;y<ny;++y)for(unsigned x=0;x<nx;++x){unsigned tw=std::min(tex::Tile,w-x*tex::Tile),th=std::min(tex::Tile,h-y*tex::Tile);
    if(eight){
     // Three bytes a texel: each value's byte again (an 8-bit file's values are its bytes times 1/255, its fill 0 or 1).
     byteTiles.emplace_back(size_t(tw)*th*3);auto& tile=byteTiles.back();
     for(unsigned j=0;j<th;++j)for(unsigned i=0;i<tw;++i){size_t idx=(size_t(y*tex::Tile+j)*w+x*tex::Tile+i)*spec.nchannels;surface::V3 c;float a;
      texelChannels(&decoded[idx],spec.nchannels,spec.alpha_channel,c,a);if(alpha)c={a,a,a};
      unsigned char* to=&tile[size_t(j*tw+i)*3];const float v[3]={c.x,c.y,c.z};
      for(int k=0;k<3;++k){const long b=std::lround(v[k]*255.0f);need(b>=0&&b<=255&&float(b)*(1.0f/255.0f)==v[k],"8-bit texel not its byte");to[k]=(unsigned char)b;}}
     page[y*nx+x]=reinterpret_cast<const surface::V3*>(tile.data());bytes+=tile.size();continue;}
    tiles.emplace_back(tw*th);auto& tile=tiles.back();
    for(unsigned j=0;j<th;++j)for(unsigned i=0;i<tw;++i){size_t idx=(size_t(y*tex::Tile+j)*w+x*tex::Tile+i)*spec.nchannels;surface::V3 c;float a;
     texelChannels(&decoded[idx],spec.nchannels,spec.alpha_channel,c,a);
     // Negative values are kept, as MoonRay's texture sampler keeps them (a signed displacement or vector map).
     if(alpha)c={a,a,a};need(surface::finite(c),"Invalid TX sample");tile[j*tw+i]=c;}
    page[y*nx+x]=tile.data();bytes+=tile.size()*sizeof(surface::V3);
   }image.levels[image.count]={w,h,page.data(),0,eight?1u:0u};++image.count;
  }need(image.count&&image.levels[image.count-1].width==1&&image.levels[image.count-1].height==1,"Software mip level bound");
  // Realtime's view: the pyramid from its first level no wider or taller than realtimeSide() on.
  const unsigned side=realtimeSide();
  while(side&&realtimeFrom+1<image.count&&std::max(image.levels[realtimeFrom].width,image.levels[realtimeFrom].height)>side)++realtimeFrom;
  realtimeImage.count=image.count-realtimeFrom;
  for(unsigned k=0;k<realtimeImage.count;++k)realtimeImage.levels[k]=image.levels[realtimeFrom+k];
  std::lock_guard<std::mutex> listed(spillLock());spillList().push_back(this);
 }
 // The largest side a texture has in realtime's frames (XPU2_SESSION_RT_TEXTURE_SIDE, default 1024, was 1280; 0: as rendered).
 // Perceptually enough at realtime's sizes, and its finer levels are then never decoded nor sent to the card.
 static unsigned realtimeSide(){static const unsigned side=[]{const char* v=std::getenv("XPU2_SESSION_RT_TEXTURE_SIDE");
   return v?unsigned(std::max(0,std::atoi(v))):1024u;}();return side;}
 tex::Image realtimeImage;unsigned realtimeFrom=0;
 // The pyramid a plan reads: realtime's from its first level of realtimeSide() or less, else the whole.
 const tex::Image& view(bool realtime)const{return realtime&&realtimeFrom?realtimeImage:image;}
};
inline Pyramid::~Pyramid(){std::lock_guard<std::mutex> listed(spillLock());auto& l=spillList();l.erase(std::remove(l.begin(),l.end(),this),l.end());}
// The decoded tiles held now, in bytes.
inline size_t tilesHeld(){std::lock_guard<std::mutex> listed(spillLock());size_t n=0;for(auto* p:spillList())n+=p->lazyHeld();return n;}
// Lets go of up to want bytes of decoded tiles, each texture's oldest, in proportion to what it holds, and returns what
// went. A tile asked for again is decoded again from its file (the disk is its record; the card's copy, where it has
// one, stays). Freed once every reader that may have seen one has left it (tex::spill).
inline size_t relieve(size_t want){
 std::vector<std::unique_ptr<unsigned char[]>> grave;size_t freed=0;
 {std::lock_guard<std::mutex> listed(spillLock());size_t held=0;for(auto* p:spillList())held+=p->lazyHeld();if(!held)return 0;
  for(auto* p:spillList()){const size_t mine=p->lazyHeld();if(mine)freed+=p->letGo(size_t(double(want)*double(mine)/double(held))+1,grave);}}
 if(grave.empty())return 0;
 std::atomic_thread_fence(std::memory_order_seq_cst);
 const unsigned long long stamp=tex::spill::epoch.fetch_add(1,std::memory_order_seq_cst);
 for(auto& r:tex::spill::readers){for(;;std::this_thread::yield()){const auto in=r.in.load(std::memory_order_seq_cst);if(!in||in>stamp)break;}}
 grave.clear();HeapCompact(GetProcessHeap(),0);return freed;
}
// What memory pressure asks to be let go now, in bytes: the machine's free RAM below its reserve (a tenth of it, 2 GB at
// least), or the session's committed memory past 85% of its ceiling (ceiling 0: none); XPU2_SESSION_SPILL_MB holds the
// tiles to that many MB whatever the machine has.
inline size_t pressure(size_t ceiling){
 if(const char* v=std::getenv("XPU2_SESSION_SPILL_MB")){const size_t cap=size_t(std::max(0,std::atoi(v)))<<20,held=tilesHeld();return held>cap?held-cap:0;}
 size_t want=0;MEMORYSTATUSEX status{};status.dwLength=sizeof status;
 if(GlobalMemoryStatusEx(&status)){const size_t reserve=std::max<size_t>(size_t(status.ullTotalPhys/10),2ull<<30);
  if(status.ullAvailPhys<reserve)want=reserve-size_t(status.ullAvailPhys);}
 PROCESS_MEMORY_COUNTERS_EX c{};c.cb=sizeof c;
 if(ceiling&&K32GetProcessMemoryInfo(GetCurrentProcess(),reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&c),sizeof c)&&c.PrivateUsage>ceiling/100*85)
  want=std::max(want,size_t(c.PrivateUsage)-ceiling/100*80);
 return want;
}
// Watches for memory pressure for the rest of the process, four times a second, and says when it lets tiles go. A session
// past its ceiling used to go back to MoonRay XPU, and a machine out of RAM stalled, with tiles on hand it could read again.
inline void watchPressure(size_t ceiling){
 std::thread([ceiling]{
  auto said=std::chrono::steady_clock::now()-std::chrono::seconds(60),last=said;size_t since=0;
  for(;;std::this_thread::sleep_for(std::chrono::milliseconds(250))){
   const size_t want=pressure(ceiling);if(!want)continue;
   // Memory low for long (other applications'): tiles let go every quarter of a second would be read again as often.
   const auto now=std::chrono::steady_clock::now();
   if(now-last<std::chrono::seconds(2)&&!std::getenv("XPU2_SESSION_SPILL_MB"))continue;
   last=now;
   const size_t freed=relieve(want);since+=freed;
   if(freed&&!tilesHeld())pressureShort().store(true);
   if(since&&now-said>std::chrono::seconds(5)){std::printf("MoonRay XPU2: memory pressure: %zu MB of decoded texture tiles let go, %zu MB kept\n",since>>20,tilesHeld()>>20);std::fflush(stdout);said=now;since=0;}
  }}).detach();
}
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
    w=spec.width;h=spec.height;if(level==0){unsigned seen=largestTexture().load();while(unsigned(std::max(w,h))>seen&&!largestTexture().compare_exchange_weak(seen,unsigned(std::max(w,h)))){}}
    if(const unsigned side=overflowSide().load();!side||unsigned(std::max(w,h))<=side)decodedBytes+=uint64_t(w)*h*spec.nchannels*4;
    need(decodedBytes<=(2ull<<30),"Decoded texture budget");++levels;
   }need(levels>0&&w==1&&h==1,"Complete stored mip pyramid required");need(!in->seek_subimage(1,0),"Multipart texture unsupported");
   OIIO::ImageSpec spec;need(system->get_imagespec(name,spec),"OIIO texture admission failed");
  }catch(...){CloseHandle(lock);lock=INVALID_HANDLE_VALUE;throw;}
 }
 ~File(){if(lock!=INVALID_HANDLE_VALUE)CloseHandle(lock);}File(const File&)=delete;
};
struct Binding {
 std::shared_ptr<File> file;float sx=1,sy=1,ox=0,oy=0,mipBias=0;bool wrap=true,gamma=false;
 tex::Binding descriptor(bool realtime=false)const{return {file->pyramid?&file->pyramid->view(realtime):nullptr,sx,sy,ox,oy,mipBias,wrap?1u:0u,gamma&&file->eightBit?1u:0u};}
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
