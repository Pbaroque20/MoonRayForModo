"""Deferred offline material export checks. Run explicitly after installation."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'kit/MoonRayForModo/python'))
from moonray_modo import shader_library as library

def main():
    shaders=library.catalog()
    assert len(shaders)==24
    for shader in shaders:
        lines=[]
        value={'native_shader':shader,'native_parameters':{},'color':[.5,.5,.5]}
        ref=library.emit(value,'/test/'+shader,[1000000000],lines,{})
        assert ref.startswith(shader+'(')
        assert any(line.startswith(shader+'(') for line in lines)
    base={'native_shader':'DwaMetalMaterial','native_parameters':{'roughness':.25},'color':[.5]*3}
    layered={'native_shader':'DwaLayerMaterial','native_parameters':{'material_A':{'material':'base'}},'color':[.5]*3}
    lines=[]
    library.emit(layered,'/layer',[1000000000],lines,{'base':base})
    assert next(i for i,line in enumerate(lines) if line.startswith('DwaMetalMaterial')) < next(i for i,line in enumerate(lines) if line.startswith('DwaLayerMaterial'))
    cyclic=dict(layered,native_parameters={'material_A':{'material':'self'}})
    try: library.attach_dependencies({'root':cyclic},{'self':cyclic})
    except ValueError: pass
    else: raise AssertionError('Cycle accepted')
    for parameters in ({'roughness':float('nan')},{'missing_attribute':1}):
        try: library.validate('DwaMetalMaterial',parameters)
        except ValueError: pass
        else: raise AssertionError('Invalid parameter accepted')
    print('Offline schema/export checks passed. Modo UI and rendered appearance still require separate validation.')

if __name__=='__main__': main()
