"""XPU2's handed-on tiles in the preview (buckets.py, render.py, viewer.py): where the GPU deferred samples to the CPU
(orange, half seen through) and where its provisional samples wait to be rendered again in full (blue), each tile taken
away once XPU2 no longer reports it. The drawing checks need the Modo-compatible PySide2 and are skipped without it."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import buckets

try:
    from PySide2 import QtCore,QtGui,QtWidgets
except ImportError:
    QtWidgets=None


class HandoffLines(unittest.TestCase):
    def test_lines_parse_as_tiles(self):
        self.assertEqual(buckets.parse('@@MODO_DEFERRED_TILES 3 64 32 0,0,8,8 16,8,32,24'),(3,64,32,[(0,0,8,8),(16,8,32,24)]))
        self.assertEqual(buckets.parse('@@MODO_PROVISIONAL_TILES 3 64 32'),(3,64,32,[]))
    def test_bounds_as_other_lines(self):
        for line in ('@@MODO_DEFERRED_TILES 3 64 32 0,0,65,8','@@MODO_PROVISIONAL_TILES 3 0 32','@@MODO_DEFERRED_TILES 3 64 32 8,0,8,8',
                     '@@MODO_PROVISIONAL_TILES 3 64 32 x','@@MODO_DEFERRED_TILES 3 64 32 '+' '.join(['0,0,8,8']*513)):
            self.assertIsNone(buckets.parse(line),line[:60])
    def test_kinds(self):
        self.assertEqual(buckets.handoff_kind('@@MODO_DEFERRED_TILES 1 8 8'),'deferred')
        self.assertEqual(buckets.handoff_kind('@@MODO_PROVISIONAL_TILES 1 8 8'),'provisional')
        for line in ('@@MODO_TILES 1 8 8','@@MODO_GPU_WORKERS 1 8 8','@@MODO_DEFERRED_TILESX 1 8 8','',' '):
            self.assertIsNone(buckets.handoff_kind(line))
    def test_other_lines_unchanged(self):
        self.assertEqual(buckets.parse('@@MODO_TILES 2 17 19 0,0,8,8 16,16,17,19'),(2,17,19,[(0,0,8,8),(16,16,17,19)]))
        self.assertIsNone(buckets.parse('@@MODO_SESSION DONE 2'))
    def test_routes(self):
        def routed(line):return buckets.route(line,buckets.parse(line))
        self.assertEqual(routed('@@MODO_DEFERRED_TILES 2 64 32 0,0,8,8'),('workers',('deferred',2,64,32,[(0,0,8,8)])))
        self.assertEqual(routed('@@MODO_PROVISIONAL_TILES 2 64 32'),('workers',('provisional',2,64,32,[])))
        # As before: the GPU's cells marked, the workers' squares and the tiles as they are.
        self.assertEqual(routed('@@MODO_GPU_WORKERS 2 64 32 0,0,64,32'),('workers',('gpu',2,64,32,[(0,0,64,32)])))
        self.assertEqual(routed('@@MODO_WORKERS 2 64 32 0,0,8,8'),('workers',(2,64,32,[(0,0,8,8)])))
        self.assertEqual(routed('@@MODO_TILES 2 64 32 0,0,8,8'),('buckets',(2,64,32,[(0,0,8,8)])))


@unittest.skipIf(QtWidgets is None,'Requires the Modo-compatible PySide2 environment')
class HandoffDrawing(unittest.TestCase):
    W,H=256,192
    GREY=(100,100,100)
    @classmethod
    def setUpClass(cls):
        cls.app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        from moonray_modo.viewer import SoftwarePreview
        cls.Preview=SoftwarePreview
    def setUp(self):
        self.view=self.Preview();self.view.resize(self.W,self.H)
        picture=QtGui.QImage(self.W,self.H,QtGui.QImage.Format_RGB32);picture.fill(QtGui.QColor(*self.GREY))
        self.view.set_image(picture)
        # No crest fading over the picture, so its pixels are the picture's and the overlay's alone.
        self.view._crest_fade=None
    def tearDown(self):
        self.view.close();self.view.deleteLater()
    def pixel(self,x,y):
        """The widget's pixel at (x, y) from its top left, as drawn."""
        shot=self.view.grab().toImage()
        colour=QtGui.QColor(shot.pixel(x,y))
        return colour.red(),colour.green(),colour.blue()
    def tell(self,kind,rectangles,serial=4,size=None):
        width,height=size or (self.W,self.H)
        self.view.set_workers((kind,serial,width,height,list(rectangles)))
    def blend(self,colour):
        r,g,b,a=colour;k=a/255.
        return tuple(round(c*k+grey*(1-k)) for c,grey in zip((r,g,b),self.GREY))
    def near(self,got,want):
        return all(abs(a-b)<=3 for a,b in zip(got,want))

    def test_deferred_orange_then_gone(self):
        # The tile (8, 0)-(16, 8) in the film's coordinates (rows from the bottom) is the widget's bottom row of tiles.
        self.tell('deferred',[(8,0,16,8)])
        orange=self.blend(self.Preview.HANDOFF_COLOURS['deferred'])
        self.assertTrue(self.near(self.pixel(12,self.H-4),orange),self.pixel(12,self.H-4))
        self.assertEqual(self.pixel(4,self.H-4),self.GREY)  # the tile beside it
        self.assertEqual(self.pixel(12,4),self.GREY)  # the top row
        self.tell('deferred',[])
        self.assertEqual(self.pixel(12,self.H-4),self.GREY)
    def test_provisional_blue_then_gone_tile_by_tile(self):
        blue=self.blend(self.Preview.HANDOFF_COLOURS['provisional'])
        self.tell('provisional',[(0,184,8,192),(248,0,256,8)])
        self.assertTrue(self.near(self.pixel(4,4),blue),self.pixel(4,4))
        self.assertTrue(self.near(self.pixel(252,self.H-4),blue),self.pixel(252,self.H-4))
        # One rendered: only the other stays.
        self.tell('provisional',[(248,0,256,8)])
        self.assertEqual(self.pixel(4,4),self.GREY)
        self.assertTrue(self.near(self.pixel(252,self.H-4),blue))
    def test_both_kinds_at_once(self):
        self.tell('deferred',[(0,0,8,8)]);self.tell('provisional',[(0,0,8,8),(8,0,16,8)])
        both=self.pixel(4,self.H-4);blue=self.pixel(12,self.H-4)
        self.assertNotEqual(both,blue)
        self.assertTrue(self.near(blue,self.blend(self.Preview.HANDOFF_COLOURS['provisional'])))
        # The deferred kind gone, the provisional kind stays where it was.
        self.tell('deferred',[])
        self.assertTrue(self.near(self.pixel(4,self.H-4),blue))
    def test_hidden_with_handoff_tiles_off(self):
        # Options > Show Handoff Tiles, a switch of its own (the user's ask): off, nothing is filled.
        self.tell('deferred',[(0,0,8,8)])
        self.view.set_show_handoff(False)
        self.assertEqual(self.pixel(4,self.H-4),self.GREY)
        self.view.set_show_handoff(True)
        self.assertNotEqual(self.pixel(4,self.H-4),self.GREY)
    def test_shown_with_buckets_off(self):
        self.tell('deferred',[(0,0,8,8)])
        self.view.set_show_buckets(False)
        self.assertNotEqual(self.pixel(4,self.H-4),self.GREY)
    def test_not_drawn_over_another_size(self):
        self.tell('deferred',[(0,0,8,8)],size=(128,96))
        self.assertEqual(self.pixel(4,self.H-4),self.GREY)
    def test_cleared_with_the_buckets(self):
        self.tell('deferred',[(0,0,8,8)]);self.tell('provisional',[(8,0,16,8)])
        self.view.set_buckets(None)
        self.assertEqual(self.view.handoff,{})
        self.assertEqual(self.pixel(4,self.H-4),self.GREY);self.assertEqual(self.pixel(12,self.H-4),self.GREY)
    def test_other_worker_packets_unchanged(self):
        self.view.set_workers(('gpu',4,self.W,self.H,[(0,0,64,64)]))
        self.assertIsNotNone(self.view.gpu_workers)
        self.view.set_workers((4,self.W,self.H,[(0,0,8,8)]))
        self.assertEqual(self.view.workers,(4,self.W,self.H,[(0,0,8,8)]))
        self.assertEqual(self.view.handoff,{})


if __name__=='__main__':
    unittest.main()
