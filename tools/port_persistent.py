"""Add the opt-in persistent preview protocol to the native command-line driver."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
p=root/'upstream/openmoonray/moonray/moonray/cmd/raas_cmd/moonray/moonray.cc'
s=p.read_text(encoding='utf-8')
if 'void renderPersistent(' not in s:
    s=s.replace('    void run();','    void renderPersistent(const std::string& directory);\n    void run();')
    s=s.replace('void\nRaasCommandLineApplication::run()', '} // namespace moonray\n#include "persistent_session.inc"\nnamespace moonray {\n\nvoid\nRaasCommandLineApplication::run()')
    s=s.replace('    logInitMessages();', '    logInitMessages();\n    if (const char* session = std::getenv("MOONRAY_MODO_SESSION")) {\n        renderPersistent(session);\n        return;\n    }')
    p.write_bytes(s.encode('utf-8'))
print('Persistent preview protocol enabled in the native source')

# Read scene text from named memory with the same lifecycle as file updates.
p=root/'upstream/openmoonray/moonray/moonray/lib/rendering/rndr/RenderContext.cc'
s=p.read_text(encoding='utf-8')
if '#include "modo_scene_memory.h"' not in s:
    s='#include "modo_scene_memory.h"\n'+s
    old='        readSceneFromFile(filename, *mSceneContext);'
    assert old in s
    s=s.replace(old,'        if (modoSceneMemory(filename)) { scene_rdl2::rdl2::AsciiReader reader(*mSceneContext); reader.fromString(modoReadSceneMemory(filename)); }\n        else readSceneFromFile(filename, *mSceneContext);',1)
    old='    for (const auto& sceneFile : sceneFiles) {'
    assert old in s
    s=s.replace(old,old+'\n        if (modoSceneMemory(sceneFile)) { asciiReader.fromString(modoReadSceneMemory(sceneFile)); continue; }',1)
    p.write_bytes(s.encode('utf-8'))
