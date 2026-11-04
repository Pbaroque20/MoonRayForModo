"""A mesh its placement mirrors (a negative scale), with normals of its own, renders black.

MoonRay bakes a mesh's node_xform into its vertices with the faces' order kept, so a mirror turns every face's winding
over: the geometric normal (Embree's, from the winding) then points inward. The mesh's own normals go through the inverse
transpose and keep pointing out. At a hit the two disagree; MoonRay turns both toward the side the ray came from by the
geometric one, and the shading normal ends up facing away from the camera: black. Without normals of its own the mesh is
right, its normals made from the same turned-over winding. A tester's Modo scenes with mirrored meshes rendered black.

Only when MoonRay is started with MOONRAY_MODO_MIRRORED_MESHES=1 (the plugin's preference), PolyMesh and OpenSubdivMesh
reverse the orientation of a mirrored mesh as they tessellate (reverseOrientation, which reverse_normals uses), so its
winding is outward again; a mesh both mirrored and set to reverse_normals is not reversed. Its own normals are negated
for reverse_normals alone, as before; smooth normals PolyMesh makes from a mirrored mesh's faces (before the reversal) are
negated as they are made. Measured on a cube: mirrored with normals 0.0 (black) and without 32.5, against 62.0 and 42.4
for the same cube unmirrored; 62.0 and 42.4 with the switch. Without the variable MoonRay is as its source has it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIM = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/geom/prim'

HELPER = '''
namespace {
// Modo: a mesh its placement mirrors (tools/port_mirrored_meshes.py): its winding is turned over by the mirror, its own
// normals are not. Only with MOONRAY_MODO_MIRRORED_MESHES=1.
bool modoMirrored(const moonray::shading::XformSamples& xforms)
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_MIRRORED_MESHES");
        return value && value[0] == '1';
    }();
    return on && !xforms.empty() && xforms[0].l.det() < 0.0f;
}
} // namespace
'''

POLY_OLD = '''    // reverse normals reverses orientation and negates normals
    if (mIsNormalReversed) {
        size_t faceVertexCount = mIsTessellated ?
'''
POLY_NEW = '''    // reverse normals reverses orientation and negates normals
    // Modo: so does a mirror, by its own (tools/port_mirrored_meshes.py); the two together cancel.
    if (mIsNormalReversed != modoMirror) {
        size_t faceVertexCount = mIsTessellated ?
'''
# The mirror asked before initAttributesAndDisplace lets the mesh's data (its transforms) go.
CALL_OLD = '''    }

    initAttributesAndDisplace(pRdlLayer,
                              baseFaceCount,'''
CALL_NEW = '''    }

    // Modo: whether the placement mirrors the mesh, asked before initAttributesAndDisplace lets its data go.
    const bool modoMirror = modoMirrored(mPolyMeshData->mXforms);
    initAttributesAndDisplace(pRdlLayer,
                              baseFaceCount,'''
# Smooth normals made from the faces (before the reversal, after a displacement) turned over with a mirror.
SMOOTH_OLD = '''    // if it's not real time mode, we don't need the smooth normal utility
    // after shading normal computation is done
    if (!realtimeMode) {'''
SMOOTH_NEW = '''    // Modo: smooth normals made from a mirrored mesh's faces turned over with them (its own do not); tessellate then
    // reverses its orientation (tools/port_mirrored_meshes.py).
    if (calculateSmoothNormal && modoMirrored(mPolyMeshData->mXforms)) {
        getAttributes()->negateNormal();
    }

    // if it's not real time mode, we don't need the smooth normal utility
    // after shading normal computation is done
    if (!realtimeMode) {'''
SUBD_OLD = '''    // reverse normals reverses orientation and negates normals
    if (mIsNormalReversed) {
        reverseOrientation(mControlMeshData->mFaceVertexCount,
'''
SUBD_NEW = '''    // reverse normals reverses orientation and negates normals
    // Modo: so does a mirror, by its own (tools/port_mirrored_meshes.py); the two together cancel.
    if (mIsNormalReversed != modoMirrored(mControlMeshData->mXforms)) {
        reverseOrientation(mControlMeshData->mFaceVertexCount,
'''


def main():
    for name, changes in (('PolyMesh.cc', ((CALL_OLD, CALL_NEW), (POLY_OLD, POLY_NEW), (SMOOTH_OLD, SMOOTH_NEW))), ('OpenSubdivMesh.cc', ((SUBD_OLD, SUBD_NEW),))):
        path = PRIM / name
        raw = path.read_bytes().decode('utf-8')
        crlf = '\r\n' in raw
        text = raw.replace('\r\n', '\n')
        if 'modoMirrored' in text:
            print('already applied', name)
            continue
        for old, new in changes:
            if text.count(old) != 1:
                raise SystemExit('%s: expected once, found %d: %s' % (name, text.count(old), old[:70]))
            text = text.replace(old, new)
        # The helper after the includes, before the file's first namespace.
        at = text.index('\nnamespace moonray')
        text = text[:at] + '\n' + HELPER + text[at:]
        if '#include <cstdlib>' not in text:
            first = text.index('#include')
            text = text[:first] + '#include <cstdlib>\n' + text[first:]
        path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
        print('patched', name)


if __name__ == '__main__':
    main()
