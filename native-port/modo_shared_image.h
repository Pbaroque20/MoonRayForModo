#pragma once
#include "modo_protocol_line.h"
#include <windows.h>
#include <cstdint>
#include <string>
#include <iostream>
// A picture of any size is handed over whole: there is no limit to its bytes (it was 64 MB, so a 4K picture, 99.5 MB,
// was not handed over at all and the preview stayed black until the render was done). The kit takes any size too
// (shared_image.py, modo_display.cpp, modo_display_stream.cpp).
// A single publication remains mapped until the consumer acknowledges it.
// The bounded mailbox drops snapshots rather than blocking the render thread.
// Once acknowledged, the same mapping takes the next picture of its size (written in place, announced again under its
// name): a new mapping each picture made its pages anew, about 4 ms of a 640 x 360 picture's hand-over, more at 4K, and
// realtime shows several pictures a camera move. The consumer reads a publication whole before it acknowledges it
// (shared_image.py), so nothing it reads is written over. One withdrawn (not taken in five seconds) is never written
// again: the next picture is a new mapping.
class ModoSharedImage {
    HANDLE mapping=nullptr,ack=nullptr;
    void* pixels=nullptr;
    unsigned serial=0;
    ULONGLONG publishedAt=0;
    size_t mappedBytes=0;
    std::string name;
    void clear() { if(pixels)UnmapViewOfFile(pixels);if(mapping)CloseHandle(mapping);if(ack)CloseHandle(ack);pixels=nullptr;mapping=ack=nullptr;mappedBytes=0; }
    bool taken() const { return mapping && WaitForSingleObject(ack,0)==WAIT_OBJECT_0; }
public:
    ~ModoSharedImage(){clear();}
    bool ready(){return !mapping || taken() || GetTickCount64()-publishedAt>=5000;}
    // The last picture handed over (its mapping, rgb floats; null: none), until the next is written: what is on screen.
    const float* picture() const { return static_cast<const float*>(pixels); }
    size_t pictureBytes() const { return pixels ? mappedBytes : 0; }
    template<class Sample>
    bool publish(const std::string& generation,const std::string& key,unsigned width,unsigned height,Sample sample) {
        if(!width || !height || !ready())return false;
        const size_t count=size_t(width)*height,bytes=count*3*sizeof(float);
        if(taken() && bytes==mappedBytes) {
            // The last picture taken: this one in its place.
            ResetEvent(ack);
        } else {
            clear();
            name="Local\\MoonRayForModo_"+std::to_string(GetCurrentProcessId())+"_"+std::to_string(++serial);
            ack=CreateEventA(nullptr,TRUE,FALSE,(name+"_ack").c_str());
            // The size in its two 32-bit halves: a picture past 4 GB is mapped whole too.
            mapping=CreateFileMappingA(INVALID_HANDLE_VALUE,nullptr,PAGE_READWRITE,DWORD(uint64_t(bytes)>>32),DWORD(bytes),name.c_str());
            if(!ack || !mapping){clear();return false;}
            pixels=MapViewOfFile(mapping,FILE_MAP_WRITE,0,0,bytes);
            if(!pixels){clear();return false;}
            mappedBytes=bytes;
        }
        float* destination=static_cast<float*>(pixels);
        for(size_t i=0;i<count;++i)sample(i,destination+i*3);
        publishedAt=GetTickCount64();
        MemoryBarrier();
        modoProtocolLine("@@MODO_SHARED " + generation + " " + key + " " + std::to_string(width) + " " + std::to_string(height) + " " + name);
        return true;
    }
};
