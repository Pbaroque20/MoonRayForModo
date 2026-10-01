// SDK lifecycle only. Geometry exports live in render_cache.cpp.
// Deliberately registers no ExternalRender server and starts no PView worker.
#include <lx_plugin.hpp>
void initialize() {}
void cleanup() {}
