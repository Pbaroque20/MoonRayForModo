# ISPC generates Windows objects, but the host C++ toolchain uses GNU ar.
set(CMAKE_ISPC_CREATE_STATIC_LIBRARY "<CMAKE_AR> qc <TARGET> <LINK_FLAGS> <OBJECTS>")
set(CMAKE_ISPC_ARCHIVE_FINISH "<CMAKE_RANLIB> <TARGET>")
