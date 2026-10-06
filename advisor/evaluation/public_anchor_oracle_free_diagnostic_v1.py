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
 return {'accepted':bool(ok),'inliers':n,'ratio':n/len(a),'spread':spread.tolist(),'scale':sc,'angle':angle,'bbox':[float(l),float(t),float(rr-l),float(bb-t)],'corners':full.tolist(),'roi_inside':inside,'edge_support':supports},supported
def diagnose(im):
 gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);k,desc=sift.detectAndCompute(gray[400:636,500:830],None);ps=np.float32([np.float32(x.pt)+[500,400] for x in k]);sizes=np.float32([x.size for x in k]);edges=cv2.Canny(gray,50,150);primary=[];probes=[]
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
burst=Path('artifacts/baseline-tester/DRAGONDARK_HAND6_CHAIN_REVEAL_TRAIN_v3_20261006/chain-cancel-reveal-continuous');m=json.load(open(burst/'manifest.json',encoding='utf-8'))
for r in m['frames']:
 if 151<=r['capture_sequence']<=315:
  p=burst/r['file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'];rows.append({'group':'newhand6','original_capture':r,'path':str(p),'diagnostic':diagnose(read_image(p))})
old=Path('artifacts/baseline-tester/DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/chain-cancel-reveal-continuous');om=json.load(open(old/'manifest.json',encoding='utf-8'))
for r in om['frames']:
 if 43<=r['capture_sequence']<=46:
  p=old/r['file'];rows.append({'group':'oldpublic','original_capture':r,'path':str(p),'diagnostic':diagnose(read_image(p))})
for name,p in [('staticselected','DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-inspected/frame-0000.png'),('staticunselected','DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected/frame-0000.png'),('Roar','DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/roar-detail-negative/frame-0000.png'),('Storm','DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/thunderstormech-detail-negative/frame-0000.png')]:
 p=Path('artifacts/baseline-tester')/p;rows.append({'group':name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'diagnostic':diagnose(read_image(p))})
h1=hashlib.sha256(src.read_bytes()).hexdigest();out={'schema':'public-anchor-oracle-free-diagnostic-v1','diagnostic_parameters':pars,'source_before':h0,'source_after':h1,'source_fixed':h0==h1,'scope':'known method selection; no NCCbbox input; projected edges observed via Canny strip support; no tracking or runtime promotion','references':cfg['public_references'],'input_count':0,'e2e_count':0,'rows':rows,'summary':{g:{'n':sum(r['group']==g for r in rows),'accepted':sum(r['group']==g and r['diagnostic']['accepted'] for r in rows)} for g in set(r['group'] for r in rows)}};p=Path('evaluation/public-anchor-oracle-free-diagnostic-v1.json');assert not p.exists();p.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');print('SAVED',p,'fixed',h0==h1,out['summary']);print('newseqaccepted',[r['original_capture']['capture_sequence'] for r in rows if r['group']=='newhand6' and r['diagnostic']['accepted']])
