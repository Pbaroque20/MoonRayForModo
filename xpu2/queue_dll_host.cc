// Loader owns module lifetime; no queue work is performed from DllMain.
#include <windows.h>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
static void require(bool ok,const char* what){if(!ok)throw std::runtime_error(what);}
int main(int argc,char** argv) {
    try {
        require(argc==6,"dll scenario capture output loads required");
        const int loads=std::stoi(argv[5]);require(loads>0 && loads<=8,"Invalid cycle count");
        for(int i=0;i<loads;++i) {
            const auto folder=std::string(argv[4])+"/load-"+std::to_string(i);
            require(CreateDirectoryA(folder.c_str(),nullptr)!=0,"Fresh output directory required");
            require(!_putenv_s("XPU2_QUEUE_LOG",(folder+"/queue.log").c_str()),"Queue log environment failed");
            require(!_putenv_s("XPU2_NATIVE_LAMBERT_LOG",(folder+"/shading.log").c_str()),"Shader log environment failed");
            require(!_putenv_s("XPU2_NATIVE_LAMBERT_RECORDS",(folder+"/shading.bin").c_str()),"Capture environment failed");
            require(GetModuleHandleA(argv[1])==nullptr,"Probe DLL already loaded before cycle");
            HMODULE library=LoadLibraryExA(argv[1],nullptr,LOAD_WITH_ALTERED_SEARCH_PATH);
            require(library!=nullptr,"Load probe DLL failed");
            require(GetModuleHandleA(argv[1])==library,"Loaded module identity lookup failed");
            auto run=reinterpret_cast<int(*)(const char*,const char*)>(GetProcAddress(library,"xpu2QueueRun"));
            require(run!=nullptr,"Missing probe entry point");
            require(run(argv[2],argv[3])==0,"Queue scenario failed; module intentionally retained");
            // The scenario has stopped/joined every worker and deleted all owners.
            require(FreeLibrary(library)!=0,"FreeLibrary failed");
            require(GetModuleHandleA(argv[1])==nullptr,"Probe DLL remained loaded after release");
            Sleep(20); // Allow stray work to surface before reload; not a latency measurement.
        }
        std::cout<<"{\"loader\":true,\"loads\":"<<loads<<",\"unloads\":"<<loads<<",\"passed\":true}\n";
        return 0;
    } catch(const std::exception& e){std::cerr<<e.what()<<" (Windows error "<<GetLastError()<<")\n";return 1;}
}
