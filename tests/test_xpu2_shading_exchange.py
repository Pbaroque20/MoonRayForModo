import struct
import unittest
from pathlib import Path
from xpu2.cuda_window_samples import packet
from xpu2.lambert_sample import read
from xpu2.shading_exchange import (SIZE,encode_batch,decode_batch,gpu_batch,material_status,check,declines)

ROOT=Path(__file__).resolve().parents[1]

class ShadingExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.row=next(r for r in read(ROOT/'xpu2/reference/lambert-sample-avx8-20261017.jsonl.gz')[1:]
                     if r['key']==[0,0,0,0,0,0,0,3])

    def setUp(self):
        words=[0x32555058,2,2,0,0xffffffff,1000,0,6,0,(77<<16)|96,0,0,0,0,1000]
        self.sampler=packet(words);words[5]+=1;self.next_sampler=packet(words)
        self.material=struct.pack('<24I',*self.row['input'])
        self.state=struct.pack('<4I',0x31485358,1,1,0)+self.sampler+self.material+bytes(32)
        self.record={'input':self.state,'length':SIZE}
        self.sample_calls=0;self.shader_calls=0

    def sample(self,batch,block,tables):
        self.sample_calls+=1
        return (b''.join(self.next_sampler if tables else r['input'] for r in batch),
                [v for r in batch for v in ([0,123,0x3f000000,0x3e800000,0] if tables else [1,123,0,0,0])])

    def shade(self,batch,block):
        self.shader_calls+=1
        for r in batch:self.assertEqual(struct.unpack_from('<2I',r['input'],44),(0x3f000000,0x3e800000))
        return b''.join(r['input'] for r in batch),[v for r in batch for v in [0,*self.row['vector']]]

    def test_round_trip_frame_and_truncation(self):
        raw=encode_batch([self.record]);self.assertEqual(raw[:8],struct.pack('<4sI',b'XHB1',1))
        out=struct.pack('<4sI',b'XHO1',1)+self.state+struct.pack('<12I',*([0]*12))
        self.assertEqual(decode_batch(out,1),(self.state,[0]*12))
        for data,count in ((out[:-1],1),(out+b'x',1),(b'BAD!'+out[4:],1),(out,2),(out,0)):
            with self.assertRaises(ValueError):decode_batch(data,count)
        for batch in ([],[{'input':self.state[:-1],'length':SIZE}]):
            with self.assertRaises(ValueError):encode_batch(batch)

    def test_success_uses_returned_sampler_and_direction(self):
        state,words=gpu_batch([self.record],self.sample,self.shade)
        self.assertEqual(state[:16],self.state[:16]);self.assertEqual(state[16:80],self.next_sampler)
        self.assertEqual(state[112:124],struct.pack('<3I',*self.row['vector'][:3]))
        self.assertEqual(state[176:],struct.pack('<8I',*self.row['vector']))
        self.assertEqual(words,[0,123,0x3f000000,0x3e800000,*self.row['vector']])
        self.assertEqual(self.state,self.record['input'])

    def test_missing_tables_preserve_entire_state(self):
        state,words=gpu_batch([self.record],self.sample,self.shade,tables=False)
        self.assertTrue(check(declines([self.record]),state,words)['passed'])
        self.assertEqual(self.shader_calls,0)

    def test_unavailable_shader_rolls_back_sampler_advance(self):
        state,words=gpu_batch([self.record],self.sample,self.shade,shader_available=False)
        self.assertTrue(check(declines([self.record]),state,words)['passed'])
        self.assertEqual(self.sample_calls,1);self.assertEqual(self.shader_calls,0)

    def test_declined_and_invalid_shader_roll_back_all_state(self):
        for status in (1,2):
            def declined(batch,block):return b''.join(r['input'] for r in batch),[status]+[0]*8
            state,words=gpu_batch([self.record],self.sample,declined)
            self.assertTrue(check(declines([self.record],status),state,words)['passed'])

    def test_unknown_math_profile_never_executes_or_silently_falls_back(self):
        state=bytearray(self.state);struct.pack_into('<I',state,8,2)
        batch=[{'input':bytes(state),'length':SIZE}]
        returned,words=gpu_batch(batch,self.sample,self.shade)
        self.assertTrue(check(declines(batch),returned,words)['passed'])
        self.assertEqual((self.sample_calls,self.shader_calls),(0,0))

    def test_shader_mutation_and_truncation_are_detected(self):
        def mutation(batch,block):return bytes(96),[0]*9
        def truncated(batch,block):return batch[0]['input'],[0]*8
        for fn in (mutation,truncated):
            with self.assertRaises(ValueError):gpu_batch([self.record],self.sample,fn)
        with self.assertRaises(ValueError):gpu_batch([self.record],lambda b,k,t:(b'',[]),self.shade)

    def test_material_controls_rejected_before_overwriting_random_inputs(self):
        for offset,value,status in ((44,0x7fc00000,2),(56,0xbf800000,2),(88,1,1),(56,0x7f7fffff,1)):
            material=bytearray(self.material);struct.pack_into('<I',material,offset,value)
            self.assertEqual(material_status(material),status)
            state=self.state[:80]+bytes(material)+self.state[176:]
            batch=[{'input':state,'length':SIZE}];returned,words=gpu_batch(batch,self.sample,self.shade)
            self.assertTrue(check(declines(batch,status),returned,words)['passed'])

    def test_checker_detects_state_result_and_length_changes(self):
        state,words=gpu_batch([self.record],self.sample,self.shade)
        row=dict(self.record,output=state,result=words)
        self.assertTrue(check([row],state,words)['passed'])
        corrupt=bytearray(state);corrupt[8]^=1
        self.assertFalse(check([row],bytes(corrupt),words)['passed'])
        changed=words[:];changed[4]^=1
        self.assertFalse(check([row],state,changed)['passed'])
        with self.assertRaises(ValueError):check([row],state[:-1],words)

if __name__=='__main__':unittest.main()
