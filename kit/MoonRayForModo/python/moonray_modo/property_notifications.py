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

# Windows of the kit's own that show a material, such as the graph editor, asked to look again.
watchers=[]

def notify():
    for watcher in list(watchers):
        try:watcher()
        except Exception:pass
    for event in list(Notifier.clients.values()):
        try:lx.object.CommandEvent(event).Event(lx.symbol.fCMDNOTIFY_CHANGE_ALL)
        except (RuntimeError,LookupError):pass
