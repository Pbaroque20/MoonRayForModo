#pragma once
#include <windows.h>
#include <string>
#include <iostream>
// A single immutable publication remains mapped until the consumer acknowledges it.
// The bounded mailbox drops snapshots rather than blocking the render thread.
class ModoSharedImage {
    HANDLE mapping=nullptr,ack=nullptr;
    void* pixels=nullptr;
    unsigned serial=0;
    ULONGLONG publishedAt=0;
    void clear() { if(pixels)UnmapViewOfFile(pixels);if(mapping)CloseHandle(mapping);if(ack)CloseHandle(ack);pixels=nullptr;mapping=ack=nullptr; }
public:
    ~ModoSharedImage(){clear();}
    bool ready(){if(!mapping)return true;if(WaitForSingleObject(ack,0)!=WAIT_OBJECT_0 && GetTickCount64()-publishedAt<5000)return false;clear();return true;}
    template<class Sample>
    bool publish(const std::string& generation,const std::string& key,unsigned width,unsigned height,Sample sample) {
        const size_t count=size_t(width)*height,bytes=count*3*sizeof(float);
        if(!width || !height || bytes>64*1024*1024 || !ready())return false;
        std::string name="Local\\MoonRayForModo_"+std::to_string(GetCurrentProcessId())+"_"+std::to_string(++serial);
        ack=CreateEventA(nullptr,TRUE,FALSE,(name+"_ack").c_str());
        mapping=CreateFileMappingA(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,0,DWORD(bytes),name.c_str());
        if(!ack || !mapping){clear();return false;}
        pixels=MapViewOfFile(mapping,FILE_MAP_WRITE,0,0,bytes);
        if(!pixels){clear();return false;}
        float* destination=static_cast<float*>(pixels);
        for(size_t i=0;i<count;++i)sample(i,destination+i*3);
        publishedAt=GetTickCount64();
        MemoryBarrier();
        std::cout << "\n@@MODO_SHARED " << generation << " " << key << " " << width << " " << height << " " << name << std::endl;
        return true;
    }
};
