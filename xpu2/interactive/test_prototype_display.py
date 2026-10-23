import array,unittest
from prototype_service import Frame
from prototype_preview import display_ppm
from protocol_model import Epoch

class DisplayTests(unittest.TestCase):
    def test_display_does_not_change_raw_and_flips_rows(self):
        values=array.array('f',[1,0,0,1, 0,0,1,1]);raw=values.tobytes()
        f=Frame(1,Epoch(1,1,1,1),'D',False,True,1,2,raw)
        self.assertEqual(display_ppm(f),b'P6\n1 2\n255\n'+bytes([0,0,255,255,0,0]))
        self.assertEqual(f.rgba,raw)
    def test_hdr_display_clip_leaves_reference_values_alone(self):
        raw=array.array('f',[3,-1,.0031308,1]).tobytes()
        f=Frame(2,Epoch(1,2,1,1),'F',True,True,1,1,raw)
        self.assertEqual(display_ppm(f),b'P6\n1 1\n255\n'+bytes([255,0,10]))
        self.assertEqual(f.rgba,raw)
if __name__=='__main__':unittest.main()
