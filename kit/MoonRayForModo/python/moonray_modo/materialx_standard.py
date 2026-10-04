"""Standard Surface controls with explicit limits where MoonRay differs."""
import copy,math

SPECIAL={'specular_rotation','transmission_extra_roughness','opacity','specular_color',
 'subsurface','subsurface_color','subsurface_radius','subsurface_scale','subsurface_anisotropy',
 'transmission_depth','transmission_scatter','transmission_scatter_anisotropy','transmission_dispersion',
 'coat_anisotropy','coat_rotation','coat_affect_color','coat_affect_roughness','thin_film_thickness','thin_film_IOR','tangent'}


def apply(item,ports,graph,resolve,parse,identity):
 def literal(name,default):
  port=ports.get(name)
  if port is None or not any(k in port.attrib for k in ('value','nodename','nodegraph')):return default
  if 'value' not in port.attrib:return None
  return parse(port)
 def new(kind,parameters=None,inputs=None):
  identity='n'+str(len(graph['nodes']))
  graph['nodes'][identity]={'type':kind,'parameters':parameters or {},'inputs':inputs or {},'position':[0,200]}
  return identity
 def source(name,default):
  port=ports.get(name)
  if port is not None and any(k in port.attrib for k in ('value','nodename','nodegraph')):return resolve(port)
  return new('constant',{'value':default if isinstance(default,list) else [default]*3})
 rotation=literal('specular_rotation',0)
 if rotation is None:
  angle=new('multiply',{'in2':[2*math.pi]*3},{'in1':source('specular_rotation',0)})
  cosine=new('OpMap',{'operation':22},{'op1':angle});sine=new('OpMap',{'operation':21},{'op1':angle})
  item['inputs']['shading_tangent']=new('combine',{}, {'in1':cosine,'in2':sine})
 elif rotation:item['parameters']['shading_tangent']=[math.cos(rotation*2*math.pi),math.sin(rotation*2*math.pi)]
 roughness=literal('transmission_extra_roughness',0)
 if roughness is None or roughness!=0:
  summed=new('add',{}, {'in1':source('specular_roughness',.2),'in2':source('transmission_extra_roughness',0)})
  item['parameters']['use_independent_transmission_roughness']=True
  item['inputs']['independent_transmission_roughness']=new('clamp',{}, {'in':summed})
 opacity=literal('opacity',[1,1,1])
 if opacity is None:
  # MoonRay presence is scalar; a connected color opacity uses its luminance.
  item['inputs']['presence']=new('luminance',{}, {'in':source('opacity',[1,1,1])})
 else:
  rgb=opacity if isinstance(opacity,list) else [opacity]*3
  if max(rgb)-min(rgb)>1e-6:raise ValueError('MoonRay presence cannot represent colored MaterialX opacity; use a grayscale mask')
  item['parameters']['presence']=rgb[0]
 neutral={'specular_color':[1,1,1],'transmission_depth':0,'transmission_scatter':[0,0,0],
 'transmission_scatter_anisotropy':0,'transmission_dispersion':0,'subsurface_anisotropy':0,
 'coat_anisotropy':0,'coat_rotation':0,'coat_affect_color':0,'coat_affect_roughness':0,'thin_film_thickness':0}
 for name,value in neutral.items():
  if literal(name,value)!=value:raise ValueError('MaterialX '+name+' has no equivalent in this Standard Surface translation')
 # These values have no effect when the corresponding lobe is disabled.
 for name in ('thin_film_IOR',):
  if literal(name,0) is None:raise ValueError('Unsupported connected MaterialX input: '+name)
 tangent=ports.get('tangent')
 if tangent is not None and any(k in tangent.attrib for k in ('value','nodename','nodegraph')):
  raise ValueError('World-space MaterialX tangent requires conversion to the shading UV basis; use specular_rotation')

 weight=literal('subsurface',0)
 if weight is not None and weight==0:return identity
 radius=source('subsurface_radius',[1,1,1])
 components=[new('swizzle',{'channels':channel},{'in':radius}) for channel in 'rgb']
 largest=new('OpMap',{'operation':4},{'op1':components[0],'op2':components[1]})
 largest=new('OpMap',{'operation':4},{'op1':largest,'op2':components[2]})
 largest=new('OpMap',{'operation':4,'op2':[1e-9]*3},{'op1':largest})
 normalized=new('divide',{}, {'in1':radius,'in2':largest})
 distance=new('multiply',{}, {'in1':largest,'in2':source('subsurface_scale',1)})
 foreground=copy.deepcopy(item)
 foreground['parameters'].pop('scattering_radius',None);foreground['parameters'].pop('scattering_color',None)
 foreground['inputs']['scattering_radius']=distance;foreground['inputs']['scattering_color']=normalized
 base=foreground['inputs'].get('albedo') or new('constant',{'value':foreground['parameters'].get('albedo',[.8]*3)})
 foreground['parameters'].pop('albedo',None)
 foreground['inputs']['albedo']=new('multiply',{}, {'in1':base,'in2':source('subsurface_color',[1,1,1])})
 scattering=new(foreground['type'],foreground['parameters'],foreground['inputs'])
 params={};inputs={'material_A':scattering,'material_B':identity}
 if weight is None:inputs['mask']=source('subsurface',0)
 else:params['mask']=max(0,min(1,float(weight)))
 return new('DwaLayerMaterial',params,inputs)
