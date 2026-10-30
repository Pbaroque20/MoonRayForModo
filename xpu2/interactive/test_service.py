import tempfile
import threading
import time
import unittest
from pathlib import Path
from fallback import Finished
from fallback_service import ReferenceService
from protocol_model import Epoch


def until(predicate,timeout=5):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=predicate()
        if value:return value
        time.sleep(.005)
    raise AssertionError("Background operation did not complete")


class FakeJob:
    def __init__(self,runtime,scene,out,threads,epoch):
        self.epoch=epoch
        self.scene=scene
        self.output=out
        self.state="new"
        self.process=self
        self.done=threading.Event()
        self.cancelled=False
        self.enter_result=None
        self.release_result=None
    def start(self):self.state="running"
    def cancel(self,reason="cancelled"):
        self.cancelled=True
        self.state="cancelled"
    def poll(self):
        if self.state=="running" and self.done.is_set():self.state="finished"
        return self.state
    def kill(self):self.state="cancelled"
    def wait(self,timeout):return self.state
    def result(self,epoch):
        if self.enter_result:
            self.enter_result.set()
            if not self.release_result.wait(5):raise RuntimeError("Blocked test result")
        return Finished(epoch,self.output/"beauty.exr","F","xpu") if self.state=="finished" else None


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.jobs=[]
        self.threads=[]
        self.services=[]
    def tearDown(self):
        for service in self.services:
            service.close()
            self.assertTrue(service.wait_closed(6))
        self.temp.cleanup()
    def factory(self,*args):
        self.threads.append(threading.get_ident())
        job=FakeJob(*args)
        self.jobs.append(job)
        return job
    def service(self,verify=lambda *a:None,factory=None):
        service=ReferenceService(self.root,{},self.root/str(len(self.services)),factory or self.factory,verify)
        self.services.append(service)
        return service
    def request(self,service,i):
        return service.request(self.root/(str(i)+".rdlb"),Epoch(1,i,1,1),1)

    def test_startup_does_not_block_host_and_coalesces_unstarted_work(self):
        entered,release=threading.Event(),threading.Event()
        def verify(*args):
            self.threads.append(threading.get_ident())
            entered.set()
            if not release.wait(5):raise RuntimeError("Blocked verifier")
        service=self.service(verify)
        self.assertTrue(entered.wait(5))
        try:
            for i in range(1,4):self.request(service,i)
            self.assertEqual(service.poll().coalesced,2)
            self.assertFalse(self.jobs)
        finally:release.set()
        until(lambda:len(self.jobs)==1)
        self.assertEqual(self.jobs[0].epoch.scene,3)
        self.jobs[0].done.set()
        status=until(lambda:service.poll() if service.poll().phase=="finished" else None)
        self.assertEqual(status.result.epoch.scene,3)
        self.assertTrue(all(t!=threading.get_ident() for t in self.threads))

    def test_edit_during_result_admission_rejects_old_frame(self):
        service=self.service()
        self.request(service,1)
        until(lambda:self.jobs)
        old=self.jobs[0]
        old.enter_result,old.release_result=threading.Event(),threading.Event()
        old.done.set()
        self.assertTrue(old.enter_result.wait(5))
        try:
            self.request(service,2)
            self.assertIsNone(service.poll().result)
        finally:old.release_result.set()
        until(lambda:len(self.jobs)==2)
        self.assertIsNone(service.poll().result)
        self.jobs[1].done.set()
        until(lambda:service.poll().phase=="finished")
        self.assertEqual(service.poll().result.epoch.scene,2)
        self.assertEqual(service.poll().discarded,1)

    def test_close_cancels_owned_work_without_host_wait(self):
        service=self.service()
        self.request(service,1)
        until(lambda:self.jobs)
        service.close()
        self.assertTrue(service.wait_closed(5))
        self.assertTrue(self.jobs[0].cancelled)
        self.assertEqual(service.poll().phase,"closed")
        self.assertIsNone(service.poll().result)
        with self.assertRaises(RuntimeError):self.request(service,2)

    def test_failed_admission_can_accept_new_request(self):
        def factory(*args):
            if args[-1].scene==1:raise ValueError("Invalid canonical scene")
            return self.factory(*args)
        service=self.service(factory=factory)
        self.request(service,1)
        until(lambda:service.poll().phase=="failed")
        self.assertIn("Invalid canonical scene",service.poll().error)
        self.request(service,2)
        until(lambda:self.jobs)
        self.jobs[0].done.set()
        until(lambda:service.poll().phase=="finished")
        self.assertIsNone(service.poll().error)

    def test_bad_reference_closes_service(self):
        def verify(*args):raise ValueError("Reference changed")
        service=self.service(verify)
        self.assertTrue(service.wait_closed(5))
        self.assertEqual(service.poll().phase,"failed")
        self.assertIn("Reference changed",service.poll().error)
        with self.assertRaises(RuntimeError):self.request(service,1)

    def test_cancel_invalidates_completed_result_and_can_restart(self):
        service=self.service()
        self.request(service,1)
        until(lambda:self.jobs)
        self.jobs[0].done.set()
        until(lambda:service.poll().phase=="finished")
        service.cancel()
        self.assertIsNone(service.poll().result)
        until(lambda:service.poll().phase=="idle")
        self.request(service,2)
        until(lambda:len(self.jobs)==2)
        self.jobs[1].done.set()
        until(lambda:service.poll().phase=="finished")
        self.assertEqual(service.poll().completed,2)

    def test_asset_validation_is_worker_only_and_blocks_bad_input(self):
        verifier_threads=[]
        def assets(path):
            verifier_threads.append(threading.get_ident())
            raise ValueError("Frozen asset changed")
        service=ReferenceService(self.root,{},self.root/'asset-service',self.factory,lambda *a:None,assets)
        self.services.append(service)
        service.request(self.root/'scene.rdlb',Epoch(1,1,1,1),1,self.root/'manifest.json')
        until(lambda:service.poll().phase=='failed')
        self.assertFalse(self.jobs)
        self.assertIn('Frozen asset changed',service.poll().error)
        self.assertTrue(all(t!=threading.get_ident() for t in verifier_threads))

    def test_asset_tamper_during_render_rejects_image_and_recovers(self):
        bad=threading.Event()
        def assets(path):
            if bad.is_set():raise ValueError("Frozen asset changed")
            return self.root/'scene.rdlb'
        service=ReferenceService(self.root,{},self.root/'tamper-service',self.factory,lambda *a:None,assets)
        self.services.append(service)
        service.request(self.root/'scene.rdlb',Epoch(1,1,1,1),1,self.root/'manifest.json')
        until(lambda:self.jobs);bad.set();self.jobs[0].done.set()
        until(lambda:service.poll().phase=='failed')
        self.assertIsNone(service.poll().result)
        self.assertIn('Frozen asset changed',service.poll().error)
        bad.clear();service.request(self.root/'scene.rdlb',Epoch(1,2,1,1),1,self.root/'manifest.json')
        until(lambda:len(self.jobs)==2);self.jobs[1].done.set()
        until(lambda:service.poll().phase=='finished')
        self.assertEqual(service.poll().result.epoch.scene,2)

if __name__=="__main__":unittest.main()
