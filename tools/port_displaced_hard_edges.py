"""A displaced polygon mesh's hard edges shade sharp, as in Modo.

MoonRay drops a displaced polygon mesh's own normals (PolyMesh::initAttributesAndDisplace): it makes smooth normals for
its points, displaces each point once along its own (so the surface stays closed), then smooths the shading normals
again over the displaced shape. An edge the mesh had hard (Modo's smoothing angle: its corner normals differ there)
comes out round: a displaced box's edges shaded like a pillow's, where Modo's stay sharp.

Unless MoonRay is started with MOONRAY_MODO_DISPLACED_HARD_EDGES=0 (the plugin's preference off), the displacement is
the same and afterwards each face corner gets a shading normal of its own where a point's faces disagreed as given
(native-port/modo_hard_edges.h, written here as geom/prim/ModoHardEdges.h): the normalized sum of the displaced faces'
normals (PolyMeshCalcNv's own, in its order) over the faces that agreed with the corner's. Every other corner keeps its
point's normal bit for bit, and a mesh with no hard edge is shaded as before. QuadMesh and TriMesh read the corners'
normals at a hit, weighed as MoonRay weighs its points' normals (Interpolator::interpolateVertices), and for the toon
terminator and curvature (get*Attributes). Reversed and mirrored meshes turn their corners over with their faces.

XPU2 makes the same normals from the same faces in xpu2_geom.dll (it includes native-port/modo_hard_edges.h: XPU2's
runtime loads the pinned reference MoonRay's geometry library, which this patch does not reach). MoonLightIPR splits its
displaced meshes' points at hard edges after displacing them once (moonlightipr_scene.welded, scene_loader.cpp).

With it 0 MoonRay is as its source has it; unset, it is on. Run on the upstream tree after tools/port_mirrored_meshes.py;
it can be run again (each file checks it is done)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIM = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/geom/prim'
SHARED = ROOT / 'native-port/modo_hard_edges.h'
MARK = 'port_displaced_hard_edges'

MEMBER_OLD = '''    // whether calculate smooth shading normal
    bool mSmoothNormal;
    uint32_t mCurvedMotionBlurSampleCount;
    scene_rdl2::rdl2::MotionBlurType mMotionBlurType;
};'''
MEMBER_NEW = '''    // whether calculate smooth shading normal
    bool mSmoothNormal;
    uint32_t mCurvedMotionBlurSampleCount;
    scene_rdl2::rdl2::MotionBlurType mMotionBlurType;

    // Modo: a displaced mesh's hard edges (tools/port_displaced_hard_edges.py): each hit face corner's shading normal,
    // mModoCornerSteps time samples each, or nothing (its points' normals then shade it). Last, after every member
    // MoonRay has, so that code built against MoonRay's layout reads the others where they were.
    std::vector<scene_rdl2::math::Vec3f> mModoCornerNormals;
    size_t mModoCornerSteps = 0;
};'''

POLY_INCLUDE_OLD = '#include "PolyMesh.h"\n'
POLY_INCLUDE_NEW = '#include "PolyMesh.h"\n#include "ModoHardEdges.h"\n'

GIVEN_OLD = '''    if (calculateSmoothNormal) {
        // when we decide to calculate the smooth shading normal,'''
GIVEN_NEW = '''    // Modo: a displaced mesh's corner normals as given, for its hard edges once it is displaced
    // (tools/port_displaced_hard_edges.py): face-varying ones, or a face's own normal at each of its corners.
    mModoCornerNormals.clear();
    mModoCornerSteps = 0;
    std::vector<Vec3f> modoGiven;
    if (hasDisplacement && modo_hard_edges::on() &&
        primitiveAttributeTable.hasAttribute(StandardAttributes::sNormal)) {
        const AttributeRate rate = primitiveAttributeTable.getRate(StandardAttributes::sNormal);
        const PrimitiveAttribute<Vec3f>& given = primitiveAttributeTable.getAttribute(StandardAttributes::sNormal, 0);
        if (rate == RATE_FACE_VARYING && given.size() == baseFaceCount * faceVertexCount) {
            for (size_t i = 0; i < given.size(); ++i) {
                modoGiven.push_back(given[i]);
            }
        } else if (rate == RATE_UNIFORM && given.size() == baseFaceCount) {
            for (size_t f = 0; f < baseFaceCount; ++f) {
                for (size_t c = 0; c < faceVertexCount; ++c) {
                    modoGiven.push_back(given[f]);
                }
            }
        }
    }

    if (calculateSmoothNormal) {
        // when we decide to calculate the smooth shading normal,'''

CORNERS_OLD = '''    // Modo: smooth normals made from a mirrored mesh's faces turned over with them (its own do not); tessellate then'''
CORNERS_NEW = '''    // Modo: each corner's shading normal where a point's faces disagreed as given: a displaced mesh's hard edges
    // (tools/port_displaced_hard_edges.py, native-port/modo_hard_edges.h).
    if (!modoGiven.empty()) {
        const bool quadBase = baseFaceType == MeshIndexType::QUAD;
        const size_t fvc = (mIsTessellated || quadBase) ? sQuadVertexCount : sTriangleVertexCount;
        const size_t faces = mIndices.size() / fvc;
        const std::vector<Vec3f> keys = modo_hard_edges::givenAtCorners(faces, fvc, mIsTessellated, quadBase,
            mTessellatedToBaseFace.data(), mFaceVaryingUv.data(), modoGiven.data(), faceVertexCount);
        const Attributes* attributes = getAttributes();
        const size_t steps = attributes->getTimeSampleCount(StandardAttributes::sNormal);
        mModoCornerNormals = modo_hard_edges::cornerNormals(faces, fvc, mIndices.data(), mVertices.size(), steps, keys,
            [&](uint32_t v, size_t t) {
                const float *p = (const float *)&mVertices(v, t);
                return Vec3f(p[0], p[1], p[2]);
            },
            [&](uint32_t v, size_t t) {
                return attributes->getVertex(StandardAttributes::sNormal, v, int(t));
            });
        mModoCornerSteps = mModoCornerNormals.empty() ? 0 : steps;
    }

    // Modo: smooth normals made from a mirrored mesh's faces turned over with them (its own do not); tessellate then'''

MIRROR_OLD = '''        getAttributes()->negateNormal();
    }'''
MIRROR_NEW = '''        getAttributes()->negateNormal();
        for (Vec3f& n : mModoCornerNormals) {
            n = -n;
        }
    }'''

REVERSE_OLD = '''        reverseOrientation(faceVertexCount,
                           mIndices,
                           mAttributes);
    }

    if (mIsNormalReversed) mAttributes->negateNormal();'''
REVERSE_NEW = '''        reverseOrientation(faceVertexCount,
                           mIndices,
                           mAttributes);
        // Modo: the corners' own normals with their faces' corners (tools/port_displaced_hard_edges.py).
        modo_hard_edges::reverseCorners(mModoCornerNormals, faceVertexCount, mModoCornerSteps);
    }

    if (mIsNormalReversed) mAttributes->negateNormal();
    if (mIsNormalReversed) {
        for (Vec3f& n : mModoCornerNormals) {
            n = -n;
        }
    }'''

HELPER = '''
namespace {
// Modo: a displaced mesh's corners' own normals at its hard edges (tools/port_displaced_hard_edges.py), in place of
// its points' normals; any other attribute as before.
template <typename T>
bool modoCorners(const std::vector<Vec3f>&, size_t, const TypedAttributeKey<T>&, size_t, int, int, int, T&, T&, T&, float)
{
    return false;
}
bool modoCorners(const std::vector<Vec3f>& corners, size_t steps, const TypedAttributeKey<Vec3f>& key, size_t offset,
                 int index1, int index2, int index3, Vec3f& v1, Vec3f& v2, Vec3f& v3, float time)
{
    if (corners.empty() || !(key == StandardAttributes::sNormal)) {
        return false;
    }
    v1 = modo_hard_edges::at(corners, offset + index1, steps, time);
    v2 = modo_hard_edges::at(corners, offset + index2, steps, time);
    v3 = modo_hard_edges::at(corners, offset + index3, steps, time);
    return true;
}
} // namespace

'''

EXPLICIT_END = '''    setExplicitAttributes<MeshInterpolator>(interpolator,
                                            *primitiveAttributes,
                                            intersection);
}'''
QUAD_REQUIRED = '''    setExplicitAttributes<MeshInterpolator>(interpolator,
                                            *primitiveAttributes,
                                            intersection);

    // Modo: a displaced mesh's hard edges (tools/port_displaced_hard_edges.py): its corners' own normals, weighed as its
    // points' are (Interpolator::interpolateVertices: the quad's four corners in order).
    if (!mModoCornerNormals.empty()) {
        const size_t offset = sQuadVertexCount * size_t(tessFaceId);
        Vec3f N = scene_rdl2::math::zero;
        for (int i = 0; i < 4; ++i) {
            N = N + (Vec3f)(vertexW[i] * modo_hard_edges::at(mModoCornerNormals, offset + i, mModoCornerSteps, time));
        }
        N = N.normalize();
        intersection.setAttribute(StandardAttributes::sNormal, N);
        intersection.setN(N);
    }
}'''
TRI_REQUIRED = '''    setExplicitAttributes<MeshInterpolator>(interpolator,
                                            *primitiveAttributes,
                                            intersection);

    // Modo: a displaced mesh's hard edges (tools/port_displaced_hard_edges.py): its corners' own normals, weighed as its
    // points' are (Interpolator::interpolateVertices: the hit triangle's three corners, w u v).
    if (!mModoCornerNormals.empty()) {
        size_t c1 = 0, c2 = 1, c3 = 2, offset = sTriangleVertexCount * size_t(tessFaceId);
        if (mIsTessellated) {
            offset = sQuadVertexCount * size_t(tessFaceId);
            if (isFirst) {
                c1 = 0; c2 = 1; c3 = 3;
            } else {
                c1 = 2; c2 = 3; c3 = 1;
            }
        }
        Vec3f N = scene_rdl2::math::zero;
        N = N + (Vec3f)(w * modo_hard_edges::at(mModoCornerNormals, offset + c1, mModoCornerSteps, time));
        N = N + (Vec3f)(u * modo_hard_edges::at(mModoCornerNormals, offset + c2, mModoCornerSteps, time));
        N = N + (Vec3f)(v * modo_hard_edges::at(mModoCornerNormals, offset + c3, mModoCornerSteps, time));
        N = N.normalize();
        intersection.setAttribute(StandardAttributes::sNormal, N);
        intersection.setN(N);
    }
}'''

QUAD_FETCH_OLD = '''        index3 = 1;
    }

    const Attributes* attributes = getAttributes();
    if (attributes->isSupported(key)) {'''
QUAD_FETCH_NEW = '''        index3 = 1;
    }

    // Modo: a displaced mesh's corners' own normals at its hard edges (tools/port_displaced_hard_edges.py).
    if (modoCorners(mModoCornerNormals, mModoCornerSteps, key, sQuadVertexCount * size_t(tessFaceId),
                    index1, index2, index3, v1, v2, v3, time)) {
        return true;
    }

    const Attributes* attributes = getAttributes();
    if (attributes->isSupported(key)) {'''
TRI_FETCH_OLD = '''        index3 = 2;
    }

    const Attributes* attributes = getAttributes();
    if (attributes->isSupported(key)) {'''
TRI_FETCH_NEW = '''        index3 = 2;
    }

    // Modo: a displaced mesh's corners' own normals at its hard edges (tools/port_displaced_hard_edges.py).
    if (modoCorners(mModoCornerNormals, mModoCornerSteps, key,
                    (mIsTessellated ? sQuadVertexCount : sTriangleVertexCount) * size_t(tessFaceId),
                    index1, index2, index3, v1, v2, v3, time)) {
        return true;
    }

    const Attributes* attributes = getAttributes();
    if (attributes->isSupported(key)) {'''


def once(text, old, new, name, after=None):
    """old replaced by new once in text (in the part after the marker after, where given)."""
    start = text.index(after) if after else 0
    if after and text.count(after) != 1:
        raise SystemExit('%s: %r is not there once' % (name, after[:70]))
    part = text[start:]
    if part.count(old) < 1 or (after is None and text.count(old) != 1):
        raise SystemExit('%s: expected once: %s' % (name, old[:70]))
    return text[:start] + part.replace(old, new, 1)


def edit(name, changes, helper_before=None, include_after=None, include=None):
    path = PRIM / name
    raw = path.read_bytes().decode('utf-8')
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    if 'tools/port_displaced_hard_edges.py' in text:
        print('already applied', name)
        return
    for old, new, after in changes:
        text = once(text, old, new, name, after)
    if include_after:
        text = once(text, include_after, include_after + include, name)
    if helper_before:
        at = text.index(helper_before)
        text = text[:at] + HELPER.lstrip('\n') + text[at:]
    path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
    print('patched', name)


def main():
    if 'modoMirrored' not in (PRIM / 'PolyMesh.cc').read_text(encoding='utf-8'):
        raise SystemExit('Run tools/port_mirrored_meshes.py first')
    header = SHARED.read_text(encoding='utf-8')
    target = PRIM / 'ModoHardEdges.h'
    if not target.is_file() or target.read_text(encoding='utf-8') != header:
        target.write_text(header, encoding='utf-8', newline='\n')
        print('wrote', target.name)
    edit('PolyMesh.h', [(MEMBER_OLD, MEMBER_NEW, None)])
    edit('PolyMesh.cc', [(POLY_INCLUDE_OLD, POLY_INCLUDE_NEW, None), (GIVEN_OLD, GIVEN_NEW, None), (CORNERS_OLD, CORNERS_NEW, None),
                         (MIRROR_OLD, MIRROR_NEW, None), (REVERSE_OLD, REVERSE_NEW, None)])
    edit('QuadMesh.cc', [(EXPLICIT_END, QUAD_REQUIRED, None), (QUAD_FETCH_OLD, QUAD_FETCH_NEW, 'QuadMesh::getQuadAttributes(const')],
         helper_before='template <typename T> bool\nQuadMesh::getQuadAttributes(', include_after='#include "QuadMesh.h"\n',
         include='#include "ModoHardEdges.h"\n')
    edit('TriMesh.cc', [(EXPLICIT_END, TRI_REQUIRED, None), (TRI_FETCH_OLD, TRI_FETCH_NEW, 'TriMesh::getTriangleAttributes(const')],
         helper_before='template <typename T> bool\nTriMesh::getTriangleAttributes(', include_after='#include "TriMesh.h"\n',
         include='#include "ModoHardEdges.h"\n')


if __name__ == '__main__':
    main()
