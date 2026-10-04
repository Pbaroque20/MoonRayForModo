// Private binary pipe display worker. Keep OIIO/OCIO outside Modo's DLL namespace.
#include <OpenImageIO/imagebuf.h>
#include <OpenImageIO/imagebufalgo.h>
#include <OpenImageIO/color.h>
#include <iostream>
#include <sstream>
#include <vector>
#include <cmath>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <fcntl.h>
#include <io.h>
using namespace OIIO;
static bool readBytes(void* p,size_t n){return bool(std::cin.read(static_cast<char*>(p),n));}
int main(int argc,char** argv){
 _setmode(_fileno(stdin),_O_BINARY);_setmode(_fileno(stdout),_O_BINARY);
 if(argc!=12)return 2;
 const std::string kind=argv[1],view=argv[2],space=argv[4],lut=argv[5],placement=argv[6];
 const float gain=std::exp2(std::stof(argv[3]));
 float matrix[9];std::istringstream matrixInput(argv[11]);
 for(float& v:matrix)if(!(matrixInput>>v) || !std::isfinite(v))return 2;
 ColorConfig config(argv[7]);
 attribute("threads",2);
 for(;;){
  uint32_t header[3];if(!readBytes(header,sizeof(header)))return 0;
  try{
   uint32_t w=header[0],h=header[1],pathBytes=header[2];
   ImageBuf source;std::vector<float> rgb;
   if(pathBytes){
    if(pathBytes>32768 || w || h)throw std::runtime_error("Invalid file request");
    std::string path(pathBytes,'\0');if(!readBytes(path.data(),pathBytes))return 3;
    ImageBuf input(path);if(!input.init_spec(path,0,0))throw std::runtime_error(input.geterror());
    const auto spec=input.spec();w=spec.width;h=spec.height;
    if(!w || !h || uint64_t(w)*h>512*1024*1024/12 || spec.deep)throw std::runtime_error("Display image exceeds memory limit or is deep");
    if(uint64_t(w)*h*(kind=="cryptomatte"?spec.nchannels:std::min(3,spec.nchannels))>512*1024*1024/4)throw std::runtime_error("Display channels exceed memory limit");
    if(!input.read(0,0,0,(kind=="cryptomatte"?spec.nchannels:std::min(3,spec.nchannels)),true,TypeDesc::FLOAT))throw std::runtime_error(input.geterror());
    if(uint64_t(w)*h*input.nchannels()>512*1024*1024/4)throw std::runtime_error("Display channels exceed memory limit");
    std::vector<float> raw(size_t(w)*h*input.nchannels());
    if(!input.get_pixels(input.roi(),TypeDesc::FLOAT,raw.data()))throw std::runtime_error(input.geterror());
    rgb.resize(size_t(w)*h*3);
    if(kind=="cryptomatte") {
      std::vector<std::pair<int,int>> pairs;
      const auto& names=input.spec().channelnames;
      for(int c=0;c<input.nchannels();++c) {
        const auto& name=names[c];
        if(name.size()!=15 || name.compare(0,11,"Cryptomatte")!=0 || name[13]!='.')continue;
        if(name[14]!='R' && name[14]!='B')continue;
        std::string coverage=name;coverage[14]=name[14]=='R'?'G':'A';
        auto found=std::find(names.begin(),names.end(),coverage);
        if(found!=names.end())pairs.emplace_back(c,int(found-names.begin()));
      }
      if(pairs.empty())throw std::runtime_error("No Cryptomatte ID/coverage channel pairs found");
      for(size_t i=0;i<size_t(w)*h;++i)for(const auto& pair:pairs) {
        float id=raw[i*input.nchannels()+pair.first],coverage=raw[i*input.nchannels()+pair.second];
        if(id==0 || !std::isfinite(coverage) || coverage<=0)continue;
        uint32_t bits;std::memcpy(&bits,&id,sizeof(bits));
        bits^=bits>>16;bits*=0x7feb352du;bits^=bits>>15;bits*=0x846ca68bu;bits^=bits>>16;
        for(int c=0;c<3;++c)rgb[i*3+c]+=std::clamp(coverage,0.f,1.f)*(.2f+.8f*((bits>>(8*c))&255)/255.f);
      }
    } else {
      for(size_t i=0;i<size_t(w)*h;++i)for(int c=0;c<3;++c)
        rgb[i*3+c]=raw[i*input.nchannels()+std::min(c,input.nchannels()-1)];
    }
   }else{
    if(!w || !h || uint64_t(w)*h>64*1024*1024/12)throw std::runtime_error("Invalid pixel dimensions");
    rgb.resize(size_t(w)*h*3);std::vector<float> row(size_t(w)*3);
    for(unsigned y=0;y<h;++y){if(!readBytes(row.data(),row.size()*4))return 3;
     std::copy(row.begin(),row.end(),rgb.begin()+size_t(h-1-y)*w*3);}
   }
   for(float& v:rgb)if(!std::isfinite(v))v=0;
   const bool color=!(kind=="cryptomatte" || kind=="normal" || kind=="geometric_normal" || kind=="alpha" || kind=="wireframe" || kind=="depth" || kind=="sample_count" || kind=="uv" || kind=="motion" || kind=="position");
   for(size_t i=0;i<rgb.size();i+=3){
    float* v=rgb.data()+i;
    if(kind=="alpha" || kind=="wireframe" || kind=="depth" || kind=="sample_count")v[1]=v[2]=v[0];
    if(kind=="uv" || kind=="motion")v[2]=0;
    if(color){
     if(space=="acescg" && view!="raw" && view!="ocio"){
      const float a=v[0],b=v[1],c=v[2];
      v[0]=matrix[0]*a+matrix[1]*b+matrix[2]*c;
      v[1]=matrix[3]*a+matrix[4]*b+matrix[5]*c;
      v[2]=matrix[6]*a+matrix[7]*b+matrix[8]*c;
     }
     for(int c=0;c<3;++c)v[c]*=gain;
    }
   }
   source=ImageBuf(ImageSpec(w,h,3,TypeDesc::FLOAT),rgb.data());
   auto check=[&](bool ok){if(!ok)throw std::runtime_error(source.geterror());};
   if(kind=="depth" || kind=="sample_count" || kind=="position")check(ImageBufAlgo::rangecompress(source,source));
   if(kind=="normal" || kind=="geometric_normal" || kind=="motion" || kind=="position"){
    check(ImageBufAlgo::mul(source,source,0.5f));check(ImageBufAlgo::add(source,source,0.5f));
   }
   if(color){
    if(!lut.empty() && placement=="linear")check(ImageBufAlgo::ociofiletransform(source,source,lut,false,false,&config));
    if(view=="reinhard"){
     for(ImageBuf::Iterator<float> p(source);!p.done();++p)for(int c=0;c<3;++c){float v=std::max(0.f,float(p[c]));p[c]=v/(1.f+v);}
    }
    if(view=="srgb" || view=="reinhard")check(ImageBufAlgo::colorconvert(source,source,"linear","sRGB",false));
    else if(view=="ocio")check(ImageBufAlgo::ociodisplay(source,source,argv[9],argv[10],argv[8],"",false,false,"","",&config));
    if(!lut.empty() && placement=="display")check(ImageBufAlgo::ociofiletransform(source,source,lut,false,false,&config));
   }
   std::vector<unsigned char> result(size_t(w)*h*4);size_t i=0;
   for(ImageBuf::ConstIterator<float> p(source);!p.done();++p){
    for(int c=0;c<3;++c)result[i++]=static_cast<unsigned char>(std::clamp(std::isfinite(p[c])?p[c]:0.f,0.f,1.f)*255.f+.5f);
    result[i++]=255;
   }
   uint32_t response[]={1,w,h};std::cout.write(reinterpret_cast<char*>(response),sizeof(response));
   std::cout.write(reinterpret_cast<char*>(result.data()),result.size());std::cout.flush();
  }catch(const std::exception& e){
   std::string error=e.what();if(error.empty())error="Image transform failed";
   if(error.size()>4096)error.resize(4096);
   uint32_t response[]={0,uint32_t(error.size()),0};std::cout.write(reinterpret_cast<char*>(response),sizeof(response));std::cout.write(error.data(),error.size());std::cout.flush();return 4;
  }
 }
}
