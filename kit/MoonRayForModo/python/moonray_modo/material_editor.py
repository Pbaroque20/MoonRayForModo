"""Schema-driven native MoonRay material editor; invoked inside an undoable command."""
import json
from PySide2 import QtWidgets
from . import shader_library, properties


def choose():
    names=['Modo controls (DwaBaseMaterial)']+sorted(shader_library.catalog())
    value,ok=QtWidgets.QInputDialog.getItem(None,'MoonShine Material','Material type',names,0,False)
    return (None if value==names[0] else value) if ok else False


def edit(item, scene):
    settings=properties.read(item)
    dialog=QtWidgets.QDialog()
    dialog.setWindowTitle('MoonShine Material — '+item.name)
    dialog.resize(760,680)
    layout=QtWidgets.QVBoxLayout(dialog)
    types=QtWidgets.QComboBox()
    types.addItems(sorted(shader_library.catalog()))
    types.setCurrentText(settings.get('native_shader') or 'DwaBaseMaterial')
    layout.addWidget(QtWidgets.QLabel("MoonRay material override"))
    layout.addWidget(types)
    info=QtWidgets.QLabel('Saving selects a native MoonRay material override for this Shader Tree material. Its native properties replace the translated Modo surface controls; compatible image layers still bind. Choose Modo controls in the main material dropdown to return to Modo shading.\nHair materials require strands; use the node editor for connected inputs.')
    info.setWordWrap(True);layout.addWidget(info)
    search=QtWidgets.QLineEdit();search.setPlaceholderText('Filter parameters');layout.addWidget(search)
    scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);layout.addWidget(scroll)
    editors={}; rows=[]; drafts={settings.get('native_shader') or 'DwaBaseMaterial':settings.get('native_parameters',{})}
    current=[None]
    def values():
        result={}
        for key,(widget,spec) in editors.items():
            if isinstance(widget,QtWidgets.QComboBox):
                value=widget.currentData()
                if value is None: continue
            else:
                text=widget.text().strip()
                if not text: continue
                if spec['type']=='String': value=text
                else:
                    try: value=json.loads(text)
                    except ValueError: raise ValueError(key+': enter a number or JSON array such as [1, 0.5, 0]')
            result[key]=value
        return shader_library.validate(current[0],result)
    def filter_rows(*args):
        text=search.text().lower()
        for label,widget in rows:
            visible=text in label.text().lower() or text in widget.toolTip().lower()
            label.setVisible(visible);widget.setVisible(visible)
    def populate(name):
        if current[0]:
            try: drafts[current[0]]=values()
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(dialog,'Invalid parameter',str(exc))
                types.blockSignals(True);types.setCurrentText(current[0]);types.blockSignals(False);return
        current[0]=name;editors.clear();rows.clear()
        container=QtWidgets.QWidget();form=QtWidgets.QFormLayout(container)
        params=drafts.get(name,{})
        for key,spec in sorted(shader_library.catalog()[name]['attributes'].items(),key=lambda kv:(kv[1].get('group',''),kv[0])):
            kind=spec['type'];value=params.get(key)
            if kind in ('Bool','SceneObject*') or 'enum' in spec:
                widget=QtWidgets.QComboBox();widget.addItem('Default: '+str(spec.get('default','')),None)
                if kind=='Bool':
                    widget.addItem('Off',False);widget.addItem('On',True)
                elif kind=='SceneObject*':
                    interface=spec.get('interface','')
                    for candidate in scene.items('advancedMaterial',superType=False):
                        shader=properties.read(candidate).get('native_shader')
                        if candidate.id!=item.id and shader and shader_library.compatible(shader,interface):
                            widget.addItem(candidate.name,{'material':candidate.id})
                    if widget.count()==1: widget.setToolTip('No compatible native material inputs. Create an input material first.')
                else:
                    for label,number in spec['enum'].items(): widget.addItem(label,int(number))
                if value is not None:
                    match=next((i for i in range(widget.count()) if widget.itemData(i)==value),-1)
                    if match<0: widget.addItem('Missing reference (repair before rendering)',value);match=widget.count()-1
                    widget.setCurrentIndex(match)
            else:
                widget=QtWidgets.QLineEdit()
                widget.setPlaceholderText('Default: '+str(spec.get('default','')))
                if value is not None: widget.setText(value if kind=='String' else json.dumps(value))
            widget.setToolTip(widget.toolTip()+'\n'+str(spec.get('comment',''))+'\nType: '+kind)
            label=QtWidgets.QLabel(str(spec.get('group',''))+' / '+key)
            form.addRow(label,widget);editors[key]=(widget,spec);rows.append((label,widget))
        old=scroll.takeWidget()
        if old: old.deleteLater()
        scroll.setWidget(container);filter_rows()
    types.currentTextChanged.connect(populate);search.textChanged.connect(filter_rows)
    buttons=QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save|QtWidgets.QDialogButtonBox.Cancel)
    layout.addWidget(buttons)
    def save():
        try:
            params=values()
            library={candidate.id:properties.read(candidate) for candidate in scene.items('advancedMaterial',superType=False)}
            native=dict(settings,moonshine_override=True,native_shader=current[0],native_parameters=params,shader='DwaBaseMaterial')
            graph=native.get('node_graph')
            if graph:
                if graph['nodes'][graph['root']]['type']!=current[0]: native.pop('node_graph',None)
                else:
                    import copy
                    graph=copy.deepcopy(graph);root=graph['nodes'][graph['root']]
                    old=root.get('parameters',{})
                    for key in set(old)|set(params):
                        if old.get(key)!=params.get(key): root.setdefault('inputs',{}).pop(key,None)
                    root['parameters']=params;native['node_graph']=graph
            library[item.id]=native
            shader_library.attach_dependencies({'selected':dict(native)},library)
            properties.write(item,native)
            dialog.accept()
        except (ValueError,KeyError) as exc: QtWidgets.QMessageBox.warning(dialog,'Invalid material',str(exc))
    def preview_draft():
        import copy
        native=copy.deepcopy(settings)
        native.update(native_shader=current[0],native_parameters=values(),shader='DwaBaseMaterial')
        graph=native.get('node_graph')
        if graph:
            root=graph['nodes'][graph['root']]
            if root['type']!=current[0]:native.pop('node_graph',None)
            else:
                old=root.get('parameters',{});params=native['native_parameters']
                for key in set(old)|set(params):
                    if old.get(key)!=params.get(key):root.setdefault('inputs',{}).pop(key,None)
                root['parameters']=params
        return native
    def preview_widget():
        from .material_preview import show
        show(item,preview_draft,dialog)
    preview=QtWidgets.QPushButton('Preview on MoonRay Widget')
    preview.clicked.connect(preview_widget);layout.insertWidget(2,preview)
    dialog.finished.connect(lambda *_:getattr(dialog,'_widget_preview',None) and dialog._widget_preview.close())
    buttons.accepted.connect(save);buttons.rejected.connect(dialog.reject)
    populate(types.currentText());dialog.exec_()
