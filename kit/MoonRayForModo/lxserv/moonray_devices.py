"""Device Management (Preferences > MoonRay > Device Management): the processors and graphics cards XPU2 finds, a switch
for each, and the shaders compiled for every card (moonray_modo.devices).

The page has a slot for each of the first few cards and processor groups: a slot's sheet shows only where there is a
device for it (moonray.pref.cardShown0 ...), its name beside its switch."""
import os
import sys
package_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "python")
if package_root not in sys.path: sys.path.insert(0, package_root)
import lx
import lxifc
import lxu.command
from moonray_modo.property_notifications import Followed

NOTIFIER = 'moonray.devices'


class DevicesNotifier(lxifc.Notifier):
    clients = {}
    def noti_Name(self): return NOTIFIER
    def noti_SetArgs(self, args): pass
    def noti_Args(self): return ''
    def noti_AddClient(self, event): self.clients[event.__peekobj__()] = event
    def noti_RemoveClient(self, event): self.clients.pop(event.__peekobj__(), None)


def _notify():
    for event in list(DevicesNotifier.clients.values()):
        try: lx.object.CommandEvent(event).Event(lx.symbol.fCMDNOTIFY_CHANGE_ALL)
        except (RuntimeError, LookupError): pass


def _devices(kind):
    from moonray_modo import devices
    groups, cards = devices.listed()
    return cards if kind == 'card' else groups


def shown(kind, place):
    class Shown(Followed, lxu.command.BasicCommand):
        """Whether slot place of kind has a device: its sheet is shown."""
        WATCHED = ((NOTIFIER, ''),)
        def cmd_Flags(self): return lx.symbol.fCMD_UI
        def basic_Enable(self, msg): return place < len(_devices(kind))
        def basic_Execute(self, msg, flags): pass
    return Shown


def named(kind, place):
    class Named(Followed, lxu.command.BasicCommand):
        """The device in slot place of kind (read only)."""
        WATCHED = ((NOTIFIER, ''),)
        def __init__(self):
            super().__init__()
            self.dyna_Add('value', lx.symbol.sTYPE_STRING)
            self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self): return lx.symbol.fCMD_UI
        def basic_Enable(self, msg): return True
        def cmd_Query(self, index, query):
            from moonray_modo import devices
            listed = _devices(kind)
            if place >= len(listed): text = '(none)'
            elif kind == 'card': text = devices.card_label(listed[place])
            else: text = devices.group_label(listed[place], listed)
            lx.object.ValueArray(query).AddString(text)
        def basic_Execute(self, msg, flags): pass
    return Named


def switched(kind, place):
    class Switched(Followed, lxu.command.BasicCommand):
        """Slot place of kind on or off. The last device on cannot be switched off."""
        WATCHED = ((NOTIFIER, ''),)
        def __init__(self):
            super().__init__()
            self.dyna_Add('value', lx.symbol.sTYPE_BOOLEAN)
            self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
        def cmd_Flags(self): return lx.symbol.fCMD_UI
        def basic_Enable(self, msg): return place < len(_devices(kind))
        def cmd_Query(self, index, query):
            from moonray_modo import devices
            listed = _devices(kind)
            on = place < len(listed) and (devices.card_on(listed[place]) if kind == 'card' else devices.group_on(listed[place]))
            lx.object.ValueArray(query).AddInt(1 if on else 0)
        def basic_Execute(self, msg, flags):
            from moonray_modo import devices
            if not devices.switch(kind, place, bool(self.dyna_Int(0))):
                lx.out('MoonRay XPU2: one device at least stays on')
            _notify()
            # The Render item's form greys XPU2's processor switch by the devices on.
            from moonray_modo import property_notifications
            property_notifications.notify()
    return Switched


class Summary(Followed, lxu.command.BasicCommand):
    """What XPU2 finds and what is on (read only)."""
    WATCHED = ((NOTIFIER, ''),)
    def __init__(self):
        super().__init__()
        self.dyna_Add('value', lx.symbol.sTYPE_STRING)
        self.basic_SetFlags(0, lx.symbol.fCMDARG_QUERY)
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def cmd_Query(self, index, query):
        from moonray_modo import devices
        lx.object.ValueArray(query).AddString(devices.summary())
    def basic_Execute(self, msg, flags): pass


class Refresh(lxu.command.BasicCommand):
    """Look for the devices again (after a card is put in or a driver installed)."""
    def cmd_Flags(self): return lx.symbol.fCMD_UI
    def basic_Enable(self, msg): return True
    def basic_Execute(self, msg, flags):
        from moonray_modo import devices
        groups, cards = devices.listed(again=True)
        lx.out('MoonRay XPU2: %s' % devices.summary())
        _notify()


lx.bless(DevicesNotifier, NOTIFIER)
lx.bless(Summary, 'moonray.pref.devicesSummary')
lx.bless(Refresh, 'moonray.pref.devicesRefresh')
from moonray_modo.devices import CARD_SLOTS, GROUP_SLOTS
for _kind, _slots in (('card', CARD_SLOTS), ('group', GROUP_SLOTS)):
    for _place in range(_slots):
        lx.bless(shown(_kind, _place), 'moonray.pref.%sShown%d' % (_kind, _place))
        lx.bless(named(_kind, _place), 'moonray.pref.%sName%d' % (_kind, _place))
        lx.bless(switched(_kind, _place), 'moonray.pref.%sOn%d' % (_kind, _place))
