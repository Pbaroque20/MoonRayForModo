from pathlib import Path
import struct
import unittest
from xpu2.cuda_window_samples import records, continuation_cases
from xpu2.exchange import encode_batch,decode_batch,owner,run_handoffs

REFERENCE=Path(__file__).resolve().parents[1]/'xpu2/reference/sampler-window-avx8-20261017.jsonl.gz'

class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items=records(REFERENCE)
        cls.oracle={r['input']:r for r in cls.items if r.get('mode')=='baseline'}

    def cpu(self,batch,workers):
        self.assertIn(workers,(1,4))
        expected=[self.oracle[r['input']] for r in batch]
        return b''.join(r['output'] for r in expected),[x for r in expected for x in r['result']]

    def gpu(self,batch,block,available):
        self.assertIn(block,(64,128,256))
        if available:
            return self.cpu(batch,1)
        return b''.join(r['input'] for r in batch),[x for r in batch for x in (1,r['result'][1],0,0,0)]

    def test_wire_layout_and_decoder(self):
        batch=self.items[:2]
        data=encode_batch(batch)
        self.assertEqual(data[:8],struct.pack('<4sI',b'XWB2',2))
        self.assertEqual(len(data),8+68*2)
        self.assertEqual(data[8:12],struct.pack('<I',64))
        self.assertEqual(data[12:76],batch[0]['input'])
        response=struct.pack('<4sI',b'XWO2',2)+b''.join(r['output']+struct.pack('<5I',*r['result']) for r in batch)
        state,words=decode_batch(response,2)
        self.assertEqual(state,b''.join(r['output'] for r in batch))
        self.assertEqual(words,[x for r in batch for x in r['result']])

    def test_bad_batch_size_or_state_rejected(self):
        for batch in ([],[self.items[0]]*32769,[dict(self.items[0],input=b'short')]):
            with self.assertRaises(ValueError):
                encode_batch(batch)

    def test_bad_output_framing_rejected(self):
        row=self.items[0]
        response=struct.pack('<4sI',b'XWO2',1)+row['output']+struct.pack('<5I',*row['result'])
        for data,count in ((response[:-1],1),(response+b'x',1),(b'BAD!'+response[4:],1),(response,2),(b'',0)):
            with self.assertRaises(ValueError):
                decode_batch(data,count)

    def test_schedules_reproducible_and_both_devices(self):
        for plan in ('alternating','chunks7','shuffled'):
            self.assertEqual([owner(plan,17,s) for s in range(48)],[owner(plan,17,s) for s in range(48)])
            self.assertEqual({owner(plan,17,s) for s in range(48)},{0,1})
        self.assertEqual([owner('chunks7',0,s) for s in range(9)],[0]*7+[1]*2)
        with self.assertRaises(ValueError):
            owner('unknown',0,0)

    def test_complete_coordinator_coverage_and_fallback(self):
        report=run_handoffs(self.items,self.cpu,self.gpu)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['plans']),3)
        for plan in report['plans']:
            self.assertEqual(plan['unique_samples'],13554)
            self.assertEqual(plan['components'],27108)
            self.assertEqual(plan['cpu_samples']+plan['gpu_samples'],13554)
            self.assertEqual(plan['cases_on_both_devices'],324)
            for key in ('cpu_to_gpu','gpu_to_cpu','fallback_samples','retry_samples'):
                self.assertGreater(plan[key],0)
        self.assertEqual(len({p['canonical_output_sha256'] for p in report['plans']}),1)

    def test_wrong_cpu_sample_fails(self):
        def bad(batch,workers):
            state,words=self.cpu(batch,workers);words[2]^=1
            return state,words
        report=run_handoffs(self.items,bad,self.gpu)
        self.assertFalse(report['passed'])
        self.assertEqual(report['failure'],'Handoff sample/state mismatch')

    def test_fallback_must_not_advance_state(self):
        def bad(batch,block,available):
            if not available:
                state,words=self.cpu(batch,1)
                return state,[x for r in batch for x in (1,r['result'][1],0,0,0)]
            return self.gpu(batch,block,available)
        report=run_handoffs(self.items,self.cpu,bad)
        self.assertFalse(report['passed'])
        self.assertEqual(report['failure'],'GPU fallback changed state')

    def test_retry_mismatch_fails(self):
        def bad(batch,block,available):
            state,words=self.gpu(batch,block,available)
            if len(batch)==11:
                words[2]^=1
            return state,words
        report=run_handoffs(self.items,self.cpu,bad)
        self.assertFalse(report['passed'])
        self.assertEqual(report['failure'],'Cross-device retry mismatch')

if __name__=='__main__':
    unittest.main()
