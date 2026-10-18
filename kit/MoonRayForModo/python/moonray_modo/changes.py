"""Conservative host notifications; scene access is deferred to the idle timer."""
import lx,lxifc

class Changes(lxifc.SceneItemListener):
    def __init__(self):
        self.full=True;self.items=set();self.service=lx.service.Listener();self.registered=False
        # Scenes closed and made since the panel last looked: the picture may be of a scene no longer open.
        self.closed=self.created=False
        try:self.service.AddListener(self);self.registered=True
        except (RuntimeError,LookupError):pass
    def invalidate(self,*args):self.full=True
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
        identity=self._place(item)
        if identity is None:self.full=True
        else:self.items.add(identity)
    def joined(self,graph,source,target,*args):
        try:
            if lx.object.SceneGraph(graph).Name()!='xfrmCore':self.full=True;return
        except (RuntimeError,LookupError,TypeError):self.full=True;return
        for item in (source,target):
            identity=self._place(item)
            if identity is not None:self.items.add(identity)
    def sil_ChannelValue(self,action,item,index):
        try:
            item=lx.object.Item(item)
            if item.ChannelName(index) in ('enable','render','visible','ptag','ptyp','effect','opacity'):
                self.full=True
            self.items.add(item.Ident())
        except (RuntimeError,LookupError):self.full=True
    def consume(self):
        result=(self.full or not self.registered,set(self.items));self.full=False;self.items.clear();return result
    def close(self):
        if self.registered:self.service.RemoveListener(self);self.registered=False
    def sil_SceneCreate(self,*args):self.full=self.created=True
    def sil_SceneDestroy(self,*args):self.full=self.closed=True
    sil_SceneClear=invalidate
    sil_ItemPostDelete=invalidate
    sil_ItemAdd=placed
    sil_ItemRemove=invalidate
    sil_ItemParent=placed
    sil_ItemChild=placed
    sil_ItemAddChannel=invalidate
    sil_ItemName=invalidate
    # Modo tells of the scene's name when the scene is first edited after it was opened or saved (its title gains a
    # mark), as well as when it is saved under another name. Neither changes what is in it.
    def sil_SceneFilename(self,*args):pass
    sil_ItemLocal=invalidate
    sil_ItemSource=invalidate
    sil_ItemPackage=invalidate
    sil_ItemTag=invalidate
    sil_ItemRemoveChannel=invalidate
    sil_LinkAdd=joined
    sil_LinkRemAfter=invalidate
    sil_LinkSet=joined
    sil_ChanLinkAdd=invalidate
    sil_ChanLinkRemAfter=invalidate
    sil_ChanLinkSet=invalidate

    sil_ItemChannelName=invalidate
    sil_ItemChannelDefault=invalidate
    sil_ItemChannelMinMax=invalidate
    sil_ItemChannelType=invalidate
