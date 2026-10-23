import io,json,struct,unittest
from pathlib import Path
from prototype_service import PrototypeService,Request
from prototype_wire import NativeProcess,read_packet
from protocol_model import Epoch
class ResidencyOptions(unittest.TestCase):
 def test_request_rejects_unqualified_options_before_enqueue(self):
  for options in ({'refill_fine':True},{'refill_fine':1,'experimental_native':True},{'publish_ms':True},{'publish_ms':-1},{'publish_ms':1001}):
   with self.subTest(options=options),self.assertRaises(ValueError):PrototypeService.request(object(),Path('C:/private/manifest.json'),Epoch(1,1,1,1),**options)
 def test_transport_preserves_explicit_options(self):
  native=object.__new__(NativeProcess);messages=[];native.send=messages.append
  request=Request(1,Path('C:/p/scene.rdlb'),Path('C:/p/manifest.json'),Epoch(1,1,1,1),12,True,'surface-textures',2,0,True,33)
  native.request(request,Path('C:/p/staging'));self.assertIs(messages[0]['refill_fine'],True);self.assertEqual(messages[0]['publish_ms'],33)
 def test_default_request_retains_legacy_options(self):
  r=Request(1,Path('C:/p/scene.rdlb'),Path('C:/p/manifest.json'),Epoch(1,1,1,1),12,False,'surface-textures',2,0)
  self.assertIs(r.refill_fine,False);self.assertEqual(r.publish_ms,0)
 def test_invalid_gpu_counter_rejected(self):
  for value in (-1,True,1.5,2**64):
   j=json.dumps({'kind':'error','rgba_bytes':0,'gpu_samples':value}).encode()
   with self.subTest(value=value),self.assertRaises(ValueError):read_packet(io.BytesIO(struct.pack('<I',len(j))+j))
if __name__=='__main__':unittest.main()
