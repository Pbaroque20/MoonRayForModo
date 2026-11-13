"""Which groups of a material's inputs start open, the same in the graph editor's list (node_editor.default_folds) and in
Modo's form for the material (tools/generate_material_item_forms.py): the everyday ones, Diffuse and Specular; a kind
with neither (a map, a light filter) has its first group open, not every group folded."""
OPEN = ('Diffuse', 'Specular')


def opened(groups):
    """The names among groups (in their order) that start open."""
    groups = list(dict.fromkeys(groups))
    found = {group for group in groups if str(group).casefold() in {name.casefold() for name in OPEN}}
    return found or set(groups[:1])
