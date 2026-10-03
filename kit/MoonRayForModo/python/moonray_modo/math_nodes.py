"""Standard graph math lowered into native MoonRay OpMap operations."""
import math

def rgb(value):return ('Rgb',[value]*3)
SCHEMAS={
 'lerp':{'bg':rgb(0),'fg':rgb(1),'mix':rgb(.5)},
 'smoothstep':{'in':rgb(0),'low':rgb(0),'high':rgb(1)},
 'contrast':{'in':rgb(0),'amount':rgb(1),'pivot':rgb(.5)},
 'luminance':{'in':rgb(0),'lumacoeffs':('Rgb',[.2722287,.6740818,.0536895])},
 'range':{'in':rgb(0),'inlow':rgb(0),'inhigh':rgb(1),'gamma':rgb(1),'outlow':rgb(0),'outhigh':rgb(1),'doclamp':('Bool',False)},
 'convert':{'in':rgb(0)},'sign':{'in':rgb(0)},'sqrt':{'in':rgb(0)},'exp':{'in':rgb(0)},
}
for name in ('ifgreater','ifgreatereq','ifequal'):
 SCHEMAS[name]={'value1':('Float',1),'value2':('Float',0),'in1':rgb(0),'in2':rgb(0)}

def emit(kind,path,parameters,inputs,definition):
 from .rdla import vector
 from .map_library import binding
 count=[0]
 def op(number,a,b='Rgb(0,0,0)'):
  name=path+'/math/'+str(count[0]);count[0]+=1
  return binding(definition('OpMap',name,{'operation':str(number),'op1':a,'op2':b}),'Rgb')
 def value(key):
  if key in inputs:return binding(inputs[key],'Rgb')
  v=parameters.get(key,SCHEMAS[kind][key][1]);return vector(v if isinstance(v,list) else [v]*3,'Rgb')
 def clamp(v,lo='Rgb(0,0,0)',hi='Rgb(1,1,1)'):return op(5,op(4,v,lo),hi)
 one='Rgb(1,1,1)'
 if kind=='lerp':out=op(0,value('bg'),op(2,op(1,value('fg'),value('bg')),value('mix')))
 elif kind=='contrast':out=op(0,op(2,op(1,value('in'),value('pivot')),value('amount')),value('pivot'))
 elif kind=='luminance':out=op(8,value('in'),value('lumacoeffs'))
 elif kind=='convert':out=value('in')
 elif kind=='sign':out=op(1,op(27,value('in')),op(25,value('in')))
 elif kind=='sqrt':out=op(6,value('in'),'Rgb(.5,.5,.5)')
 elif kind=='exp':out=op(6,vector([math.e]*3,'Rgb'),value('in'))
 elif kind=='smoothstep':
  t=clamp(op(3,op(1,value('in'),value('low')),op(1,value('high'),value('low'))))
  out=op(2,op(2,t,t),op(1,'Rgb(3,3,3)',op(2,'Rgb(2,2,2)',t)))
 elif kind=='range':
  t=op(3,op(1,value('in'),value('inlow')),op(1,value('inhigh'),value('inlow')))
  sign=op(1,op(27,t),op(25,t))
  t=op(2,op(6,op(15,t),op(3,one,value('gamma'))),sign)
  out=op(0,value('outlow'),op(2,t,op(1,value('outhigh'),value('outlow'))))
  if parameters.get('doclamp',False):out=clamp(out,op(5,value('outlow'),value('outhigh')),op(4,value('outlow'),value('outhigh')))
 else:
  condition=op({'ifgreater':27,'ifgreatereq':28,'ifequal':29}[kind],value('value1'),value('value2'))
  out=op(0,value('in2'),op(2,op(1,value('in1'),value('in2')),condition))
 return definition('OpMap',path,{'operation':'11','op1':out})
