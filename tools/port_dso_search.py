"""MoonRay looking along PATH for itself as it starts, past entries that are files.

DsoFinder::guessDsoPath (scene_rdl2) looks through each PATH entry for moonray.exe to find a folder of scene classes
beside it. It checks only that an entry exists before reading it as a folder, so an entry that is a file (a tester's
PATH named c:\\Windows\\System32\\cmd.exe) stops MoonRay with "directory iterator cannot open directory: Not a
directory", before any preview or scene load. It compares each name without its extension with "moonray.exe", which
never matches on Windows, so it always goes through the whole of PATH. SceneContext::loadAllSceneClasses reads the
entries of RDL2_DSO_PATH the same way.

Only when MoonRay is started with MOONRAY_MODO_DSO_SEARCH=1 (the plugin's preference), entries that are not folders, or
cannot be read, are passed over, and moonray.exe is matched by its whole name, so the look stops at the first folder
holding it. Without the variable MoonRay is as its source has it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RDL2 = ROOT / 'upstream/openmoonray/moonray/scene_rdl2/lib/scene/rdl2'

SWITCH = '''
// Modo: PATH entries that are not folders passed over (tools/port_dso_search.py).
static bool
modoDsoSearch()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_DSO_SEARCH");
        return value && value[0] == '1';
    }();
    return on;
}

// Modo: whether a readable folder holds a file of this whole name, without throwing.
static bool
modoFolderHolds(const std::filesystem::path &folder, const std::string &name)
{
    std::error_code error;
    if (!std::filesystem::is_directory(folder, error)) {
        return false;
    }
    std::filesystem::directory_iterator entry(folder, std::filesystem::directory_options::skip_permission_denied, error);
    for (; !error && entry != std::filesystem::directory_iterator(); entry.increment(error)) {
        if (entry->path().filename().string() == name) {
            return true;
        }
    }
    return false;
}
'''

FINDER = (
    ('''using util::Args;
''', '''using util::Args;
''' + SWITCH),
    ('''        path = std::filesystem::path(pathEnv).make_preferred();

        if (std::filesystem::exists(path)) {
''', '''        path = std::filesystem::path(pathEnv).make_preferred();

        if (modoDsoSearch()) {
            pathFound = modoFolderHolds(path, sRaasRender);
        } else if (std::filesystem::exists(path)) {
'''),
    ('''            path = std::filesystem::path(pathEnv.substr(counter, found - counter)).make_preferred();
            if (std::filesystem::exists(path)) {
''', '''            path = std::filesystem::path(pathEnv.substr(counter, found - counter)).make_preferred();
            if (modoDsoSearch()) {
                pathFound = modoFolderHolds(path, sRaasRender);
            } else if (std::filesystem::exists(path)) {
'''),
)

CONTEXT = (
    ('''        std::filesystem::path p(directory);
        if (std::filesystem::exists(p)) {
''', '''        std::filesystem::path p(directory);
        // Modo: an entry that is not a readable folder passed over (tools/port_dso_search.py).
        static const bool modoDsoSearch = [] {
            const char *value = std::getenv("MOONRAY_MODO_DSO_SEARCH");
            return value && value[0] == '1';
        }();
        std::error_code modoError;
        if (modoDsoSearch && !std::filesystem::is_directory(p, modoError)) {
            // Nothing to read here.
        } else if (std::filesystem::exists(p)) {
'''),
)


def patch(path, changes, mark):
    raw = path.read_bytes().decode('utf-8')
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    if mark in text:
        print('already applied', path.name)
        return
    for old, new in changes:
        if text.count(old) != 1:
            raise SystemExit('%s: expected once, found %d: %s' % (path.name, text.count(old), old[:70]))
        text = text.replace(old, new)
    if '#include <cstdlib>' not in text:
        first = text.index('#include')
        text = text[:first] + '#include <cstdlib>\n' + text[first:]
    path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
    print('patched', path.name)


def main():
    patch(RDL2 / 'DsoFinder.cc', FINDER, 'modoFolderHolds')
    patch(RDL2 / 'SceneContext.cc', CONTEXT, 'MOONRAY_MODO_DSO_SEARCH')


if __name__ == '__main__':
    main()
