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
