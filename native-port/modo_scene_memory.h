#pragma once
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <string>
#include <cstdint>
#include <cstring>
#include <stdexcept>
inline bool modoSceneMemory(const std::string& ref){return ref.rfind("modo-memory:",0)==0;}
inline std::string modoReadSceneMemory(const std::string& ref){
 const auto split=ref.find(':',12);
 if(!modoSceneMemory(ref) || split==std::string::npos)throw std::runtime_error("Invalid shared scene reference");
 const std::string count=ref.substr(12,split-12),name=ref.substr(split+1);
 if(count.empty() || count.find_first_not_of("0123456789")!=std::string::npos || name.rfind("Local\\MoonRayForModoScene_",0)!=0 || name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_\\")!=std::string::npos)throw std::runtime_error("Invalid shared scene name");
 const auto size=std::stoull(count);
 if(!size || size>256ull*1024*1024)throw std::runtime_error("Shared scene exceeds limit");
 HANDLE mapping=OpenFileMappingA(FILE_MAP_READ,FALSE,name.c_str());
 if(!mapping)throw std::runtime_error("Shared scene unavailable");
 void* data=MapViewOfFile(mapping,FILE_MAP_READ,0,0,size);
 if(!data){CloseHandle(mapping);throw std::runtime_error("Cannot map shared scene");}
 try{std::string result(static_cast<const char*>(data),size);UnmapViewOfFile(data);CloseHandle(mapping);return result;}
 catch(...){UnmapViewOfFile(data);CloseHandle(mapping);throw;}
}

class ModoSceneCommand {
 HANDLE mapping=nullptr,event=nullptr;const char* data=nullptr;
 public:
 explicit ModoSceneCommand(const char* name){
  if(!name)return;
  std::string value(name);
  if(value.rfind("Local\\MoonRayForModoCommand_",0)!=0)throw std::runtime_error("Invalid command mapping name");
  mapping=OpenFileMappingA(FILE_MAP_READ,FALSE,name);
  if(mapping)data=static_cast<const char*>(MapViewOfFile(mapping,FILE_MAP_READ,0,0,65536));
  event=OpenEventA(SYNCHRONIZE|EVENT_MODIFY_STATE,FALSE,(value+"_ready").c_str());
  if(!data || !event){if(data)UnmapViewOfFile(data);if(mapping)CloseHandle(mapping);if(event)CloseHandle(event);throw std::runtime_error("Cannot open scene command channel");}
 }
 ~ModoSceneCommand(){if(data)UnmapViewOfFile(data);if(mapping)CloseHandle(mapping);if(event)CloseHandle(event);}
 bool enabled() const{return event!=nullptr;}
 bool ready() const{return event && WaitForSingleObject(event,0)==WAIT_OBJECT_0;}
 std::string receive(){
  if(!ready())throw std::runtime_error("Scene command not ready");
  uint32_t size;memcpy(&size,data,4);
  if(!size || size>65532)throw std::runtime_error("Invalid scene command size");
  std::string text(data+4,size);ResetEvent(event);return text;
 }
};
