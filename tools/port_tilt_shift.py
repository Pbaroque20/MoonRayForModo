"""A tilt-shift camera for MoonRay: TiltShiftCamera, a perspective camera whose lens can be tilted and shifted.

MoonRay has no tilt-shift camera. Its PerspectiveCamera focuses on a plane square to the view, dof_focus_distance away.
A tilt-shift lens tilted against the film swings that plane (Scheimpflug's rule): it turns about a line beside the
camera, the hinge, which lies in the lens's plane f / sin(tilt) from the axis (Merklinger's hinge rule), and still
crosses the axis at the focus distance. Seen from the camera the plane leans by an angle whose tangent is
focus distance * sin(tilt) / f. Tilted one way, a slanting surface (a street, a field) is sharp from near to far; the
other way, only a narrow band of the picture is, which is the miniature look. The lens's shift, moving it across the
film without turning the camera, is MoonRay's film offset, which this camera keeps (labelled as shift).

This writes the new class from MoonRay's own perspective camera, so the two stay alike:
- dso/camera/TiltShiftCamera: PerspectiveCamera's DSO, its attributes with lens_tilt and tilt_direction (degrees)
  added after the rest, so every attribute the two share is laid out as it is in PerspectiveCamera;
- lib/rendering/pbr/camera/TiltShiftCamera.{h,cc}: PerspectiveCamera's renderer code, its rays met by the tilted plane
  of focus. With no tilt the plane's equation reduces to MoonRay's, operation for operation, and the picture is
  PerspectiveCamera's;
- pbr/core/Scene.cc makes one for the class, and the build lists both.

With MOONRAY_MODO_TILT_SHIFT=0 (the plugin's preference off) the lens is not tilted: the camera focuses as a perspective
camera does (and the plugin writes a PerspectiveCamera in its place). Unset, it is on. XPU2's camera_core.h tilts the
plane the same way (cpu_scene.h reads the class), and MoonLightIPR's kernel too (moonlightipr_scene.py packs the plane).

Run on the upstream tree before building; it can be run again (each step checks it is done)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOONRAY = ROOT / 'upstream/openmoonray/moonray/moonray'
DSO = MOONRAY / 'dso/camera'
PBR = MOONRAY / 'lib/rendering/pbr'
CHANGED = []


def write(path, text):
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')
    CHANGED.append(path)


def edit(path, old, new, done):
    text = path.read_text(encoding='utf-8')
    if done in text:
        return
    if text.count(old) != 1:
        raise SystemExit('%s: the text to change is not there once' % path)
    write(path, text.replace(old, new))


def swap(text, old, new):
    if text.count(old) != 1:
        raise SystemExit('PerspectiveCamera changed: %r is not there once' % old[:70])
    return text.replace(old, new)


# ---- The DSO -----------------------------------------------------------------------------------------------------

def dso():
    source = DSO / 'PerspectiveCamera'
    write(DSO / 'TiltShiftCamera/CMakeLists.txt', (source / 'CMakeLists.txt').read_text(encoding='utf-8').replace('PerspectiveCamera', 'TiltShiftCamera'))
    code = (source / 'PerspectiveCamera.cc').read_text(encoding='utf-8')
    code = code.replace('PerspectiveCamera', 'TiltShiftCamera')
    write(DSO / 'TiltShiftCamera/TiltShiftCamera.cc', code)
    attributes = (source / 'attributes.cc').read_text(encoding='utf-8')
    attributes = swap(attributes, '    rdl2::AttributeKey<rdl2::Float>  attrBokehWeightStrength;\n',
                      '    rdl2::AttributeKey<rdl2::Float>  attrBokehWeightStrength;\n\n'
                      '    // Modo: the tilt of the lens (tools/port_tilt_shift.py).\n'
                      '    rdl2::AttributeKey<rdl2::Float>  attrLensTilt;\n'
                      '    rdl2::AttributeKey<rdl2::Float>  attrTiltDirection;\n')
    # A tilt-shift lens's shift is the film offset.
    for axis, across in (('Horizontal', 'across'), ('Vertical', 'up and down')):
        lower = axis.lower()
        attributes = swap(attributes, 'sceneClass.setMetadata(attr%sFilmOffset, "label", "%s film offset");' % (axis, lower),
                          'sceneClass.setMetadata(attr%sFilmOffset, "label", "%s shift");' % (axis, lower))
        attributes = swap(attributes, 'sceneClass.setMetadata(attr%sFilmOffset, rdl2::SceneClass::sComment, "%s offset of the frustum.");' % (axis, axis),
                          'sceneClass.setMetadata(attr%sFilmOffset, rdl2::SceneClass::sComment, "Shift of the lens %s the film, '
                          'in the film\'s units (mm), as on a tilt-shift lens: the picture moves without the camera turning, so '
                          'upright lines stay upright.");' % (axis, across))
    attributes = swap(attributes, '\n    // Grouping the attributes for Torch', '''
    attrLensTilt = sceneClass.declareAttribute<rdl2::Float>("lens_tilt", 0.0f, { "lens tilt" });
    sceneClass.setMetadata(attrLensTilt, "label", "lens tilt");
    sceneClass.setMetadata(attrLensTilt, rdl2::SceneClass::sComment, "How far the lens is tilted against the film, in "
        "degrees, as on a tilt-shift lens. The plane of focus swings about a line beside the camera (Scheimpflug's rule): "
        "with the tilt direction at 0, a positive tilt lays it down toward what is below the view, so that the ground is "
        "sharp from near to far, and a negative one stands it up, so that only a narrow band is (the miniature look). "
        "Shows with depth of field on.");
    attrTiltDirection = sceneClass.declareAttribute<rdl2::Float>("tilt_direction", 0.0f, { "tilt direction" });
    sceneClass.setMetadata(attrTiltDirection, "label", "tilt direction");
    sceneClass.setMetadata(attrTiltDirection, rdl2::SceneClass::sComment, "Which way the lens tilts, in degrees round the "
        "view: 0 tilts it up and down, so the plane of focus swings about a line below the camera; 90 swings it sideways, "
        "about a line to its right.");

    // Grouping the attributes for Torch''')
    attributes = swap(attributes, '    sceneClass.setGroup("Depth of Field", attrBokehWeightStrength);\n',
                      '    sceneClass.setGroup("Depth of Field", attrBokehWeightStrength);\n\n'
                      '    sceneClass.setGroup("Tilt-Shift", attrLensTilt);\n'
                      '    sceneClass.setGroup("Tilt-Shift", attrTiltDirection);\n')
    write(DSO / 'TiltShiftCamera/attributes.cc', attributes)
    edit(DSO / 'CMakeLists.txt', 'add_subdirectory(SphericalCamera)', 'add_subdirectory(SphericalCamera)\nadd_subdirectory(TiltShiftCamera)',
         'add_subdirectory(TiltShiftCamera)')


# ---- The renderer's camera -----------------------------------------------------------------------------------------

SWITCH = '''
// Modo: whether the lens is tilted (tools/port_tilt_shift.py). Unless MOONRAY_MODO_TILT_SHIFT=0, as the plugin sets it
// from its preference: off, the camera focuses as PerspectiveCamera does.
bool
modoTiltShift()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_TILT_SHIFT");
        return !value || value[0] != '0';
    }();
    return on;
}

// Where a ray from the camera's focal point meets the plane of focus through the point focusDistance down the view,
// square to normal: the tilted lens's plane (TiltShiftCamera::updateImpl). With normal (0, 0, 1) this is
// getFocusPlaneHitPoint's sum, operation for operation. A ray that meets the plane behind the camera, or never, is in
// focus far off.
finline Vec3f
getTiltedFocusPlaneHitPoint(const Vec3f& focalPoint, const Vec3f& raster, const Mat4f& rt2c,
                            float focusDistance, const Vec3f& normal)
{
    const Vec3f dir = normalize(transformH(rt2c, raster) - focalPoint);
    float t = dot(normal, Vec3f(0.0f, 0.0f, -focusDistance) - focalPoint) / dot(normal, dir);
    const float farOff = 1.0e6f * max(focusDistance, 1.0f);
    if (!(t > 0.0f) || t > farOff) {
        t = farOff;
    }
    return focalPoint + dir * t;
}
'''

UPDATE = '''
    // Modo: the plane of focus of the tilted lens (tools/port_tilt_shift.py). It crosses the view at the focus distance
    // and leans about a hinge line f / sin(tilt) from the axis, on the side the tilt direction points to (below the
    // camera at 0, to its right at 90), so that its slope from the camera is focus distance * sin(tilt) / f, f in the
    // scene's units (as ProjectiveCamera turns the focal length's millimetres into them).
    mFocusNormal = Vec3f(0.0f, 0.0f, 1.0f);
    const float tilt = deg2rad(getRdlCamera()->get(sLensTiltKey));
    if (modoTiltShift() && getIsDofEnabled() && tilt != 0.0f) {
        const scene_rdl2::rdl2::SceneVariables& vars =
            getRdlCamera()->getSceneClass().getSceneContext()->getSceneVariables();
        const float worldToMm = vars.get(scene_rdl2::rdl2::SceneVariables::sSceneScaleKey) * 1000.0f;
        const float focal = max(getFocalDistance(), 0.00001f) / worldToMm;
        const float direction = deg2rad(getRdlCamera()->get(sTiltDirectionKey));
        const float slope = getDofFocusDistance() * sin(tilt) / focal;
        mFocusNormal = normalize(Vec3f(-slope * sin(direction), slope * cos(direction), 1.0f));
    }
'''


def renderer():
    header = (PBR / 'camera/PerspectiveCamera.h').read_text(encoding='utf-8').replace('PerspectiveCamera', 'TiltShiftCamera')
    header = swap(header, '    scene_rdl2::math::Vec3f mFocalPoint;\n',
                  '    scene_rdl2::math::Vec3f mFocalPoint;\n'
                  '    // Modo: the normal of the tilted lens\'s plane of focus, in camera space; (0, 0, 1) untilted.\n'
                  '    scene_rdl2::math::Vec3f mFocusNormal = scene_rdl2::math::Vec3f(0.0f, 0.0f, 1.0f);\n')
    header = swap(header, '    static scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Float> sStereoConvergenceDistance;\n',
                  '    static scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Float> sStereoConvergenceDistance;\n'
                  '    static scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Float> sLensTiltKey;\n'
                  '    static scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Float> sTiltDirectionKey;\n')
    write(PBR / 'camera/TiltShiftCamera.h', header)

    code = (PBR / 'camera/PerspectiveCamera.cc').read_text(encoding='utf-8').replace('PerspectiveCamera', 'TiltShiftCamera')
    code = swap(code, '#include "TiltShiftCamera.h"\n', '#include "TiltShiftCamera.h"\n\n#include <cstdlib>\n')
    code = swap(code, 'rdl2::AttributeKey<rdl2::Float> TiltShiftCamera::sStereoConvergenceDistance;\n',
                'rdl2::AttributeKey<rdl2::Float> TiltShiftCamera::sStereoConvergenceDistance;\n'
                'rdl2::AttributeKey<rdl2::Float> TiltShiftCamera::sLensTiltKey;\n'
                'rdl2::AttributeKey<rdl2::Float> TiltShiftCamera::sTiltDirectionKey;\n')
    code = swap(code, '\nfinline float\ngetClipPlaneT(', SWITCH + '\nfinline float\ngetClipPlaneT(')
    code = swap(code, '    sStereoConvergenceDistance = sceneClass.getAttributeKey<rdl2::Float>("stereo_convergence_distance");\n',
                '    sStereoConvergenceDistance = sceneClass.getAttributeKey<rdl2::Float>("stereo_convergence_distance");\n'
                '    sLensTiltKey = sceneClass.getAttributeKey<rdl2::Float>("lens_tilt");\n'
                '    sTiltDirectionKey = sceneClass.getAttributeKey<rdl2::Float>("tilt_direction");\n')
    # Every focus-plane hit in createDOFRay meets the tilted plane.
    calls = len(re.findall(r'getFocusPlaneHitPoint\(mFocalPoint,', code))
    if calls != 3:
        raise SystemExit('PerspectiveCamera changed: createDOFRay has %d focus-plane hits, not 3' % calls)
    code = re.sub(r'getFocusPlaneHitPoint\(mFocalPoint,(\s*)raster(\s*\+\s*n[xy])?,(\s*)rt2ct,(\s*)getDofFocusDistance\(\)\)',
                  lambda m: 'getTiltedFocusPlaneHitPoint(mFocalPoint,%sraster%s,%srt2ct,%sgetDofFocusDistance(), mFocusNormal)'
                  % (m.group(1), m.group(2) or '', m.group(3), m.group(4)), code)
    if code.count('getTiltedFocusPlaneHitPoint(mFocalPoint,') != 3:
        raise SystemExit('PerspectiveCamera changed: the focus-plane hits could not all be tilted')
    # After the stereo focal point is set, at the end of updateImpl.
    marker = '''        mFocalPoint.x = -computeInterocularOffset(stereoView,
                                                  getRdlCamera()->get(
                                                      sStereoInterocularDistance));
    }
'''
    code = swap(code, marker, marker + UPDATE)
    write(PBR / 'camera/TiltShiftCamera.cc', code)

    edit(PBR / 'camera/../CMakeLists.txt', '        camera/PerspectiveCamera.cc\n', '        camera/PerspectiveCamera.cc\n        camera/TiltShiftCamera.cc\n',
         'camera/TiltShiftCamera.cc')
    scene = PBR / 'core/Scene.cc'
    edit(scene, '#include <moonray/rendering/pbr/camera/SphericalCamera.h>\n',
         '#include <moonray/rendering/pbr/camera/SphericalCamera.h>\n#include <moonray/rendering/pbr/camera/TiltShiftCamera.h>\n',
         'camera/TiltShiftCamera.h')
    edit(scene, '''    } else if (className == "FisheyeCamera") {
        return std::unique_ptr<Camera>(new FisheyeCamera(rdlCamera));
''', '''    } else if (className == "FisheyeCamera") {
        return std::unique_ptr<Camera>(new FisheyeCamera(rdlCamera));
    } else if (className == "TiltShiftCamera") {
        // Modo: a perspective camera with a tilting lens (tools/port_tilt_shift.py).
        return std::unique_ptr<Camera>(new TiltShiftCamera(rdlCamera));
''', 'new TiltShiftCamera(rdlCamera)')


def main():
    dso()
    renderer()
    print('Tilt-shift camera: %s' % ('; '.join(str(p.relative_to(ROOT)) for p in CHANGED) if CHANGED else 'already in place'))


if __name__ == '__main__':
    sys.exit(main())
