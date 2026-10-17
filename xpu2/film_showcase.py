"""Framed diffuse sphere and ground fixture, using live native light inputs."""
def scene(text):
    light='''table.insert(lights, DistantLight("/xpu2/key") {
 ["node_xform"]=Mat4(0.70710678,0,0.70710678,0,0.57735027,0.57735027,-0.57735027,0,-0.40824829,0.81649658,0.40824829,0,0,0,0,1),
 ["intensity"]=1.2, ["angular_extent"]=8, ["normalized"]=true
})
'''
    floor='''local ground = RdlMeshGeometry("/xpu2/ground") {
 ["vertex_list_0"]={Vec3(-5,-1,-5),Vec3(-5,-1,5),Vec3(5,-1,5),Vec3(5,-1,-5)},
 ["vertices_by_index"]={0,1,2,3}, ["face_vertex_count"]={4}
}
local groundMaterial=UsdPreviewSurface("/xpu2/ground/material") {
 ["diffuseColor"]=Rgb(0.4,0.43,0.48),["roughness"]=1,
 ["useSpecularWorkflow"]=1,["specularColor"]=Rgb(0,0,0)
}
table.insert(geometries,ground)
table.insert(assignments,{ground,"",groundMaterial,lightSet})
'''
    anchor='local lightSet = LightSet("/modo/lightSet")(lights)'
    layer='GeometrySet("/modo/geometrySet")(geometries)'
    if text.count(anchor)!=1 or text.count(layer)!=1:raise ValueError('Showcase scene anchor drift')
    text=text.replace(anchor,light+anchor).replace(layer,floor+layer).replace('["intensity"] = 0.3','["intensity"] = 0.12',1)
    return text+'''\nPerspectiveCamera("/modo/camera") {
 ["node_xform"]=Mat4(1,0,0,0,0,0.9918366,-0.1275153,0,0,0.1275153,0.9918366,0,0,0.9,7,1),["focal"]=45
}
SceneVariables { ["image_width"]=384,["image_height"]=216,["pixel_samples"]=2 }
'''
