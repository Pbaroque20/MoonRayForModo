"""Modo command UI invalidation for scene-owned MoonRay settings."""
import lx
import lxifc

NAME='moonray.material.properties'

class Notifier(lxifc.Notifier):
    clients={}
    def noti_Name(self):return NAME
    def noti_SetArgs(self,args):pass
    def noti_Args(self):return ''
    def noti_AddClient(self,event):self.clients[event.__peekobj__()]=event
    def noti_RemoveClient(self,event):self.clients.pop(event.__peekobj__(),None)

class Followed:
    """For a command whose control looks again when told, ahead of BasicCommand in its bases. Modo's Python commands are asked
    this way only (BasicCommand has no basic_Notifier): a control with no client here keeps what it first drew until its form
    is drawn again. WATCHED: (notifier, args) pairs."""
    WATCHED=()
    def cmd_NotifyAddClient(self,argument,client):
        if getattr(self,'_notifications',None) is None:
            self._notifications=[lx.service.NotifySys().Spawn(name,args) for name,args in self.WATCHED]
        for notifier in self._notifications:notifier.AddClient(client)
    def cmd_NotifyRemoveClient(self,client):
        for notifier in getattr(self,'_notifications',None) or ():notifier.RemoveClient(client)

# Windows of the kit's own that show a material, such as the graph editor, asked to look again.
watchers=[]

def notify():
    for watcher in list(watchers):
        try:watcher()
        except Exception:pass
    for event in list(Notifier.clients.values()):
        try:lx.object.CommandEvent(event).Event(lx.symbol.fCMDNOTIFY_CHANGE_ALL)
        except (RuntimeError,LookupError):pass
