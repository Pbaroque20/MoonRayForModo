"""A VDB's emission grid of single values (a temperature or flames grid) glows grey.

MoonRay's VdbVolume takes only an RGB (vector) grid as its emission grid: any other is refused at load with "Emission grid:
"temperature" is not an RGB grid." and the volume gives off no light. EmberGen, Houdini and Blender write their
temperature, flames and heat grids as single values (float grids), so none of their fire or explosions glows in MoonRay.

Only when MoonRay is started with MOONRAY_MODO_SCALAR_EMISSION=1 (the plugin's preference), a float emission grid is
read and made into an RGB grid of the same shape (its topology copied, tiles kept as tiles) with each value v as
(v, v, v), its background and transform kept; from there MoonRay goes on as with an RGB grid (the emission sampler, its
distribution, the emission sample rate). The volume's incandescence gain mult gives the glow its colour and strength.
XPU2's xpu2_geom.dll makes the same grid by the same steps (modoGreyGrid). Without the variable MoonRay is as its source has
it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'upstream/openmoonray/moonray/moonray/lib/rendering/geom/prim/VdbVolume.cc'

HELPER = '''
namespace {
// Modo: a single-value emission grid glows grey (tools/port_scalar_emission.py). Only with MOONRAY_MODO_SCALAR_EMISSION=1.
bool modoScalarEmission()
{
    static const bool on = [] {
        const char *value = std::getenv("MOONRAY_MODO_SCALAR_EMISSION");
        return value && value[0] == '1';
    }();
    return on;
}

// The float grid as an RGB grid of the same shape, each value v as (v, v, v); XPU2's xpu2_geom.cc makes it the same way.
openvdb::VectorGrid::Ptr modoGreyGrid(const openvdb::FloatGrid& scalar)
{
    const float background = scalar.background();
    openvdb::VectorGrid::Ptr grey = openvdb::VectorGrid::create(openvdb::Vec3f(background, background, background));
    grey->setTransform(scalar.transform().copy());
    grey->setName(scalar.getName());
    grey->tree().topologyUnion(scalar.tree());
    const openvdb::FloatGrid::ConstAccessor values = scalar.getConstAccessor();
    for (auto it = grey->beginValueAll(); it; ++it) {
        const float v = values.getValue(it.getCoord());
        it.setValue(openvdb::Vec3f(v, v, v));
    }
    return grey;
}
} // namespace
'''

OLD = '''    // check that it is a valid grid. If not, throw error.
    if (emissionGrid) {
        if (!emissionGrid->isType<openvdb::VectorGrid>()) {
            rdlGeometry.error("Emission grid: \\"", emissionGridName, "\\" is not an RGB grid.");
            return false;
        }

        // read voxel data
        emissionGrid = file.readGrid(emissionGridName);
        if (emissionGrid->empty()) {
            rdlGeometry.error("Emission grid: \\"", emissionGridName, "\\" is empty.");
            return false;
        }

        mEmissionGrid = openvdb::gridPtrCast<openvdb::VectorGrid>(emissionGrid);
    } else {'''
NEW = '''    // check that it is a valid grid. If not, throw error.
    if (emissionGrid) {
        // Modo: a single-value grid glows grey (tools/port_scalar_emission.py).
        const bool modoGrey = emissionGrid->isType<openvdb::FloatGrid>() && modoScalarEmission();
        if (!emissionGrid->isType<openvdb::VectorGrid>() && !modoGrey) {
            rdlGeometry.error("Emission grid: \\"", emissionGridName, "\\" is not an RGB grid.");
            return false;
        }

        // read voxel data
        emissionGrid = file.readGrid(emissionGridName);
        if (emissionGrid->empty()) {
            rdlGeometry.error("Emission grid: \\"", emissionGridName, "\\" is empty.");
            return false;
        }

        mEmissionGrid = modoGrey ? modoGreyGrid(*openvdb::gridPtrCast<openvdb::FloatGrid>(emissionGrid))
                                 : openvdb::gridPtrCast<openvdb::VectorGrid>(emissionGrid);
    } else {'''


def main():
    raw = SOURCE.read_bytes().decode('utf-8')
    crlf = '\r\n' in raw
    text = raw.replace('\r\n', '\n')
    if 'modoScalarEmission' in text:
        print('already applied', SOURCE.name)
        return
    if text.count(OLD) != 1:
        raise SystemExit('VdbVolume.cc: expected the emission grid check once, found %d' % text.count(OLD))
    text = text.replace(OLD, NEW)
    at = text.index('\nnamespace moonray')
    text = text[:at] + '\n' + HELPER + text[at:]
    if '#include <cstdlib>' not in text:
        first = text.index('#include <openvdb/openvdb.h>')
        text = text[:first] + '#include <cstdlib>\n' + text[first:]
    SOURCE.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode('utf-8'))
    print('patched', SOURCE.name)


if __name__ == '__main__':
    main()
