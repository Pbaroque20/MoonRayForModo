"""Private end-to-end native preview, automatic fallback and recovery checks."""
import argparse,array,json,math,struct,time
from io import BytesIO
from pathlib import Path
import asset_snapshot
from fallback import environment
from prototype_service import PrototypeService
from prototype_wire import read_packet,decode
from protocol_model import Epoch
from reference_runtime import sha,verify
from run_m0 import guard,standalone,image
from run_material_progressive import call
from run_cpu_image import compare_fixture
HERE=Path(__file__).resolve().parent
GATES={'native_max_channel_error':.002,'fallback_bytes':'exact float32 RGBA from the owned pinned-XPU EXR; independent runs checked against reference-only envelope',
       'reference_profile':'xpu-strict','image_block_width':8,'image_alpha_error':.015,
       'image_max_pixel_error':.08,'image_max_block_mean_error':.015,
       'cancelled_or_obsolete_images':0,'production_native_qualification':False}

def floats(data):
    v=array.array('f');v.frombytes(data);return v

def packed(reference):
    channels=reference['channels'];return array.array('f',(channels[c][i] for i in range(len(channels['R'])) for c in 'RGBA')).tobytes()

def classify(report):
    """Operational completion never hides a failed reference-qualification gate."""
    report['operational_status']='passed'
    passed=all(x['heldout_passed'] and x['candidate_passed'] for x in report['reference_repeatability'].values())
    report['reference_gate']='passed on these one-worker controls' if passed else 'unqualified: reference envelope exceeded'
    report['status']='passed' if passed else 'partial'
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','runtime','spatial','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);rt=a.runtime.resolve();base=a.spatial.resolve()
    r={'status':'incomplete','gates':GATES,'scope':'private process-isolated mode controller; no Modo or speed qualification'};service=None
    try:
        guard();lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock)
        build=json.loads(a.build.read_text());assert build['status']=='passed'
        exe,ptx,helper=map(Path,(build['exe'],build['ptx'],build['helper']))
        assert sha(exe)==build['binary_hashes']['exe'] and sha(ptx)==build['binary_hashes']['ptx'] and sha(helper)==build['asset_build']['executable_sha256']
        if any(sha(Path(k))!=v for k,v in build['source_hashes'].items()):raise RuntimeError('Compiled source drift')
        held={str(f):sha(f) for f in [HERE/n for n in ('prototype_service.py','prototype_wire.py','run_prototype.py','fallback_service.py','fallback.py','asset_snapshot.py')]}
        r['source_hashes']=held;r['build_manifest_sha256']=sha(a.build)
        (out/'frozen-gates.json').write_text(json.dumps(GATES,indent=2))
        assert json.loads((base/'report.json').read_text())['status']=='passed'
        scene=base/'room-close/frozen/manifest.json';reference=image(rt,base/'room-close/reference');expected_ref=packed(reference)
        header,decoded=decode(exe,rt,base/'room-close/reference/beauty.exr',out)
        assert decoded==expected_ref,'Decoded reference row order/precision mismatch'
        r['reference_decoder']='exact float32 RGBA against independent PFM reader'
        # An unqualified nondefault material control must use original XPU.
        # Roughness is inert for this zero-specular fixture, whose reference is
        # repeatable. The earlier metallic fixture failed the exact-reference
        # gate (2.235e-7 variation between originals); that report is retained.
        unsupported=out/'unsupported';unsupported.mkdir()
        text=(base/'room-close/input.rdla').read_text()+'\nUsdPreviewSurface("/m1") { ["roughness"]=.3 }\n'
        (unsupported/'input.rdla').write_text(text,encoding='utf-8')
        call([rt/'rdl2_convert.exe','-i',unsupported/'input.rdla','-o',unsupported/'input.rdlb'],rt,unsupported,'convert')
        asset_snapshot.freeze(unsupported/'input.rdlb',helper,rt,unsupported/'frozen',unsupported)
        unsupported_ref=standalone(rt,unsupported/'frozen/scene.rdlb',unsupported/'reference',1)
        unsupported_pixels=packed(image(rt,unsupported/'reference'));r['unsupported_standalone_execution']=unsupported_ref['execution']
        # Freeze the rule before candidate runs: five new original renders, then
        # two held-out originals. No candidate-dependent padding or tolerances.
        # FID-03 is measured separately from byte-exact extraction of the child EXR.
        r['reference_repeatability']={}
        for name,manifest in [('textured',scene),('unsupported',unsupported/'frozen/manifest.json')]:
            folder=out/('reference-envelope-'+name);folder.mkdir();values=[];executions=[]
            for i in range(7):
                rendered=standalone(rt,manifest.parent/'scene.rdlb',folder/str(i),1)
                executions.append(rendered['execution']);values.append(floats(packed(image(rt,folder/str(i)))))
            width=len(values[0]);low=[min(v[i] for v in values[:5]) for i in range(width)];high=[max(v[i] for v in values[:5]) for i in range(width)]
            bound=max(b-a for a,b in zip(low,high))
            heldout=max(max(abs(x-y) for x,y in zip(a,b)) for a in values[5:] for b in values[:5])
            entry={'rule':'max-channel sup norm of five independent original renders; no slack','training_runs':5,'held_out_runs':2,'absolute_bound':bound,'heldout_error':heldout,'heldout_passed':heldout<=bound,'candidate_passed':True,'execution':executions}
            r['reference_repeatability'][name]=entry
            (folder/'frozen-envelope.json').write_text(json.dumps(entry,indent=2))
            print('Reference envelope:',name,bound,heldout,flush=True)
        def handoff(s,baseline,name):
            assert s.frame.tier=='F' and s.frame.reference_image is not None,'Expected owned reference frame'
            independent=packed(image(rt,s.frame.reference_image.parent))
            assert s.frame.rgba==independent,'Controller changed pinned-XPU raw pixels'
            error=max(abs(x-y) for x,y in zip(floats(s.frame.rgba),floats(baseline)))
            entry=r['reference_repeatability'][name]
            entry['candidate_passed'] &= error<=entry['absolute_bound']
            return {'own_reference_bytes_exact':True,'independent_standalone_max_error':error,'within_original_envelope':error<=entry['absolute_bound'],'reason':s.fallback_reason}
        # Bound and reject malformed transport before it could reach the display.
        rejected=0
        for blob in (struct.pack('<I',20000),struct.pack('<I',2)+b'{}'):
            try:read_packet(BytesIO(blob))
            except (ValueError,EOFError):rejected+=1
        assert rejected==2;r['malformed_wire_rejections']=rejected
        service=PrototypeService(exe,ptx,rt,lock,out/'session',binary_hashes=build['binary_hashes'],test_faults=True)
        number=0;max_request_ms=0;max_poll_ms=0;intermediate=0
        def request(manifest=scene,threads=12,**kwargs):
            nonlocal number,max_request_ms
            number+=1;t=time.perf_counter();ticket=service.request(manifest,Epoch(1201,number,1,1),threads,**kwargs);max_request_ms=max(max_request_ms,(time.perf_counter()-t)*1000)
            assert service.poll().frame is None,'Previous scene frame retained at request'
            return ticket
        def wait(ticket,*,partial=False):
            nonlocal max_poll_ms,intermediate
            end=time.monotonic()+240;min_spp=0
            while time.monotonic()<end:
                t=time.perf_counter();s=service.poll();max_poll_ms=max(max_poll_ms,(time.perf_counter()-t)*1000)
                assert s.ticket==ticket,'Unexpected controller ticket'
                if s.phase=='failed':raise RuntimeError(s.error)
                frame=s.frame
                if frame:
                    assert frame.ticket==ticket and frame.epoch==Epoch(1201,number,1,1),'Obsolete image surfaced'
                    if frame.tier=='D':
                        assert not frame.qualified and frame.min_spp>=min_spp;min_spp=frame.min_spp
                        if not frame.final:intermediate+=1
                    if partial and not frame.final:return s
                    if frame.final and not partial:return s
                    if partial and frame.final:raise RuntimeError('Fixture completed before partial preview')
                time.sleep(.003)
            raise TimeoutError('Prototype request timed out')
        baseline=(base/'room-close/mixed-12.rgba').read_bytes()
        def native_result(name,s):
            f=s.frame;assert f.final and f.tier=='D' and f.pending_paths==0
            delta=max(abs(x-y) for x,y in zip(floats(f.rgba),floats(baseline)))
            assert delta<=GATES['native_max_channel_error'],(name,delta)
            (out/(name+'.rgba')).write_bytes(f.rgba)
            return {'max_native_error':delta,'reference_errors':compare_fixture(floats(f.rgba),reference,GATES),'windows':f.windows}
        r['native']={}
        for threads in (1,12):
            ticket=request(threads=threads,experimental_native=True);s=wait(ticket);r['native'][str(threads)]=native_result('native-'+str(threads),s)
        assert intermediate>0,'No incremental native previews'
        # Retained worker, new immutable epoch, no stale previous-scene pixels.
        ticket=request(experimental_native=True);wait(ticket,partial=True)
        ticket=request(experimental_native=True);s=wait(ticket);r['edit']=native_result('edit',s)
        ticket=request(experimental_native=True);wait(ticket,partial=True);service.cancel()
        end=time.monotonic()+15
        while service.poll().phase!='idle':
            assert service.poll().frame is None,'Cancelled image surfaced'
            if time.monotonic()>end:raise TimeoutError('Cancel did not retire')
            time.sleep(.005)
        r['cancelled_native_image_cleared']=True
        # Explicit reference mode is the default, even when native could admit it.
        ticket=request(threads=1);s=wait(ticket)
        assert not s.fallback_reason,'Default mode unexpectedly tried native first'
        r['default_reference']=handoff(s,expected_ref,'textured')
        # Native admission rejection automatically dispatches the same package.
        ticket=request(unsupported/'frozen/manifest.json',threads=1,experimental_native=True);s=wait(ticket)
        assert s.fallback_reason,'Native rejection was not reported'
        r['unsupported_fallback']=handoff(s,unsupported_pixels,'unsupported')
        # A real malformed native completion must not become black successful data.
        ticket=request(threads=1,experimental_native=True,fault=1);s=wait(ticket)
        assert s.fallback_reason,'Native failure was not reported'
        r['failure_fallback']=handoff(s,expected_ref,'textured')
        ticket=request(threads=1,experimental_native=True,fault=2);s=wait(ticket)
        assert s.fallback_reason,'Native process crash was not reported'
        r['process_crash_fallback']=handoff(s,expected_ref,'textured')
        ticket=request(experimental_native=True);s=wait(ticket);r['recovery']=native_result('recovered',s)
        # Missing/tampered package fails closed instead of rendering another scene.
        corrupt=out/'corrupt';corrupt.mkdir();(corrupt/'manifest.json').write_text('{}')
        ticket=request(corrupt/'manifest.json',experimental_native=True);end=time.monotonic()+15
        while service.poll().phase!='failed':
            if time.monotonic()>end:raise TimeoutError('Malformed package not rejected')
            time.sleep(.005)
        assert service.poll().frame is None;r['invalid_asset_package_rejected']=True
        ticket=request(experimental_native=True);wait(ticket,partial=True);s=service.poll()
        r['counts']={k:getattr(s,k) for k in ('submitted','coalesced','discarded','native_frames','reference_frames','fallbacks')}
        r['events']=s.events;r['observed_host_call_ms']={'max_request':max_request_ms,'max_poll':max_poll_ms,'qualification':False}
        service.close();assert service.wait_closed(25),'Prototype shutdown timeout'
        assert service.poll().phase=='closed' and service.poll().frame is None and not service.poll().error,'Shutdown failed'
        r['shutdown']='owned child and reader/reference workers retired; no pixels exposed'
        if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Controller source drift')
        verify(rt,lock);guard();classify(r)
    except Exception as error:r.update(status='failed',error=str(error))
    finally:
        if service is not None:service.close();service.wait_closed(25)
    (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k not in ('source_hashes','events')},indent=2),flush=True)
    return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
