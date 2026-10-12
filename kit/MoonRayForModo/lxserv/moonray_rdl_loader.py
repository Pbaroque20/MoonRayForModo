# python
"""MoonRay scenes (.rdla, .rdlb) in Modo's File > Open and File > Import.

Modo asks each loader whether a file is its own. This one knows a MoonRay scene by its name, hands Modo a scene with
nothing in it yet, and then has MoonRay > Import MoonRay Scene read the file into it: the same importer, with its
window saying how far it has come and what it could not bring. Reading a scene is done by MoonRay's own reader in a
process of its own, which a loader cannot wait on without stopping Modo, so the scene is filled a moment after it
opens rather than as it opens."""
import os

import lx
import lxifc

KINDS = ('.rdla', '.rdlb')


class RdlLoader(lxifc.Loader):
    def __init__(self):
        self.path = None

    def load_Recognize(self, filename, loadInfo):
        if os.path.splitext(filename)[1].lower() not in KINDS or lx.service.Platform().IsHeadless():
            lx.throw(lx.result.NOTFOUND)
        self.path = filename
        info = lx.object.LoaderInfo(loadInfo)
        info.SetClass(lx.symbol.u_SCENE)
        info.SetFlags(0)
        # Modo wants to know what kind of item a scene's file is of before it will make the scene: without this it
        # fell over. It gives the scene one empty mesh of that kind, which is left there.
        target = lx.object.SceneLoaderTarget()
        target.set(loadInfo)
        target.SetRootType(lx.symbol.sITYPE_MESH)

    def load_LoadObject(self, loadInfo, monitor, dest):
        path = self.path
        from PySide2 import QtCore

        def bring():
            from moonray_modo.rdl_import_dialog import show
            show(path, True)
        # Once Modo has finished opening: the scene just made is then the current one, and commands may be run.
        QtCore.QTimer.singleShot(300, bring)

    def load_Cleanup(self):
        return lx.result.OK


tags = {
    lx.symbol.sLOD_CLASSLIST: lx.symbol.a_SCENE,
    lx.symbol.sLOD_DOSPATTERN: '*.rdla;*.rdlb',
    lx.symbol.sLOD_MACPATTERN: '*.rdla;*.rdlb',
    lx.symbol.sSRV_USERNAME: 'MoonRay Scene (RDL)',
}
lx.bless(RdlLoader, 'moonray.rdlLoader', tags)
