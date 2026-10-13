// Original MoonRayForModo fur geometry: its attributes.
#include <scene_rdl2/scene/rdl2/rdl2.h>

using namespace scene_rdl2;

RDL2_DSO_ATTR_DECLARE

    rdl2::AttributeKey<rdl2::String> attrFile;
    rdl2::AttributeKey<rdl2::Int>    attrCurvesSubType;
    rdl2::AttributeKey<rdl2::Int>    attrTessellationRate;

RDL2_DSO_ATTR_DEFINE(rdl2::Geometry);

    attrFile = sceneClass.declareAttribute<rdl2::String>("file", "", rdl2::FLAGS_FILENAME);
    sceneClass.setMetadata(attrFile, "comment", "A fur file written by modo_fur_grow: the fibres as plain numbers.");

    attrCurvesSubType = sceneClass.declareAttribute<rdl2::Int>("curves_subtype", 0);
    sceneClass.setMetadata(attrCurvesSubType, "comment", "0: ribbons that face the ray. 1: round tubes.");

    attrTessellationRate = sceneClass.declareAttribute<rdl2::Int>("tessellation_rate", 4);

RDL2_DSO_ATTR_END
