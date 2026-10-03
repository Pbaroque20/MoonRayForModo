"""Conservative host notifications; scene access is deferred to the idle timer."""
import lx,lxifc

class Changes(lxifc.SceneItemListener):
    def __init__(self):
        self.full=True;self.items=set();self.service=lx.service.Listener();self.registered=False
        try:self.service.AddListener(self);self.registered=True
        except (RuntimeError,LookupError):pass
    def invalidate(self,*args):self.full=True
    def sil_ChannelValue(self,action,item,index):
        try:self.items.add(lx.object.Item(item).Ident())
        except (RuntimeError,LookupError):self.full=True
    def consume(self):
        result=(self.full or not self.registered,set(self.items));self.full=False;self.items.clear();return result
    def close(self):
        if self.registered:self.service.RemoveListener(self);self.registered=False
    sil_SceneCreate=invalidate
    sil_SceneDestroy=invalidate
    sil_SceneClear=invalidate
    sil_ItemPostDelete=invalidate
    sil_ItemAdd=invalidate
    sil_ItemRemove=invalidate
    sil_ItemParent=invalidate
    sil_ItemChild=invalidate
    sil_ItemAddChannel=invalidate
    sil_ItemName=invalidate
    sil_SceneFilename=invalidate
    sil_ItemLocal=invalidate
    sil_ItemSource=invalidate
    sil_ItemPackage=invalidate
    sil_ItemTag=invalidate
    sil_ItemRemoveChannel=invalidate
    sil_LinkAdd=invalidate
    sil_LinkRemAfter=invalidate
    sil_LinkSet=invalidate
    sil_ChanLinkAdd=invalidate
    sil_ChanLinkRemAfter=invalidate
    sil_ChanLinkSet=invalidate
