import cv2,json,hashlib,numpy as np
from pathlib import Path
from master_duel_advisor.hand_search import NativeArtDetails
from master_duel_advisor.image_io import read_image
src=Path('src/master_duel_advisor/hand_search.py');h0=hashlib.sha256(src.read_bytes()).hexdigest();cp=Path('artifacts/dragondark-hand-search-calibration-v4/hand-search.json');cfg=json.loads(cp.read_text(encoding='utf-8'));refs=[cv2.resize(read_image(cp.parent/r['image']),(103,150)) for r in cfg['public_references']];details=NativeArtDetails(refs);sift=cv2.SIFT_create(nfeatures=800);bf=cv2.BFMatcher(cv2.NORM_L2);pars={'roi':[500,400,330,236],'candidate_features':800,'ratio':.75,'inliers':6,'inlier_ratio':.7,'spread':[39,36],'scale':[.9,1.25],'rotation_abs':3,'fullface_width':[100,130],'fullface_height':[145,190],'merge_px':3,'edge_support_min':.35,'edge_strip_radius':2,'probe_models':2};rows=[]
def model(a,b,size,edges):
 if len(a)<6:return None,np.zeros(len(a),bool)
 mat,mask=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2,maxIters=300,confidence=.99)
 if mat is None:return None,np.zeros(len(a),bool)
 sc=float(np.hypot(mat[0,0],mat[0,1]));inv=cv2.transform(b[None],cv2.invertAffineTransform(mat))[0];clear=np.min(np.stack([inv[:,0]-12,inv[:,1]-30,89-inv[:,0],101-inv[:,1]]),axis=0);supported=mask.ravel().astype(bool)&(size*5.31/max(sc,1e-9)<=clear+1e-12);n=int(supported.sum())
 if n<6:return None,supported
 full=cv2.transform(np.float32([[[0,0],[102,0],[102,149],[0,149]]]),mat)[0];l,t=full.min(axis=0);rr,bb=full.max(axis=0);angle=float(np.degrees(np.arctan2(mat[1,0],mat[0,0])));spread=np.ptp(a[supported],axis=0);inside=bool(500<=l and 400<=t and rr<830 and bb<636);supports=[]
 for p,q in zip(full,np.roll(full,-1,axis=0)):
  maskline=np.zeros_like(edges);cv2.line(maskline,tuple(np.round(p).astype(int)),tuple(np.round(q).astype(int)),255,1);band=cv2.dilate(edges,np.ones((5,5),np.uint8));supports.append(float(np.mean(band[maskline>0]>0)))
 ok=n>=6 and n/len(a)>=.7 and np.all(spread>=[39,36]) and .9<=sc<=1.25 and abs(angle)<=3 and inside and 100<=rr-l<=130 and 145<=bb-t<=190 and min(supports)>=.35
 return {'accepted':bool(ok),'inliers':n,'ratio':n/len(a),'spread':spread.tolist(),'scale':sc,'angle':angle,'bbox':[float(l),float(t),float(rr-l),float(bb-t)],'corners':full.tolist(),'roi_inside':inside,'edge_support':supports,'affine':mat.tolist(),'candidate_ids':[int(np.argmin(np.sum((CANDIDATE_POINTS-point)**2,axis=1))) for point in b[supported]],'scene_support_points':b[supported].tolist(),'reference_support_points':a[supported].tolist()},supported
def diagnose(im):
 gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);k,desc=sift.detectAndCompute(gray[400:636,500:830],None);ps=np.float32([np.float32(x.pt)+[500,400] for x in k]);sizes=np.float32([x.size for x in k]);global CANDIDATE_POINTS;CANDIDATE_POINTS=ps;edges=cv2.Canny(gray,50,150);primary=[];probes=[]
 if desc is None:return {'accepted':False,'primary':[],'probes':[],'reason':'descriptors_absent'}
 for ri,(rp,rd) in enumerate(details.references):
  if rd is None:continue
  reverse={x.queryIdx:x.trainIdx for x in bf.match(desc,rd)};pairs=[p[0] for p in bf.knnMatch(rd,desc,k=2) if len(p)==2 and p[0].distance<.75*p[1].distance and reverse.get(p[0].trainIdx)==p[0].queryIdx];a=np.float32([rp[p.queryIdx] for p in pairs]);b=np.float32([ps[p.trainIdx] for p in pairs]);ss=np.float32([sizes[p.trainIdx] for p in pairs]);r,_=model(a,b,ss,edges)
  if r:r['ref']=ri;primary.append(r)
  pairs=[p[0] for p in bf.knnMatch(desc,rd,k=2) if len(p)==2 and p[0].distance<.75*p[1].distance];a=np.float32([rp[p.trainIdx] for p in pairs]);b=np.float32([ps[p.queryIdx] for p in pairs]);ss=np.float32([sizes[p.queryIdx] for p in pairs])
  for z in range(2):
   r,sup=model(a,b,ss,edges)
   if r:r['ref']=ri;probes.append(r)
   if not sup.any():break
   a,b,ss=a[~sup],b[~sup],ss[~sup]
 valid=[r for r in primary+probes if r['accepted']];amb=any(np.linalg.norm(np.array(a['bbox'][:2])-b['bbox'][:2])>3 for a in valid for b in valid);return {'accepted':any(r['accepted'] for r in primary) and not amb,'ambiguous':bool(amb),'primary':primary,'probes':probes}

from master_duel_advisor.hand_search import HandSearchVision
from master_duel_advisor.capture import Frame
RULE={'candidate':'art only; no NCC OR','accept':'all accepted primary/probe model pairs common6 spread39x36 residual<=2','representative':'primary accepted max inliers, then ascending ref index, then original model index','stop':'first permanent failure or handoff; no reanchor'}
def compatible(a,b):
 am={k:(p,v) for k,p,v in zip(a['candidate_ids'],a['reference_support_points'],a['scene_support_points'])};bm={k:(p,v) for k,p,v in zip(b['candidate_ids'],b['reference_support_points'],b['scene_support_points'])};ids=am.keys()&bm.keys()
 if len(ids)<6:return False
 for model,mp in [(a,am),(b,bm)]:
  pp=np.array([mp[k][0] for k in ids]);vv=np.array([mp[k][1] for k in ids]);mat=np.array(model['affine']);pred=pp@mat[:,:2].T+mat[:,2]
  if not np.all(np.ptp(pp,axis=0)>=[39,36]) or not np.all(np.linalg.norm(pred-vv,axis=1)<=2):return False
 return True
burst=Path('artifacts/baseline-tester/DRAGONDARK_HAND6_CHAIN_REVEAL_TRAIN_v3_20261006/chain-cancel-reveal-continuous');manifest=json.load(open(burst/'manifest.json',encoding='utf-8'));v=HandSearchVision(cp);ctx={'action_id':'synthetic-art-anchor-tracker','hand_search_confirmation':{'card_id':'13906'},'steps':[{'input_sent':True,'before_sequence':0,'hand_before':{'facts':{'hand_search.layout':{'value':'hand6-slot3'}}}},{'input_sent':True,'before_sequence':150,'client_rect':[-1918,817,-638,1537],'input_epoch':97996062}]};rows=[]
for r in manifest['frames']:
 if not 151<=r['capture_sequence']<=315:continue
 p=burst/r['file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'];im=read_image(p);f=Frame(im,r['captured_at_monotonic'],r['capture_sequence'],capture_source='live_mss',capture_rect=tuple(r['rect_before']),input_epoch=97996062);st=v.recognize(f);cand=None
 if v.episode is None:
  v.episode={'action_id':ctx['action_id'],'layout':'hand6-slot3','profile_sha256':v.sha256,'source_sequence':0,'anchor':None,'handoff':None,'trace':[],'failed':None,'ready':False}
 if v.points is None and not v.episode['anchor']:
  cand=diagnose(im);valid=[m for m in cand['primary']+cand['probes'] if m['accepted']];pos=[(i,m) for i,m in enumerate(cand['primary']) if m['accepted']];allpair=bool(pos) and all(compatible(a,b) for i,a in enumerate(valid) for b in valid[i+1:]);cand['common_support_all_pair']=allpair
  if allpair and not st['own_chain'] and not st['gy_panel']:
   idx,rep=min(pos,key=lambda z:(-z[1]['inliers'],z[1]['ref'],z[0]));x,y,w,h=rep['bbox'];mask=np.zeros(im.shape[:2],np.uint8);xx,yy,ww,hh=map(round,[x,y,w,h]);mask[yy+14:yy+hh-24,xx+8:xx+ww-8]=255;gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);pts=cv2.goodFeaturesToTrack(gray,24,.02,5,mask=mask)
   if pts is not None and len(pts)>=6:
    v.points=pts;v.gray=gray;v.box=np.float32([[x,y],[x+w,y],[x+w,y+h],[x,y+h]]);v.episode.update(anchor={'seq':f.sequence,'at':f.captured_at,'bbox':[x,y,w,h],'cid':'13906','method':'diagnostic_art_pose','representative_ref':rep['ref'],'affine':rep['affine']},entered=False,raised=False,last_seq=f.sequence,last_at=f.captured_at)
 else:v.observe(f,ctx,st)
 rows.append({'original_capture':r,'candidate':cand,'episode_snapshot':json.loads(json.dumps(v.episode)),'points':len(v.points) if v.points is not None else 0,'box':v.box.tolist() if v.box is not None else None})
 if v.episode.get('failed') or v.episode.get('handoff'):break
h1=hashlib.sha256(src.read_bytes()).hexdigest();out={'schema':'public-art-anchor-tracker-diagnostic-v1','rules':RULE,'parameters':pars,'source_before':h0,'source_after':h1,'source_fixed':h0==h1,'scope':'saved images + synthetic receipts/live wrapper only; production unchanged','input_count':0,'e2e_count':0,'rows':rows,'episode':v.episode,'original_clock_preserved':True};op=Path('evaluation/public-art-anchor-tracker-diagnostic-v1.json');assert not op.exists();op.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');print('saved',op,'sourcefixed',h0==h1,'frames',len(rows),'lastseq',rows[-1]['original_capture']['capture_sequence'],'episode',json.dumps(v.episode,ensure_ascii=False))
