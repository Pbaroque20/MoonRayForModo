// An Alembic file's meshes as the kit needs them for motion blur: Modo's Alembic loader gives its render cache a mesh's
// points and faces, not its velocities, so a mesh rebuilt each frame (a fluid mesher's) could not be blurred.
//
//   modo_abc_reader --list <file.abc>
// prints each object of the file: its path, its kind, its samples and time range, and a mesh's point and face counts
// and whether it has velocities (its .velocities, or a "v" or "velocity" geometry parameter).
//
//   modo_abc_reader <file.abc> <object path or name> <seconds> <output>
// writes the mesh at that time (the sample at or before it): "MABC", the counts of points, faces and face-vertex indices,
// whether it has velocities, then its points (three floats each, in its own space), its velocities (as many, in units a
// second) and its face counts. Its world transform is the kit's (Modo's item), not read here.
//
//   modo_abc_reader --meshes <file.abc> <seconds> <output>
// writes every mesh of the file at that time, for the kit to render as it stands (entities a file's own, a fluid mesher's
// rebuilt each frame): "MAB2", the count of meshes, then each: its name, its world matrix (sixteen floats, rows, the
// Xforms above it at that time), the time of its sample, its first and last sample times, the counts of points, faces
// and face-vertex indices, whether it has velocities, then its points, its velocities and its face counts and indices,
// each face's turned to Modo's winding (Alembic holds them clockwise). Ogawa files only (every
// Alembic of the last decade); the older HDF5 kind is refused.
#include <Alembic/AbcCoreOgawa/All.h>
#include <Alembic/AbcGeom/All.h>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

using namespace Alembic::AbcGeom;

namespace {

// A mesh's velocities: its schema's own, else a geometry parameter named v or velocity (Houdini writes v).
bool velocitiesOf(const IPolyMeshSchema& mesh, const ISampleSelector& at, std::vector<V3f>& out) {
    if (mesh.getVelocitiesProperty().valid()) {
        V3fArraySamplePtr held = mesh.getVelocitiesProperty().getValue(at);
        if (held && held->size()) {
            out.assign(held->get(), held->get() + held->size());
            return true;
        }
    }
    ICompoundProperty params = mesh.getArbGeomParams();
    if (!params.valid()) return false;
    for (size_t i = 0; i < params.getNumProperties(); ++i) {
        const auto& header = params.getPropertyHeader(i);
        if (header.getName() != "v" && header.getName() != "velocity" && header.getName() != "velocities") continue;
        if (!IV3fGeomParam::matches(header)) continue;
        IV3fGeomParam param(params, header.getName());
        IV3fGeomParam::Sample sample = param.getExpandedValue(at);
        if (sample.getVals() && sample.getVals()->size()) {
            out.assign(sample.getVals()->get(), sample.getVals()->get() + sample.getVals()->size());
            return true;
        }
    }
    return false;
}

void list(const IObject& object, int depth) {
    for (size_t i = 0; i < object.getNumChildren(); ++i) {
        IObject child(object, object.getChildHeader(i).getName());
        const std::string path = child.getFullName();
        if (IPolyMesh::matches(child.getHeader())) {
            IPolyMesh mesh(object, child.getName());
            const IPolyMeshSchema& schema = mesh.getSchema();
            const size_t samples = schema.getNumSamples();
            TimeSamplingPtr timing = schema.getTimeSampling();
            const double first = timing->getSampleTime(0), last = timing->getSampleTime(samples ? samples - 1 : 0);
            IPolyMeshSchema::Sample sample;
            schema.get(sample, ISampleSelector(Abc::index_t(0)));
            std::vector<V3f> velocities;
            const bool moving = velocitiesOf(schema, ISampleSelector(Abc::index_t(0)), velocities);
            std::printf("mesh %s samples %zu seconds %.4f to %.4f topology %s points %zu faces %zu velocities %s\n", path.c_str(), samples, first,
                        last, schema.getTopologyVariance() == kHeterogeneousTopology ? "changing" : schema.getTopologyVariance() == kHomogenousTopology ? "fixed" : "constant",
                        sample.getPositions() ? sample.getPositions()->size() : 0, sample.getFaceCounts() ? sample.getFaceCounts()->size() : 0,
                        moving ? "yes" : "no");
        } else {
            std::printf("%s %s\n", child.getHeader().getMetaData().get("schema").c_str(), path.c_str());
        }
        list(child, depth + 1);
    }
}

// Every mesh below an object, with the Xforms above it multiplied in (row vectors, as Alembic and Modo hold them).
void meshes(const IObject& object, const M44d& above, const ISampleSelector& at, std::vector<std::pair<IObject, M44d>>& out) {
    for (size_t i = 0; i < object.getNumChildren(); ++i) {
        IObject child(object, object.getChildHeader(i).getName());
        M44d here = above;
        if (IXform::matches(child.getHeader())) {
            IXform xform(object, child.getName());
            XformSample sample;
            xform.getSchema().get(sample, at);
            here = xform.getSchema().getInheritsXforms() ? sample.getMatrix() * above : sample.getMatrix();
        } else if (IPolyMesh::matches(child.getHeader())) {
            out.emplace_back(child, above);
        }
        meshes(child, here, at, out);
    }
}

// The mesh named (its full path, or its own name, or the last part of a path), or none.
IObject find(const IObject& object, const std::string& wanted) {
    for (size_t i = 0; i < object.getNumChildren(); ++i) {
        IObject child(object, object.getChildHeader(i).getName());
        if (IPolyMesh::matches(child.getHeader()) && (child.getFullName() == wanted || child.getName() == wanted)) return child;
        IObject found = find(child, wanted);
        if (found.valid()) return found;
    }
    return IObject();
}

}  // namespace

int main(int argc, char** argv) {
    try {
        auto open = [](const char* path) {
            IArchive archive(Alembic::AbcCoreOgawa::ReadArchive(), path);
            if (!archive.valid()) throw std::runtime_error("not an Alembic (Ogawa) file it can read");
            return archive;
        };
        if (argc == 3 && std::string(argv[1]) == "--list") {
            IArchive archive = open(argv[2]);
            list(archive.getTop(), 0);
            return 0;
        }
        if (argc == 5 && std::string(argv[1]) == "--meshes") {
            IArchive archive = open(argv[2]);
            const double seconds = std::atof(argv[3]);
            const ISampleSelector at(seconds, ISampleSelector::kFloorIndex);
            std::vector<std::pair<IObject, M44d>> found;
            M44d identity;
            identity.makeIdentity();
            meshes(archive.getTop(), identity, at, found);
            std::ofstream out(argv[4], std::ios::binary);
            out.write("MAB2", 4);
            const uint32_t count = uint32_t(found.size());
            out.write(reinterpret_cast<const char*>(&count), 4);
            for (auto& [object, matrix] : found) {
                IPolyMesh mesh(object.getParent(), object.getName());
                const IPolyMeshSchema& schema = mesh.getSchema();
                IPolyMeshSchema::Sample sample;
                schema.get(sample, at);
                std::vector<V3f> velocities;
                velocitiesOf(schema, at, velocities);
                const size_t points = sample.getPositions() ? sample.getPositions()->size() : 0;
                if (velocities.size() != points) velocities.clear();
                const std::string name = object.getFullName();
                const uint32_t length = uint32_t(name.size());
                out.write(reinterpret_cast<const char*>(&length), 4);
                out.write(name.data(), length);
                float m[16];
                for (int r = 0; r < 4; ++r)
                    for (int c = 0; c < 4; ++c) m[4 * r + c] = float(matrix[r][c]);
                out.write(reinterpret_cast<const char*>(m), sizeof(m));
                TimeSamplingPtr timing = schema.getTimeSampling();
                const size_t samples = schema.getNumSamples();
                const float times[3] = {float(timing->getSampleTime(timing->getFloorIndex(seconds, samples).first)),
                                        float(timing->getSampleTime(0)), float(timing->getSampleTime(samples ? samples - 1 : 0))};
                out.write(reinterpret_cast<const char*>(times), sizeof(times));
                const size_t faces = sample.getFaceCounts() ? sample.getFaceCounts()->size() : 0;
                const size_t indices = sample.getFaceIndices() ? sample.getFaceIndices()->size() : 0;
                const uint32_t counts[4] = {uint32_t(points), uint32_t(faces), uint32_t(indices), uint32_t(velocities.empty() ? 0 : 1)};
                out.write(reinterpret_cast<const char*>(counts), sizeof(counts));
                if (points) out.write(reinterpret_cast<const char*>(sample.getPositions()->get()), points * sizeof(V3f));
                if (!velocities.empty()) out.write(reinterpret_cast<const char*>(velocities.data()), points * sizeof(V3f));
                if (faces) out.write(reinterpret_cast<const char*>(sample.getFaceCounts()->get()), faces * sizeof(int32_t));
                // Each face's corners turned round: Alembic's clockwise to Modo's (and MoonRay's) counter-clockwise.
                std::vector<int32_t> turned(indices);
                size_t at_index = 0;
                for (size_t f = 0; f < faces; ++f) {
                    const int32_t n = (*sample.getFaceCounts())[f];
                    for (int32_t k = 0; k < n && at_index + k < indices; ++k) turned[at_index + k] = (*sample.getFaceIndices())[at_index + (n - 1 - k)];
                    at_index += size_t(std::max(0, n));
                }
                if (indices) out.write(reinterpret_cast<const char*>(turned.data()), indices * sizeof(int32_t));
            }
            if (!out) throw std::runtime_error("cannot write the output");
            std::cout << found.size() << " meshes" << std::endl;
            return 0;
        }
        if (argc != 5) {
            std::cerr << "usage: modo_abc_reader --list <file.abc> | modo_abc_reader <file.abc> <mesh> <seconds> <output>" << std::endl;
            return 2;
        }
        IArchive archive = open(argv[1]);
        IObject object = find(archive.getTop(), argv[2]);
        if (!object.valid()) throw std::runtime_error(std::string("no mesh named ") + argv[2]);
        IPolyMesh mesh(object.getParent(), object.getName());
        const IPolyMeshSchema& schema = mesh.getSchema();
        const ISampleSelector at(std::atof(argv[3]), ISampleSelector::kFloorIndex);
        IPolyMeshSchema::Sample sample;
        schema.get(sample, at);
        std::vector<V3f> velocities;
        const bool moving = velocitiesOf(schema, at, velocities);
        const size_t points = sample.getPositions() ? sample.getPositions()->size() : 0;
        if (moving && velocities.size() != points) velocities.clear();
        const uint32_t counts[4] = {uint32_t(points), uint32_t(sample.getFaceCounts() ? sample.getFaceCounts()->size() : 0),
                                    uint32_t(sample.getFaceIndices() ? sample.getFaceIndices()->size() : 0), uint32_t(velocities.empty() ? 0 : 1)};
        std::ofstream out(argv[4], std::ios::binary);
        out.write("MABC", 4);
        out.write(reinterpret_cast<const char*>(counts), sizeof(counts));
        if (points) out.write(reinterpret_cast<const char*>(sample.getPositions()->get()), points * sizeof(V3f));
        if (!velocities.empty()) out.write(reinterpret_cast<const char*>(velocities.data()), points * sizeof(V3f));
        if (counts[1]) out.write(reinterpret_cast<const char*>(sample.getFaceCounts()->get()), counts[1] * sizeof(int32_t));
        if (!out) throw std::runtime_error("cannot write the output");
        std::cout << points << " points, " << counts[1] << " faces, velocities " << (velocities.empty() ? "no" : "yes") << std::endl;
        return 0;
    } catch (const std::exception& problem) {
        std::cerr << "modo_abc_reader: " << problem.what() << std::endl;
        return 1;
    }
}
