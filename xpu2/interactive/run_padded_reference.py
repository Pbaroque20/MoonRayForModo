"""Reference-only empirical rounding guardband. Does not change renderer or native image gates."""
import array,json,traceback
from pathlib import Path
from reference_runtime import sha,verify
from reference_repeatability import save,values,envelope,against,run_reference
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-reference-padded-20261022'
PLAN={'threads':[1,12],'new_calibration_per_thread':4,'heldout_originals_per_thread':8,'heldout_fallbacks_per_thread':2,'bound':'max(2 * reference-only observed channel range, 8 * float32 epsilon * max(1, reference peak))','historical':'all prior original and fallback images including old failed held-outs are now explicitly calibration, never held-out evidence here','freeze':'both worker bounds frozen before fresh held-outs','scope':'empirical guardband on this fixture/runtime/device; no universal bound, bit-exact claim, or renderer modification','native_gates':'unchanged'}
OUT.mkdir(exist_ok=False);save(OUT/'protocol.json',PLAN);r={'status':'incomplete','protocol':PLAN,'cases':{},'global_bit_exact_claim':False}
try:
 rt=TR/'interactive-reference-042';lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard();scene=asset_snapshot.verify(TR/'interactive-spatial-textures-20261022b/room-close/frozen/manifest.json');b=json.loads((TR/'interactive-prototype-build-20261022qmc/build.json').read_text());decoder=Path(b['exe']);assert sha(decoder)==b['binary_hashes']['exe'];r.update(runtime_identity=lock['identity'],scene_sha256=sha(scene),harness_sha256=sha(Path(__file__)))
 historical=[json.loads((TR/n/'report.json').read_text()) for n in ('interactive-repeatability-20261022','interactive-repeatability-extended-20261022')];controls={}
 for t in PLAN['threads']:
  key=str(t);c=r['cases'][key]={'calibration':[],'heldout':[],'fallback':[]};images=[];seen=set()
  for h in historical:
   for rows in (h['cases'][key].get(n,[]) for n in ('calibration','heldout','fallback')):
    for row in rows:
     raw=Path(row['folder'])/'beauty.rgba' if 'folder' in row else Path(row['exr']).with_suffix('.rgba')
     if not raw.exists() or str(raw) in seen:continue
     assert sha(raw)==row['raw_sha256'];im=values(raw.read_bytes());images.append(im);seen.add(str(raw));c['calibration'].append({'historical':True,'raw':str(raw),'sha256':sha(raw)})
  for i in range(PLAN['new_calibration_per_thread']):
   im,row=run_reference(rt,scene,OUT/f'cal-{t}-{i}',t,decoder);images.append(im);c['calibration'].append(row);print('calibration',t,i,flush=True)
  measured=envelope(images);peak=max(max(abs(v) for v in im) for im in images);bound=max(2*measured,8*2**-23*max(1,peak));controls[key]=images;c.update(reference_range=measured,reference_peak=peak,frozen_bound=bound);save(OUT/'report.json',r)
 save(OUT/'frozen-bounds.json',{'protocol':PLAN,'bounds':{k:v['frozen_bound'] for k,v in r['cases'].items()},'reference_only':True})
 ok=True
 for t in PLAN['threads']:
  key=str(t);c=r['cases'][key];images=controls[key]
  for kind,count,fb in [('heldout',8,False),('fallback',2,True)]:
   for i in range(count):
    im,row=run_reference(rt,scene,OUT/f'{kind}-{t}-{i}',t,decoder,fallback=fb);row.update(against(im,images,c['frozen_bound']));c[kind].append(row);ok &= row['passed'];print(kind,t,i,row['max_distance_to_controls'],row['passed'],flush=True);save(OUT/'report.json',r)
  bad=array.array('f',images[0]);bad[0]+=max(.001,100*c['frozen_bound']);c['negative_rgb_control_rejected']=not against(bad,images,c['frozen_bound'])['passed'];bad=array.array('f',images[0]);bad[3]+=0.1;c['negative_alpha_control_rejected']=not against(bad,images,c['frozen_bound'])['passed'];ok &= c['negative_rgb_control_rejected'] and c['negative_alpha_control_rejected']
 verify(rt,lock);asset_snapshot.verify(scene.parent/'manifest.json');guard();assert sha(Path(__file__))==r['harness_sha256'];r['status']='passed' if ok else 'failed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
