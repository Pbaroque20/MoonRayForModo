"""Real Qt image checks for material-library thumbnail precedence; no Modo/rendering required."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from PySide2 import QtCore,QtGui,QtWidgets
from moonray_modo.asset_browser import picture,tile,ball
app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
class Thumbnails(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/'paint.moonmat.json'
  self.path.write_text(json.dumps({'format':1,'shader':'DwaBaseMaterial','parameters':{'albedo':[1,0,0]}}))
  self.row={'path':str(self.path),'category':'Saved materials'}
 def image(self,path,color):
  im=QtGui.QImage(80,40,QtGui.QImage.Format_RGB32);im.fill(QtGui.QColor(color));assert im.save(str(path),'PNG')
 def check_color(self,color):
  im=picture(self.row,40);self.assertEqual((im.width(),im.height()),(40,20));self.assertEqual(im.pixelColor(20,10),QtGui.QColor(color))
 def test_exact_sidecar_beats_material_drawing(self):
  self.image(self.path.with_suffix('.png'),'blue');self.check_color('blue')
 def test_simple_stem_and_exact_precedence(self):
  self.image(self.path.with_name('paint.png'),'green');self.check_color('green')
  self.image(self.path.with_suffix('.png'),'blue');self.check_color('blue')
 def test_graph_uses_sidecar_without_evaluating_graph(self):
  self.path.write_text(json.dumps({'format':2,'materials':{'root':{'settings':{}}}}))
  self.image(self.path.with_suffix('.png'),'magenta');self.check_color('magenta')
 def test_graph_without_sidecar_is_labelled_tile(self):
  self.path.write_text(json.dumps({'format':2}));self.assertEqual(picture(self.row,40),tile('Graph','#70747c',40))
 def test_corrupt_sidecar_falls_back(self):
  self.path.with_suffix('.png').write_bytes(b'not an image')
  self.assertEqual(picture(self.row,40),ball([1,0,0],False,.4,0,40))
 def test_texture_itself_remains_first(self):
  p=self.path.with_name('texture.png');self.image(p,'yellow');self.image(p.with_suffix('.jpg'),'blue')
  im=picture({'path':str(p)},40);self.assertEqual(im.pixelColor(20,10),QtGui.QColor('yellow'))
if __name__=='__main__':unittest.main()
