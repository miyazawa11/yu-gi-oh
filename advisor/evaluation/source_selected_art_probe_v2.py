"""方法選択の読み再生だけ。GUI/元画像/原時計/runtimeは変更しません。"""
from pathlib import Path
import hashlib
import json
import time

import cv2
import numpy as np

from master_duel_advisor.cancel_caption import diagnostic_output_path
from master_duel_advisor.capture import Frame
from master_duel_advisor.hand_search import HandSearchVision,NativeArtDetails
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/dragondark-hand-search-calibration-v3"
DATA=ROOT/"artifacts/baseline-tester"
vision=HandSearchVision(BASE/"hand-search.json")
detail=NativeArtDetails([read_image(vision.asset(r)) for r in vision.config["detail_references"]])
sift=cv2.SIFT_create(nfeatures=300)
bf=cv2.BFMatcher(cv2.NORM_L2)


def model(a,b,sizes,center,effect_y):
    row={"accepted":False,"pairs":len(a)}
    if len(a)<6:return row,np.zeros(len(a),bool)
    matrix,mask=cv2.estimateAffinePartial2D(a,b,method=cv2.RANSAC,ransacReprojThreshold=2.,maxIters=300,confidence=.99)
    if matrix is None:return row,np.zeros(len(a),bool)
    scale=float(np.hypot(matrix[0,0],matrix[0,1]));angle=float(np.degrees(np.arctan2(matrix[1,0],matrix[0,0])))
    if scale<=0:return row,np.zeros(len(a),bool)
    mapped=cv2.transform(b[None],cv2.invertAffineTransform(matrix))[0]
    clearance=np.min(np.stack([mapped[:,0]-12,mapped[:,1]-30,89-mapped[:,0],101-mapped[:,1]]),axis=0)
    supported=mask.ravel().astype(bool)&(5.31*sizes/scale<=clearance+1e-12)
    n=int(supported.sum())
    if n<6:row.update(reason="supported_under6",inliers=n);return row,supported
    spread=np.ptp(a[supported],axis=0);ratio=n/len(a)
    corners=cv2.transform(np.float32([[[12,30],[90,30],[90,102],[12,102]]]),matrix)[0]
    bbox=[float(corners[:,0].min()),float(corners[:,1].min()),float(np.ptp(corners[:,0])),float(np.ptp(corners[:,1]))]
    flags={"inliers":n>=6,"ratio":ratio>=.7,"spread":bool(np.all(spread>=[39,36])),"scale":.9<=scale<=1.1,
        "rotation":abs(angle)<=3,"relative_y":58<=bbox[1]-effect_y<=74,"relative_x":abs(bbox[0]+bbox[2]/2-center)<=20}
    row.update(accepted=all(flags.values()),inliers=n,ratio=ratio,spread=spread.tolist(),scale=scale,angle=angle,
        bbox=bbox,guards=flags,reason=[name for name,passed in flags.items() if not passed])
    return row,supported


def different(rows):
    valid=[row for row in rows if row["accepted"]]
    return any(np.linalg.norm(np.array(a["bbox"][:2])-np.array(b["bbox"][:2]))>3 for a in valid for b in valid)


def observe(im,center,effect_y):
    origin=np.float32([center-78,536]);roi=im[536:720,center-78:center+77]
    keypoints,descriptors=sift.detectAndCompute(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),None)
    result={"accepted":False,"primary":[],"ambiguity_models":[]}
    if descriptors is None:return result
    positions=np.float32([p.pt+origin for p in keypoints]);sizes=np.float32([p.size for p in keypoints])
    for points,ref_desc in detail.references:
        if ref_desc is None:continue
        reverse={m.queryIdx:m.trainIdx for m in bf.match(descriptors,ref_desc)}
        pairs=[pair[0] for pair in bf.knnMatch(ref_desc,descriptors,k=2) if len(pair)==2
            and pair[0].distance<.75*pair[1].distance and reverse.get(pair[0].trainIdx)==pair[0].queryIdx]
        a=np.float32([points[m.queryIdx] for m in pairs]);b=np.float32([positions[m.trainIdx] for m in pairs]);ss=np.float32([sizes[m.trainIdx] for m in pairs])
        positive,_=model(a,b,ss,center,effect_y);result["primary"].append(positive)
        # negative-only: reverse相互制限で弱い2枚目を消さず、最大2モデルへ分割。
        probe=[pair[0] for pair in bf.knnMatch(descriptors,ref_desc,k=2) if len(pair)==2 and pair[0].distance<.75*pair[1].distance]
        a=np.float32([points[m.trainIdx] for m in probe]);b=np.float32([positions[m.queryIdx] for m in probe]);ss=np.float32([sizes[m.queryIdx] for m in probe])
        for _ in range(2):
            alternative,supported=model(a,b,ss,center,effect_y);result["ambiguity_models"].append(alternative)
            if len(a)<6 or not supported.any():break
            a,b,ss=a[~supported],b[~supported],ss[~supported]
    result["ambiguous"]=different(result["primary"]+result["ambiguity_models"])
    result["accepted"]=any(r["accepted"] for r in result["primary"]) and not result["ambiguous"]
    return result


def run():
    folders={"new10":("DRAGONDARK_SOURCE_TEMPORAL_FIXED_v1_20261006/menu",683,524),
        "old_source6":("DRAGONDARK_SEARCH_TRAIN_v1_20261006/effect-menu-before",683,524),
        "old_source7":("DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/effect-menu-before",640,522),
        "selected7_no_effect":("DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006/post-reveal-fresh-hand-inspect",640,522),
        "unselected6":("DRAGONDARK_SEARCH_TRAIN_v1_20261006/post-search-hand-unselected",683,524),
        "Ash":("CARD_NAME_OCR_EXPLORATION_20261006/ash-first",683,524),
        "G":("MAXXC_MENU_TRAIN_v1_full",683,524),"Solar":("MAXXC_CURRENT_HAND_TRAIN_20261006/solar-menu",683,524),
        "roar13908":("DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/roar-detail-negative",683,524),
        "storm15011":("DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/thunderstormech-detail-negative",683,524),
        "restored13906":("DRAGON_NEIGHBOR_DETAIL_TRAIN_v1_20261006/dragondark-restored-positive",683,524)}
    inputs={ROOT/"evaluation/source-selected-art-condition-v1.json",Path(__file__).resolve(),*map(Path,vision.files)};cases=[]
    for group,(name,center,effect_y) in folders.items():
        folder=DATA/name;manifest=folder/"manifest.json";inputs.add(manifest)
        for item in json.loads(manifest.read_text(encoding="utf-8"))["frames"]:
            path=folder/item["file"];inputs.add(path)
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:raise ValueError("original hash mismatch")
            cases.append((group,path,item,center,effect_y))
    condition_path=diagnostic_output_path(ROOT/"evaluation/source-selected-art-condition-v2.json",inputs,ROOT/"evaluation")
    condition=json.loads((ROOT/"evaluation/source-selected-art-condition-v1.json").read_text(encoding="utf-8"))
    condition.update(schema="source-selected-art-condition-v2",ambiguity_probe={"direction":"candidate forward Lowe to reference, no reverse constraint, negative-only",
        "max_models_per_reference":2,"quality":"same pose/inlier/spread/descriptor support condition","iteration_bound":4})
    condition_path.write_text(json.dumps(condition,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    output=diagnostic_output_path(ROOT/"evaluation/source-selected-art-comparison-v2.json",inputs|{condition_path},ROOT/"evaluation")
    rows=[];timings=[]
    for group,path,item,center,effect_y in cases:
        im=read_image(path);start=time.perf_counter();result=observe(im,center,effect_y);timings.append((time.perf_counter()-start)*1000)
        static=vision.recognize(Frame(im,0,0,capture_source="saved_image"));cid=max(static["detail_score"],0)>=.98 or detail.recognize(im[151:301,27:130])["accepted"]
        enabled=static["scores"]["effect_hand6-slot3" if center==683 else "effect_hand7-slot3"]>=.98
        rows.append({"group":group,"path":str(path),"original_capture":item,"pose":result,"detail13906":cid,"enabled_effect":enabled,"source_UI_AND":bool(result["accepted"] and cid and enabled)})
    # 合成対応点だけの強/弱cluster。特徴抽出の実画像精度とは分離します。
    points,_=detail.references[0];size=np.ones(len(points),np.float32)*1.5
    a=np.vstack([points,points]);b=np.vstack([points*1.065+[627.4,558.0],points*1.065+[635.4,560.0]]).astype(np.float32)
    first,support=model(a,b,np.tile(size,2),683,524);second,_=model(a[~support],b[~support],np.tile(size,2)[~support],683,524)
    summary={group:{"cases":sum(r["group"]==group for r in rows),"pose":sum(r["pose"]["accepted"] for r in rows if r["group"]==group),"source_UI_AND":sum(r["source_UI_AND"] for r in rows if r["group"]==group)} for group in folders}
    report={"schema":"source-selected-art-comparison-v2","notice":"read-only・方法選択・sourceUI_ANDはselfMain1を含まない中間判定で実入力可否ではない。元画像/時計/runtime不変。",
        "condition":str(condition_path),"condition_sha256":hashlib.sha256(condition_path.read_bytes()).hexdigest(),"rows":rows,"summary":summary,
        "synthetic_correspondences":{"first":first,"second":second,"ambiguous":different([first,second]),"not_native_accuracy":True},
        "local_ms":{"mean":float(np.mean(timings)),"p50":float(np.percentile(timings,50)),"p95":float(np.percentile(timings,95)),"maximum":max(timings),"n":len(timings),"capture_decode_E2E_excluded":True}}
    output.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(output),"summary":summary,"synthetic":report["synthetic_correspondences"],"timing":report["local_ms"]},ensure_ascii=False))


if __name__=="__main__":run()
