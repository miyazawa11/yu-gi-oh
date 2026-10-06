
import cv2,json,numpy as np,hashlib,time
from pathlib import Path
from master_duel_advisor.hand_search import HandSearchVision
from master_duel_advisor.image_io import read_image
cp=Path('artifacts/dragondark-hand-search-calibration-v4/hand-search.json');v=HandSearchVision(cp);cfg=v.config;refs=[]
for layout in ['hand6-slot3','hand7-slot3']:
 scene=cfg['scenes']['effect_'+layout];rect=scene['rect'];point=cfg['layouts'][layout]['effect_point']
 for r in scene['references']:
  refs.append((cv2.cvtColor(read_image(cp.parent/r['image']),cv2.COLOR_BGR2GRAY),[point[0]-rect[0],point[1]-rect[1]],r['sha256']))
PARAM={'ROI':[280,460,720,150],'method':'native gray TM_CCOEFF_NORMED','threshold':.98,'merge_origin_px':3,'scale':[1.0],'cache':'same image content SHA exact only','no_runtime_permission':True};memo={}
def detect(im,usecache):
 key=hashlib.sha256(im.tobytes()).hexdigest()
 if usecache and key in memo:return memo[key]
 roi=cv2.cvtColor(im[460:610,280:1000],cv2.COLOR_BGR2GRAY);cand=[];maximum=-1
 for ref,off,sha in refs:
  vals=cv2.matchTemplate(roi,ref,cv2.TM_CCOEFF_NORMED);maximum=max(maximum,float(vals.max()));peaks=cv2.dilate(vals,np.ones((7,7),np.uint8));yy,xx=np.where((vals>=.98)&(vals==peaks))
  for x,y in zip(xx,yy):cand.append({'bbox':[int(x)+280,int(y)+460,int(ref.shape[1]),int(ref.shape[0])],'point':[int(x)+280+off[0],int(y)+460+off[1]],'score':float(vals[y,x]),'ref_sha':sha})
 clusters=[]
 for c in sorted(cand,key=lambda z:-z['score']):
  if not any(np.linalg.norm(np.array(c['bbox'][:2])-cl[0]['bbox'][:2])<=3 for cl in clusters):clusters.append([c])
  else:next(cl for cl in clusters if np.linalg.norm(np.array(c['bbox'][:2])-cl[0]['bbox'][:2])<=3).append(c)
 result={'max_score':maximum,'candidates':cand,'distinct':len(clusters),'selected':clusters[0][0] if len(clusters)==1 else None};memo[key]=result;return result
DATA=Path('artifacts/baseline-tester');groups={'source6':'DRAGONDARK_SEARCH_TRAIN_v1_20261006/effect-menu-before','source7':'DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/effect-menu-before','fixed10':'DRAGONDARK_SOURCE_TEMPORAL_FIXED_v1_20261006/menu','retry1zero4':'DRAGONDARK_HAND_SEARCH_PREPARATION_v3_20261006/retry1-hand6-slot4-mismatch','selectednoeffect':'DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/post-reveal-fresh-hand-inspect','unselected':'DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected','roar':'DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/roar-detail-negative','storm':'DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/thunderstormech-detail-negative','Ash':'CARD_NAME_OCR_EXPLORATION_20261006/ash-first','G':'MAXXC_MENU_TRAIN_v1_full','Solar':'MAXXC_CURRENT_HAND_TRAIN_20261006/solar-menu','GY':'DRAGONDARK_SEARCH_TRAIN_v1_20261006/gy-dragondark-fresh-inspected','ownchain':'DRAGONDARK_SEARCH_TRAIN_v1_20261006/own-chain-optional-before','field':'ASH_NORMAL_INSPECT_TRAIN_v1_20261006/post-inspected'};rows=[];source=Path('src/master_duel_advisor/hand_search.py');h0=hashlib.sha256(source.read_bytes()).hexdigest()
for group,path in groups.items():
 mp=DATA/path/'manifest.json'
 if not mp.exists():continue
 m=json.load(open(mp,encoding='utf-8'))
 for r in m['frames']:
  p=mp.parent/r['file'];assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256'];im=read_image(p);t=time.perf_counter();d=detect(im,False);cold=(time.perf_counter()-t)*1000;t=time.perf_counter();hot=detect(im,True);cached=(time.perf_counter()-t)*1000;st=v.recognize(type('F',(),{'pixels':im,'sequence':r.get('capture_sequence',0),'captured_at':r.get('captured_at_monotonic',0)})());pose=v.source_art.recognize(im,d['selected']['point']) if d['selected'] else None;bound=d['selected'] is not None and st['detail_cid']=='13906' and pose and pose['accepted'] and not pose.get('ambiguous');rows.append({'group':group,'original_capture':r,'manifest_path':str(mp),'detection':d,'detail_cid':st['detail_cid'],'source_art_pose':pose,'detail_art_effect_AND_diagnostic_only':bool(bound),'scope_guards':{'GY':st['gy_panel'],'ownchain':st['own_chain'],'Main1':'not included in this intermediate predicate'},'uncached_ms':cold,'same_image_cache_ms':cached})
out={'schema':'effect-position-oracle-free-diagnostic-v1','parameters':PARAM,'reference_hashes':[r[2] for r in refs],'source_before':h0,'source_after':hashlib.sha256(source.read_bytes()).hexdigest(),'input_count':0,'e2e_count':0,'slot_count_inference':False,'summary':{g:{'n':sum(r['group']==g for r in rows),'unique_effect':sum(r['group']==g and r['detection']['distinct']==1 for r in rows),'detail_art_effect_AND':sum(r['group']==g and r['detail_art_effect_AND_diagnostic_only'] for r in rows)} for g in groups},'timing':{'uncached_mean_ms':float(np.mean([r['uncached_ms'] for r in rows])),'same_image_cache_mean_ms':float(np.mean([r['same_image_cache_ms'] for r in rows])),'excludes_capture_decode_E2E':True},'rows':rows,'limitations':['same-reference method selection, not independent holdout','effect crop is evidence crop, safe point from original reference offset; button boundary not independently verified','3px greedy merge is diagnostic only; must reject bridging/point inconsistency before production','Main1/terminal/modal/actualinspect/receipt safety not removed or replaced','no threshold/template changes after seeing Retry1']};p=Path('evaluation/effect-position-oracle-free-diagnostic-v1.json');assert not p.exists();p.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');print('saved',p,'fixed',out['source_before']==out['source_after'],'n',len(rows));print(out['summary']);print(out['timing'])
