"""Add paired affine transform arrays to the native shared instancer."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
base=ROOT/'upstream/openmoonray/moonray/moonray'
def replace(path,old,new):
 text=path.read_text(encoding='utf-8')
 if new in text:return
 if old not in text:raise RuntimeError('Instance motion patch anchor missing: '+str(path))
 path.write_text(text.replace(old,new,1),encoding='utf-8')
a=base/'dso/geometry/RdlInstancerGeometry/attributes.cc'
replace(a,'    scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Mat4dVector> attrXformList;',
 '    scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Mat4dVector> attrXformList;\n    scene_rdl2::rdl2::AttributeKey<scene_rdl2::rdl2::Mat4dVector> attrXformListClose;')
replace(a,'    attrPositions =','''    attrXformListClose = sceneClass.declareAttribute<scene_rdl2::rdl2::Mat4dVector>("xform_list_close");
    sceneClass.setMetadata(attrXformListClose, "comment", "Optional shutter-close affine transforms paired with shutter-open xform_list. Requires matching counts; supersedes velocities when motion blur is enabled.");
    sceneClass.setGroup("Motion Blur", attrXformListClose);

    attrPositions =''')
replace(base/'dso/geometry/RdlInstancerGeometry/RdlInstancerGeometry.cc',
 'instanceGeometry->get(attrXformList));','instanceGeometry->get(attrXformList),\n                           instanceGeometry->get(attrXformListClose));')
h=base/'lib/rendering/geom/InstanceProceduralLeaf.h'
replace(h,'const scene_rdl2::rdl2::Mat4dVector& xforms);',
 'const scene_rdl2::rdl2::Mat4dVector& xforms,\n                            const scene_rdl2::rdl2::Mat4dVector& xformsClose = {});')
c=base/'lib/rendering/geom/InstanceProceduralLeaf.cc'
replace(c,'const scene_rdl2::rdl2::Mat4dVector& xforms)',
 'const scene_rdl2::rdl2::Mat4dVector& xforms,\n                                           const scene_rdl2::rdl2::Mat4dVector& xformsClose)')
replace(c,'        // motion blur\n','''        // Modo paired affine instance motion; endpoints use SceneVariables motion_steps.
        if (!xformsClose.empty() && (instanceMethod != InstanceMethod::XFORMS || xformsClose.size() != xforms.size())) {
            rdlGeometry->error("xform_list_close requires xform-list method and matching sample counts");
            return;
        }
        const bool applyAffineMotion = generateContext.isMotionBlurOn() && !xformsClose.empty();
        // motion blur
''')
replace(c,'} else if (instanceMethod == InstanceMethod::XFORMS) {\n                    if (applyVelocity) {','''} else if (instanceMethod == InstanceMethod::XFORMS) {
                    if (applyAffineMotion) {
                        xform.push_back(scene_rdl2::math::xform<scene_rdl2::math::Xform3f>(xforms[i]));
                        xform.push_back(scene_rdl2::math::xform<scene_rdl2::math::Xform3f>(xformsClose[i]));
                    } else if (applyVelocity) {''')
print('Native paired instance transform source enabled; render verification deferred.')
