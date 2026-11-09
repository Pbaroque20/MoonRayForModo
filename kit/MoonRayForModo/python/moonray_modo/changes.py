"""Conservative host notifications; scene access is deferred to the idle timer."""
import lx,lxifc

class Changes(lxifc.SceneItemListener):
    def __init__(self):
        self.full=True;self.items=set();self.service=lx.service.Listener();self.registered=False
        # The items whose channels changed, beside items (a material's tag alone is told of in tagged): consume hands
        # them on as consumed_channels, so a material's tag rewritten with nothing to render anew can be told apart.
        self.channel_items=set();self.consumed_channels=set()
        # Scenes closed and made since the panel last looked: the picture may be of a scene no longer open.
        self.closed=self.created=False
        # Whether an item that is not the Schematic's own was removed since Modo last told of deletions (deleted).
        self._removed_other=False
        # Registered through one COM object kept for it, as Modo's SDK asks: Modo's Python makes a new one at every call,
        # so RemoveListener(self) named one Modo never had ('not found'), the listener stayed for good, and the panel's
        # closing (dispose) stopped there, its renderer left running into Modo's exit, which crashed.
        self.com=lx.object.Unknown(self)
        try:self.service.AddListener(self.com);self.registered=True
        except (RuntimeError,LookupError):pass
    def invalidate(self,*args):self.full=True
    # The Schematic's own items (a node, a backdrop, a note) and workspaces (assembly groups), the graph that ties a
    # node to its item, and the one that puts items in a workspace: none of them is anything a render reads. A node
    # moved, made, wired again as it was, a workspace filled or a note typed in is no edit, and realtime does not start
    # again for it (each was taken for a change to the scene, read whole).
    SCHEMATIC_TYPES=('schmNode','backdropSchm','noteSchm')
    SCHEMATIC_GRAPHS=('schmItem',)
    def _kind(self,name):
        """An item type's code by its name, or None where Modo has no such type."""
        held=self.__dict__.setdefault('_kinds',{})
        if name not in held:
            try:held[name]=lx.service.Scene().ItemTypeLookup(name)
            except (RuntimeError,LookupError):held[name]=None
        return held[name]
    def _schematic(self,item):
        """Whether an item is one of the Schematic's own: a node, a backdrop or a note, or a workspace (a group whose
        group type is assembly, as Modo makes one). Where it cannot be told, it is not."""
        try:
            item=lx.object.Item(item)
            kind=item.Type()
            if kind in [self._kind(name) for name in self.SCHEMATIC_TYPES]:return True
            if kind!=self._kind('group'):return False
            try:return lx.object.StringTag(item).Get(lx.symbol.i_GROUP_TYPE if hasattr(lx.symbol,'i_GROUP_TYPE') else 0x47545950)=='assembly'
            except (RuntimeError,LookupError,TypeError):return False
        except (RuntimeError,LookupError,TypeError):return False
    def _new_group(self,item):
        """Whether an item is a group: one newly made holds nothing yet, and what it comes to hold, or any channel or
        link given it, is told of by itself. (A Schematic workspace is made so, its type set after.)"""
        try:return lx.object.Item(item).Type()==self._kind('group')
        except (RuntimeError,LookupError,TypeError):return False
    def _empty_group(self,item):
        """Whether an item is a group with no member: its tags, package or name are nothing a render reads."""
        if not self._new_group(item):return False
        try:
            item=lx.object.Item(item)
            graph=lx.object.ItemGraph(lx.object.Scene(item.Context()).GraphLookup('itemGroups'))
            return graph.FwdCount(item)==0
        except (RuntimeError,LookupError,TypeError):return False
    def _beside(self,item):
        """Whether what was told of an item (a tag, a package, its name) leaves the render as it was: the item is the
        Schematic's own, or a group with no member yet."""
        return self._schematic(item) or self._empty_group(item)
    def packaged(self,item,*args):
        if not self._beside(item):self.full=True
    @staticmethod
    def _graph_name(graph):
        """A link notice's graph, by name: Modo hands the name itself (a graph object, where one is given, is asked its
        name). None where it cannot be told."""
        if isinstance(graph,str):return graph
        try:return lx.object.SceneGraph(graph).Name()
        except (RuntimeError,LookupError,TypeError):return None
    def _schematic_link(self,graph,source,target):
        """Whether a link is the Schematic's own: on its node graph, or putting an item in a workspace."""
        name=self._graph_name(graph)
        if name is None:return False
        if name in self.SCHEMATIC_GRAPHS:return True
        # An item put in or taken out of a workspace; a workspace, or a group with no member, put among the scene's groups.
        # (An item taken out of any other group is a change, even where it was the last: a light's group may be one.)
        if name=='itemGroups':return self._schematic(source) or self._schematic(target)
        return name=='groups' and (self._beside(source) or self._beside(target))
    def item_changed(self,item,*args):
        """An item removed or renamed: the scene is read again, unless it is one of the Schematic's own (or, renamed, a
        group with no member yet)."""
        if self._beside(item):return
        self.full=True;self._removed_other=True
    def deleted(self,*args):
        """Items deleted, as Modo tells after the removal of each (which names it): the scene is read again unless all
        that went since were the Schematic's own."""
        if getattr(self,'_removed_other',True):self.full=True
        self._removed_other=False
    def unlinked(self,graph,source,target,*args):
        if not self._schematic_link(graph,source,target):self.full=True
    # An item moved for the first time is given a place of its own: Modo adds a transform item and joins it to the
    # item moved. That is a move like any other, not a change to what the scene holds, and is told of as one: taken
    # for a change to the scene, it had the whole scene read again in the middle of the first drag of anything.
    PLACES=('translation','rotation','scale','transform')
    def _place(self,item):
        """The identity of a transform item, or None for anything else or where it cannot be told."""
        try:
            item=lx.object.Item(item)
            kinds=getattr(self,'_place_types',None)
            if kinds is None:
                scenes=lx.service.Scene();kinds=self._place_types={scenes.ItemTypeLookup(name) for name in self.PLACES}
            return item.Ident() if item.Type() in kinds else None
        except (RuntimeError,LookupError,TypeError):return None
    def placed(self,item,*args):
        if self._schematic(item):return
        identity=self._place(item)
        if identity is not None:self.items.add(identity);return
        if self._new_group(item):return
        self.full=True
    def parented(self,item,*args):
        """An item put under another: the scene is read again, unless it is one of the Schematic's own."""
        if self._schematic(item):return
        identity=self._place(item)
        if identity is None:self.full=True
        else:self.items.add(identity)
    def joined(self,graph,source,target,*args):
        if self._schematic_link(graph,source,target):return
        # (Modo hands the graph's name; asked as an object, every link was taken for a change to the scene.)
        if self._graph_name(graph)!='xfrmCore':self.full=True;return
        for item in (source,target):
            identity=self._place(item)
            if identity is not None:self.items.add(identity)
    def tagged(self,item,*args):
        """A tag set on an item: on a material, its MoonRay settings and graph (properties.TAG), which the graph editor and
        the Properties panel write at every change. That is the material's edit like a channel's, told as one (the edit is
        then the materials', incremental.classify): taken for a change to the scene, each step of a value in the graph
        editor read the whole scene again, meshes and all. On anything else a tag may say anything: the scene is read."""
        try:
            item=lx.object.Item(item)
            kind=lx.service.Scene().ItemTypeName(item.Type())
            from .incremental import MATERIALS
            if kind in MATERIALS or kind.startswith('material.'):self.items.add(item.Ident())
            elif not self._beside(item):self.full=True
        except (RuntimeError,LookupError,TypeError):self.full=True
    def sil_ChannelValue(self,action,item,index):
        try:
            item=lx.object.Item(item)
            # A Schematic node moved or resized, a note or backdrop changed: nothing a render reads.
            if self._schematic(item):return
            if item.ChannelName(index) in ('enable','render','visible','ptag','ptyp','effect','opacity'):
                self.full=True
            self.items.add(item.Ident());self.channel_items.add(item.Ident())
        except (RuntimeError,LookupError):self.full=True
    def consume(self):
        result=(self.full or not self.registered,set(self.items));self.full=False;self.items.clear()
        self.consumed_channels=set(self.channel_items);self.channel_items.clear();return result
    def close(self):
        if self.registered:
            self.registered=False
            try:self.service.RemoveListener(self.com)
            except (RuntimeError,LookupError):pass
    def sil_SceneCreate(self,*args):self.full=self.created=True
    def sil_SceneDestroy(self,*args):self.full=self.closed=True
    sil_SceneClear=invalidate
    sil_ItemPostDelete=deleted
    sil_ItemAdd=placed
    sil_ItemRemove=item_changed
    sil_ItemParent=parented
    sil_ItemChild=parented
    sil_ItemAddChannel=invalidate
    sil_ItemName=item_changed
    # Modo tells of the scene's name when the scene is first edited after it was opened or saved (its title gains a
    # mark), as well as when it is saved under another name. Neither changes what is in it.
    def sil_SceneFilename(self,*args):pass
    sil_ItemLocal=invalidate
    sil_ItemSource=invalidate
    sil_ItemPackage=packaged
    sil_ItemTag=tagged
    sil_ItemRemoveChannel=invalidate
    sil_LinkAdd=joined
    sil_LinkRemAfter=unlinked
    sil_LinkSet=joined
    sil_ChanLinkAdd=invalidate
    sil_ChanLinkRemAfter=invalidate
    sil_ChanLinkSet=invalidate

    sil_ItemChannelName=invalidate
    sil_ItemChannelDefault=invalidate
    sil_ItemChannelMinMax=invalidate
    sil_ItemChannelType=invalidate
