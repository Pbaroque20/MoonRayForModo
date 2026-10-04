"""Shared mesh prototypes with individual affine instance shutter transforms."""
from .rdla import IDENTITY,matrix,node_matrix,string,array
from . import cryptomatte,lighting


def emit(mesh,index,tag,scene,crypto,lines):
 transforms=mesh['instances'];ends=mesh.get('instances_close',[]);identities=mesh.get('instance_ids',[])
 if not len(transforms)==len(ends)==len(identities):raise ValueError('Instance shutter samples and IDs must match')
 if scene.get('_paired_instance_motion'):
  data=cryptomatte.userdata(mesh,lines,cryptomatte.category(scene),scene,instances=True) if crypto and cryptomatte.category(scene)!='material' else None
  lines+=['  local movingInstance = RdlInstancerGeometry('+string('/modo/instances/'+str(index))+') {',
   '    ["method"] = 2,','    ["references"] = {geometry},',
   '    ["use_reference_xforms"] = false,','    ["use_reference_attributes"] = true,',
   '    ["xform_list"] = '+array(matrix(m) for m in transforms)+',',
   '    ["xform_list_close"] = '+array(matrix(m) for m in ends)+',']
  if data:lines.append('    ["primitive_attributes"] = {'+data+'},')
  lines+=['  }','  table.insert(geometries, movingInstance)',
   '  assign(movingInstance, "", %s, %s)'%(string(tag),string(lighting.owner(mesh)))]
  return
 for i,(identity,start,end) in enumerate(zip(identities,transforms,ends)):
  value=dict(mesh,instances=[start],instance_ids=[identity])
  data=cryptomatte.userdata(value,lines,cryptomatte.category(scene),scene,instances=True) if crypto and cryptomatte.category(scene)!='material' else None
  lines+=['  do','    local movingInstance = RdlInstancerGeometry('+string('/modo/instances/%d/%d'%(index,i))+') {',
   '      ["node_xform"] = '+node_matrix({'matrix':start,'matrix_close':end})+',',
   '      ["method"] = 2,','      ["references"] = {geometry},',
   '      ["use_reference_xforms"] = false,','      ["use_reference_attributes"] = true,',
   '      ["xform_list"] = {'+matrix(IDENTITY)+'},']
  if data:lines.append('      ["primitive_attributes"] = {'+data+'},')
  lines+=['    }','    table.insert(geometries, movingInstance)',
   '    assign(movingInstance, "", %s, %s)'%(string(tag),string(lighting.owner(mesh))),'  end']
