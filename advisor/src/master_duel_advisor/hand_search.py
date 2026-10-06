"""雷電龍の限定公開UI/公開face→手札episode。手札断片からCIDを生成しません。"""
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from .image_io import read_image
from .perception import fingerprint

TRACK = {"corners":24,"quality":.02,"distance":5,"window":21,"levels":3,
    "fb":1.5,"ransac":2.,"minimum_inliers":6,"ratio":.7,"scale":[.75,1.2],
    "dx":40,"dy":[-8,120],"entry_raise_dy":-50,"entry_y":585,"max_gap":.3}

TIME_EPSILON_SECONDS = 1e-9
HANDOFF_MAX_AGE_SECONDS = 3.0
DETAIL_ART_MODE="rgb_or_native_art_sift_v1"
DETAIL_ART_PARAMETERS={"art_inside_thumbnail":[12,30,78,72],"SIFT_nfeatures":200,"footprint_radius_factor":5.31,
    "support_boundary_tolerance_px":1e-12,
    "mutual_lowe":.75,"ransac_px":2.,"minimum_inliers":6,"minimum_ratio":.7,
    "scale":[.9,1.1],"shift_px":3,"art_spread":[39,36]}
SOURCE_ART_MODE="detail_to_selected_hand_art_v1"
SOURCE_ART_PARAMETERS={"candidate_roi":[-78,536,155,184],"candidate_nfeatures":300,"forward_lowe":.75,"ransac_px":2.,
    "minimum_inliers":6,"minimum_ratio":.7,"spread":[39,36],"scale":[.9,1.1],"rotation_degrees":3,
    "effect_to_art_top":[58,74],"art_center_to_effect_x":20,"same_position_merge_px":3,
    "max_probe_models_per_reference":2,"descriptor_radius_factor":5.31,"support_boundary_tolerance_px":1e-12}
PUBLIC_ART_MODE="native_public_art_common_support_v1"
PUBLIC_ART_PARAMETERS={"roi":[500,400,330,236],"candidate_features":800,"ratio":.75,"inliers":6,"inlier_ratio":.7,
    "spread":[39,36],"scale":[.9,1.25],"rotation_abs":3,"fullface_width":[100,130],"fullface_height":[145,190],
    "edge_support_min":.35,"edge_strip_radius":2,"probe_models":2,"common_scene_support":6,
    "common_ref_spread":[39,36],"common_scene_residual_px":2.,"descriptor_radius_factor":5.31,
    "support_boundary_tolerance_px":1e-12}


def art_keypoint_inside(point):
    """descriptor全支持をart内部へ制限。共通枠/星/本文を使いません。"""
    _,_,w,h=DETAIL_ART_PARAMETERS["art_inside_thumbnail"]
    x,y=point.pt;radius=DETAIL_ART_PARAMETERS["footprint_radius_factor"]*point.size
    clearance=min(x,y,w-1-x,h-1-y)
    return bool(all(math.isfinite(v) for v in (x,y,radius)) and radius>0
        and (radius<=clearance or math.isclose(radius,clearance,rel_tol=0.,
            abs_tol=DETAIL_ART_PARAMETERS["support_boundary_tolerance_px"])))


class NativeArtDetails:
    """既知13906の公開detail artだけの局所勾配照合。CID/所属の一般判定ではありません。"""
    def __init__(self,references):
        self.sift=cv2.SIFT_create(nfeatures=DETAIL_ART_PARAMETERS["SIFT_nfeatures"])
        self.matcher=cv2.BFMatcher(cv2.NORM_L2)
        self.references=[self.features(image) for image in references]

    def features(self,image):
        if image.shape!=(150,103,3) or image.dtype!=np.uint8:raise ValueError("native detail thumbnail寸法不一致")
        x,y,w,h=DETAIL_ART_PARAMETERS["art_inside_thumbnail"]
        keypoints,descriptors=self.sift.detectAndCompute(cv2.cvtColor(image[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY),None)
        keep=[i for i,p in enumerate(keypoints) if art_keypoint_inside(p)]
        coords=np.float32([np.float32(keypoints[i].pt)+np.float32([x,y]) for i in keep])
        return coords,descriptors[keep] if descriptors is not None and keep else None

    def compare(self,query,reference):
        points,descriptors=query;ref_points,ref_descriptors=reference
        result={"matches":0,"accepted":False}
        if descriptors is None or ref_descriptors is None or len(ref_descriptors)<2:
            result["reason"]="descriptors_absent";return result
        reverse={m.queryIdx:m.trainIdx for m in self.matcher.match(ref_descriptors,descriptors)}
        # forward Lowe ratioとreverse nearestの相互一致。reverse ratioは使いません。
        pairs=[pair[0] for pair in self.matcher.knnMatch(descriptors,ref_descriptors,k=2)
            if len(pair)==2 and pair[0].distance<DETAIL_ART_PARAMETERS["mutual_lowe"]*pair[1].distance
            and reverse.get(pair[0].trainIdx)==pair[0].queryIdx]
        result["matches"]=len(pairs)
        if len(pairs)<DETAIL_ART_PARAMETERS["minimum_inliers"]:
            result["reason"]="matches_under6";return result
        original=np.float32([ref_points[p.trainIdx] for p in pairs]);current=np.float32([points[p.queryIdx] for p in pairs])
        affine,inliers=cv2.estimateAffinePartial2D(original,current,method=cv2.RANSAC,
            ransacReprojThreshold=DETAIL_ART_PARAMETERS["ransac_px"],maxIters=300,confidence=.99)
        if affine is None or inliers is None:result["reason"]="affine_missing";return result
        supported=inliers.ravel().astype(bool)
        if not supported.any():result["reason"]="inliers_absent";return result
        spread=np.ptp(original[supported],axis=0);scale=float(np.hypot(affine[0,0],affine[0,1]))
        count=int(supported.sum());ratio=float(supported.mean())
        checks={"inliers":count>=DETAIL_ART_PARAMETERS["minimum_inliers"],"ratio":ratio>=DETAIL_ART_PARAMETERS["minimum_ratio"],
            "scale":DETAIL_ART_PARAMETERS["scale"][0]<=scale<=DETAIL_ART_PARAMETERS["scale"][1],
            "shift":bool(max(abs(affine[:,2]))<=DETAIL_ART_PARAMETERS["shift_px"]),
            "spread":bool(np.all(spread>=DETAIL_ART_PARAMETERS["art_spread"]))}
        result.update(inliers=count,ratio=ratio,spread=spread.tolist(),scale=scale,shift=affine[:,2].tolist(),
            accepted=all(checks.values()),reason=[name for name,ok in checks.items() if not ok])
        return result

    def recognize(self,image):
        query=self.features(image);results=[self.compare(query,reference) for reference in self.references]
        return {"accepted":any(r["accepted"] for r in results),"keypoints":len(query[0]),"references":results}


class SelectedHandArt:
    """既知detailのart→選択hand内の実art。card外枠/未観測部分を補いません。"""
    def __init__(self,details):
        self.references=details.references
        self.sift=cv2.SIFT_create(nfeatures=SOURCE_ART_PARAMETERS["candidate_nfeatures"])
        self.matcher=cv2.BFMatcher(cv2.NORM_L2)

    def model(self,original,current,sizes,effect_point):
        row={"accepted":False,"pairs":len(original)}
        empty=np.zeros(len(original),bool)
        if len(original)<6:return row,empty
        matrix,mask=cv2.estimateAffinePartial2D(original,current,method=cv2.RANSAC,
            ransacReprojThreshold=2.,maxIters=300,confidence=.99)
        if matrix is None or mask is None:return row,empty
        scale=float(np.hypot(matrix[0,0],matrix[0,1]));angle=float(np.degrees(np.arctan2(matrix[1,0],matrix[0,0])))
        if scale<=0:return row,empty
        mapped=cv2.transform(current[None],cv2.invertAffineTransform(matrix))[0]
        clearance=np.min(np.stack([mapped[:,0]-12,mapped[:,1]-30,89-mapped[:,0],101-mapped[:,1]]),axis=0)
        supported=mask.ravel().astype(bool)&(5.31*sizes/scale<=clearance+1e-12)
        n=int(supported.sum())
        if n<6:row.update(reason="supported_under6",inliers=n);return row,supported
        spread=np.ptp(original[supported],axis=0);ratio=n/len(original)
        corners=cv2.transform(np.float32([[[12,30],[90,30],[90,102],[12,102]]]),matrix)[0]
        art_bbox=[float(corners[:,0].min()),float(corners[:,1].min()),float(np.ptp(corners[:,0])),float(np.ptp(corners[:,1]))]
        checks={"inliers":n>=6,"ratio":ratio>=.7,"spread":bool(np.all(spread>=[39,36])),"scale":.9<=scale<=1.1,
            "rotation":abs(angle)<=3,"relative_y":58<=art_bbox[1]-effect_point[1]<=74,
            "relative_x":abs(art_bbox[0]+art_bbox[2]/2-effect_point[0])<=20}
        row.update(accepted=all(checks.values()),inliers=n,ratio=ratio,spread=spread.tolist(),scale=scale,
            angle=angle,art_bbox=art_bbox,affine=matrix.tolist(),guards=checks,reason=[key for key,ok in checks.items() if not ok])
        return row,supported

    @staticmethod
    def different(models):
        valid=[model for model in models if model["accepted"]]
        return any(np.linalg.norm(np.array(a["art_bbox"][:2])-np.array(b["art_bbox"][:2]))>3 for a in valid for b in valid)

    def recognize(self,pixels,effect_point):
        center=effect_point[0];x,y,w,h=SOURCE_ART_PARAMETERS["candidate_roi"];x+=center
        keypoints,descriptors=self.sift.detectAndCompute(cv2.cvtColor(pixels[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY),None)
        result={"status":"unconfirmed","accepted":False,"primary":[],"ambiguity_models":[],"art_bbox":None}
        if descriptors is None:return result
        positions=np.float32([np.float32(p.pt)+np.float32([x,y]) for p in keypoints])
        sizes=np.float32([p.size for p in keypoints])
        for ref_index,(points,ref_desc) in enumerate(self.references):
            if ref_desc is None:continue
            reverse={m.queryIdx:m.trainIdx for m in self.matcher.match(descriptors,ref_desc)}
            pairs=[pair[0] for pair in self.matcher.knnMatch(ref_desc,descriptors,k=2) if len(pair)==2
                and pair[0].distance<.75*pair[1].distance and reverse.get(pair[0].trainIdx)==pair[0].queryIdx]
            a=np.float32([points[p.queryIdx] for p in pairs]);b=np.float32([positions[p.trainIdx] for p in pairs]);ss=np.float32([sizes[p.trainIdx] for p in pairs])
            positive,_=self.model(a,b,ss,effect_point);positive["reference_index"]=ref_index;result["primary"].append(positive)
            # negative専用。reverse相互制限で弱い別instanceを隠さず、各ref最大2モデル。
            probe=[pair[0] for pair in self.matcher.knnMatch(descriptors,ref_desc,k=2) if len(pair)==2 and pair[0].distance<.75*pair[1].distance]
            a=np.float32([points[p.trainIdx] for p in probe]);b=np.float32([positions[p.queryIdx] for p in probe]);ss=np.float32([sizes[p.queryIdx] for p in probe])
            for _ in range(SOURCE_ART_PARAMETERS["max_probe_models_per_reference"]):
                alternative,supported=self.model(a,b,ss,effect_point);alternative["reference_index"]=ref_index
                result["ambiguity_models"].append(alternative)
                if len(a)<6 or not supported.any():break
                a,b,ss=a[~supported],b[~supported],ss[~supported]
        result["ambiguous"]=self.different(result["primary"]+result["ambiguity_models"])
        # probeだけの陽性を操作許可へ使用しません。
        primary=[p for p in result["primary"] if p["accepted"]]
        result["accepted"]=bool(primary) and not result["ambiguous"]
        if result["accepted"]:
            result.update(status="supported",art_bbox=primary[0]["art_bbox"])
        return result


def file_sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class PublicHandArt:
    """公開ROI内の固有artと投影辺の近傍支持。全輪郭の確定や手札CID認識ではありません。"""
    def __init__(self,references):
        self.references=NativeArtDetails([cv2.resize(image,(103,150)) for image in references]).references
        self.sift=cv2.SIFT_create(nfeatures=PUBLIC_ART_PARAMETERS["candidate_features"])
        self.matcher=cv2.BFMatcher(cv2.NORM_L2)

    @staticmethod
    def compatible(first,second):
        """全pairの同scene支持で同個体を確認。距離mergeやsingle-linkは使用しません。"""
        def mapping(model):
            return {key:(p,v) for key,p,v in zip(model["candidate_ids"],model["reference_support_points"],model["scene_support_points"])}
        a,b=mapping(first),mapping(second);common=a.keys()&b.keys()
        if len(common)<6:return False
        for model,points in [(first,a),(second,b)]:
            original=np.array([points[key][0] for key in common]);current=np.array([points[key][1] for key in common])
            matrix=np.array(model["affine"]);predicted=original@matrix[:,:2].T+matrix[:,2]
            if (not np.all(np.ptp(original,axis=0)>=[39,36])
                    or not np.all(np.linalg.norm(predicted-current,axis=1)<=2)):return False
        return True

    @classmethod
    def resolve_models(cls,primary,probes):
        """primaryの許可とprobeの拒否役割を分離し、全pair同一性を要求します。"""
        valid=[r for r in primary+probes if r["accepted"]]
        ambiguous=any(not cls.compatible(a,b) for i,a in enumerate(valid) for b in valid[i+1:])
        positive=[(i,r) for i,r in enumerate(primary) if r["accepted"]]
        accepted=bool(positive) and not ambiguous
        representative=min(positive,key=lambda pair:(-pair[1]["inliers"],pair[1]["reference_index"],pair[0]))[1] if accepted else None
        return {"accepted":accepted,"ambiguous":ambiguous,"representative":representative}

    def model(self,original,current,sizes,positions,edge_band):
        row={"accepted":False,"pairs":len(original)};empty=np.zeros(len(original),bool)
        if len(original)<6:return row,empty
        matrix,mask=cv2.estimateAffinePartial2D(original,current,method=cv2.RANSAC,
            ransacReprojThreshold=2.,maxIters=300,confidence=.99)
        if matrix is None or mask is None:return row,empty
        scale=float(np.hypot(matrix[0,0],matrix[0,1]))
        if not math.isfinite(scale) or scale<=0:return row,empty
        mapped=cv2.transform(current[None],cv2.invertAffineTransform(matrix))[0]
        clearance=np.min(np.stack([mapped[:,0]-12,mapped[:,1]-30,89-mapped[:,0],101-mapped[:,1]]),axis=0)
        supported=mask.ravel().astype(bool)&(sizes*5.31/scale<=clearance+1e-12)
        count=int(supported.sum())
        if count<6:return row,supported
        corners=cv2.transform(np.float32([[[0,0],[102,0],[102,149],[0,149]]]),matrix)[0]
        left,top=corners.min(axis=0);right,bottom=corners.max(axis=0)
        angle=float(np.degrees(np.arctan2(matrix[1,0],matrix[0,0])))
        spread=np.ptp(original[supported],axis=0);supports=[]
        for start,end in zip(corners,np.roll(corners,-1,axis=0)):
            line=np.zeros_like(edge_band)
            cv2.line(line,tuple(np.round(start).astype(int)),tuple(np.round(end).astype(int)),255,1)
            samples=edge_band[line>0];supports.append(float(np.mean(samples>0)) if samples.size else 0.)
        inside=bool(500<=left and 400<=top and right<830 and bottom<636)
        checks={"ratio":count/len(original)>=.7,"spread":bool(np.all(spread>=[39,36])),"scale":.9<=scale<=1.25,
            "rotation":abs(angle)<=3,"roi":inside,"width":100<=right-left<=130,"height":145<=bottom-top<=190,
            "projected_edge_strip_support":min(supports)>=.35}
        row.update(accepted=all(checks.values()),inliers=count,ratio=count/len(original),spread=spread.tolist(),
            scale=scale,angle=angle,bbox=[float(left),float(top),float(right-left),float(bottom-top)],
            corners=corners.tolist(),roi_inside=inside,edge_support=supports,affine=matrix.tolist(),
            candidate_ids=[int(np.argmin(np.sum((positions-p)**2,axis=1))) for p in current[supported]],
            scene_support_points=current[supported].tolist(),reference_support_points=original[supported].tolist(),
            guards=checks,reason=[name for name,passed in checks.items() if not passed])
        return row,supported

    def recognize(self,pixels):
        if pixels.dtype!=np.uint8 or pixels.shape!=(720,1280,3):raise ValueError("公開faceはnative1280x720のみです")
        gray=cv2.cvtColor(pixels,cv2.COLOR_BGR2GRAY)
        keypoints,descriptors=self.sift.detectAndCompute(gray[400:636,500:830],None)
        result={"accepted":False,"ambiguous":False,"primary":[],"ambiguity_models":[],"representative":None}
        if descriptors is None:return result
        positions=np.float32([np.float32(p.pt)+[500,400] for p in keypoints]);sizes=np.float32([p.size for p in keypoints])
        edge_band=cv2.dilate(cv2.Canny(gray,50,150),np.ones((5,5),np.uint8))
        for index,(points,ref_desc) in enumerate(self.references):
            if ref_desc is None or len(ref_desc)<2:continue
            reverse={m.queryIdx:m.trainIdx for m in self.matcher.match(descriptors,ref_desc)}
            pairs=[pair[0] for pair in self.matcher.knnMatch(ref_desc,descriptors,k=2) if len(pair)==2
                and pair[0].distance<.75*pair[1].distance and reverse.get(pair[0].trainIdx)==pair[0].queryIdx]
            original=np.float32([points[p.queryIdx] for p in pairs]);current=np.float32([positions[p.trainIdx] for p in pairs])
            ss=np.float32([sizes[p.trainIdx] for p in pairs])
            row,_=self.model(original,current,ss,positions,edge_band);row["reference_index"]=index;result["primary"].append(row)
            # probeは別個体の拒否専用。primaryを新規陽性へ昇格させません。
            pairs=[pair[0] for pair in self.matcher.knnMatch(descriptors,ref_desc,k=2) if len(pair)==2 and pair[0].distance<.75*pair[1].distance]
            original=np.float32([points[p.trainIdx] for p in pairs]);current=np.float32([positions[p.queryIdx] for p in pairs])
            ss=np.float32([sizes[p.queryIdx] for p in pairs])
            for _ in range(2):
                row,supported=self.model(original,current,ss,positions,edge_band)
                row["reference_index"]=index;result["ambiguity_models"].append(row)
                if not supported.any():break
                original,current,ss=original[~supported],current[~supported],ss[~supported]
        result.update(self.resolve_models(result["primary"],result["ambiguity_models"]))
        return result


def activation_parent_valid(context,goal,frame,profile_sha,*,logical_action=None):
    """新取得の自己chainを実親ACTIVATEに結合。過去phaseを現在stateへ転記しません。"""
    if not context or context.get("result") is not None or not context.get("action_id"):
        return False
    if (context.get("hand_search_confirmation")!=goal.model_dump(mode="json")
            or not logical_action or context.get("logical_action")!=logical_action):return False
    steps=context.get("steps",[])
    if len(steps)!=1:return False  # 既送信Cancelの再発行も拒否。
    step=steps[0];action=step.get("action") or {};before=step.get("hand_before") or {};proof=action.get("hand_search_proof") or {}
    if (step.get("input_sent") is not True or step.get("input_epoch_verified") is not True
            or step.get("result")!="changed" or action.get("type")!="ACTIVATE" or action.get("card_id")!="13906"
            or action.get("source_region")!=goal.activate_region or action.get("target") is not None
            or step.get("capture_source")!="live_mss" or step.get("capture_input_epoch") is None
            or step.get("capture_rect")!=step.get("client_rect")
            or frame.capture_source!="live_mss" or frame.capture_rect!=tuple(step.get("client_rect") or ())
            or frame.input_epoch is None or frame.input_epoch!=step.get("input_epoch")
            or frame.sequence<=step.get("before_sequence",frame.sequence)
            or frame.sequence<step.get("after_sequence",frame.sequence+1)
            or frame.captured_at<=step.get("capture_monotonic",frame.captured_at)
            or proof.get("profile_sha256")!=profile_sha or proof.get("frame_seq")!=step.get("before_sequence")
            or proof.get("observed_at")!=step.get("capture_monotonic")):return False
    box=proof.get("evidence_bbox");point=proof.get("point");rect=step.get("client_rect")
    if (proof.get("client_rect")!=rect or proof.get("action_type")!="ACTIVATE"
            or not box or len(box)!=4 or not point or len(point)!=2
            or not 0<=box[0]<=point[0]<box[0]+box[2]<=1280
            or not 0<=box[1]<=point[1]<box[1]+box[3]<=720
            or step.get("screen_point")!=[rect[0]+point[0],rect[1]+point[1]]):return False
    for key,value in [("phase","MAIN1"),("turn_player","self")]:
        obs=before.get(key) or {}
        if obs.get("value")!=value or obs.get("confidence",0)<.98 or obs.get("observed_at")!=before.get("captured_at"):return False
    for key,value in [(goal.source_ready_fact,"true"),(goal.detail_fact,"13906")]:
        obs=(before.get("facts") or {}).get(key) or {}
        if (obs.get("value")!=value or obs.get("confidence",0)<.98 or obs.get("observed_at")!=before.get("captured_at")
                or obs.get("source")!="hand_search:"+profile_sha):return False
    return True


def local_card_rectangle(pixels,roi,top_range,center_x):
    """公開手札の局所接続辺。CID/手札全体の絵柄は判定しません。"""
    x,y,w,h=map(int,roi);w=min(w,1280-x);h=min(h,720-y)
    if not (0<=x<x+w<=1280 and 0<=y<y+h<=720):return None
    edges=cv2.Canny(cv2.cvtColor(pixels[y:y+h,x:x+w],cv2.COLOR_BGR2GRAY),50,150)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,40,minLineLength=65,maxLineGap=8)
    if lines is None or len(lines)>128:return None
    vertical=[];horizontal=[]
    for a,b,c,d in lines[:,0,:]:
        line=[int(a)+x,int(b)+y,int(c)+x,int(d)+y]
        if abs(c-a)<=3 and abs(d-b)>=65:vertical.append(line)
        if abs(d-b)<=3 and abs(c-a)>=65 and top_range[0]<=min(line[1],line[3])<=top_range[1]:horizontal.append(line)
    # 混雑したhand/fieldではedge strip延長が背景の横線まで接続します。
    # この局所APIは実Hough線分の交差だけを使い、欠落した辺を補完しません。
    candidates=[]
    for left in vertical:
        lx=(left[0]+left[2])/2
        for right in vertical:
            rx=(right[0]+right[2])/2
            if not 80<=rx-lx<=120 or abs((lx+rx)/2-center_x)>20:continue
            ly=sorted([left[1],left[3]]);ry=sorted([right[1],right[3]])
            for top in horizontal:
                tx=sorted([top[0],top[2]]);ty=(top[1]+top[3])/2
                if (tx[0]-8<=lx<=tx[1]+8 and tx[0]-8<=rx<=tx[1]+8
                        and ly[0]-8<=ty<=ly[1] and ry[0]-8<=ty<=ry[1]
                        and min(ly[1],ry[1])-ty>=65):
                    candidates.append({"left":left,"right":right,"top":top,"bbox":[round(lx),round(ty),round(rx-lx),round(min(ly[1],ry[1])-ty)]})
    return min(candidates,key=lambda r:abs(r["bbox"][0]+r["bbox"][2]/2-center_x)) if candidates else None


def ready_visible_card(pixels,handoff_bbox):
    """実handoff内の可視上辺/左辺と安全点。隠れた右辺/下辺は生成しません。

    CIDは公開anchorのepisodeに属し、この形状APIでは判定しません。
    接続許容8pxは既存Houghのgap分解能、傾き8pxは収納後のfan辺専用です。
    """
    if pixels.shape!=(720,1280,3) or len(handoff_bbox)!=4:return None
    x,y,w,h=map(float,handoff_bbox)
    if (not all(math.isfinite(v) for v in (x,y,w,h)) or not 80<=w<=120
            or not 110<=h<=190 or not 0<=x<x+w<=1280 or not 585<=y<=655):return None
    rx=max(0,math.floor(x-8));ry=math.floor(y-8)
    ex=min(1280,math.ceil(x+w+8));ey=min(720,math.ceil(y+h))
    # card絵柄の斜線と投票を競わせず、handoff左端/上端の帯を別々に抽出。
    # 上端16pxは接続許容8px＋fan辺8px。元card矩形へは拡張しません。
    bands=[(rx,ry,min(ex,math.ceil(x+8)),ey),(rx,ry,ex,min(ey,math.ceil(y+16)))]
    lines=[]
    for ax,ay,bx,by in bands:
        edge=cv2.Canny(cv2.cvtColor(pixels[ay:by,ax:bx],cv2.COLOR_BGR2GRAY),50,150)
        raw=cv2.HoughLinesP(edge,1,np.pi/180,40,minLineLength=65,maxLineGap=8)
        if raw is not None:
            lines.extend([[int(a)+ax,int(b)+ay,int(c)+ax,int(d)+ay] for a,b,c,d in raw[:,0,:]])
    if not lines or len(lines)>128:return None
    vertical=[];tops=[]
    for line in lines:
        a,b,c,d=line
        if abs(c-a)<=8 and abs(d-b)>=65 and abs((a+c)/2-x)<=8:
            vertical.append(line)
        if abs(d-b)<=8 and abs(c-a)>=65 and abs((b+d)/2-y)<=16:
            tops.append(line)
    candidates=[]
    for left in vertical:
        if left[1]>left[3]:left=[left[2],left[3],left[0],left[1]]
        for top in tops:
            if top[0]>top[2]:top=[top[2],top[3],top[0],top[1]]
            # 傾いた可視辺の左側交点で接続を検証します。
            tx=(left[0]+left[2])/2
            ty=top[1]+(top[3]-top[1])*(tx-top[0])/(top[2]-top[0])
            lx=left[0]+(left[2]-left[0])*(ty-left[1])/(left[3]-left[1])
            if not (left[1]-8<=ty<=left[3]-65 and top[0]-8<=lx<=top[2]
                    and top[2]-lx>=65):continue
            # 8px inset内だけを使います。top右端は実可視辺の端でありcard右辺ではありません。
            safe_left=math.ceil(max(lx,left[0],left[2],x)+8)
            safe_top=math.ceil(max(ty,y)+8)
            safe_right=math.floor(min(top[2],x+w)-8)
            safe_bottom=math.floor(min(left[3],y+h,720)-8)
            px=math.floor(x+w/2)
            if not (safe_left<px<safe_right and safe_bottom-safe_top>=40):continue
            candidates.append({"left":left,"top":top,
                "bbox":[safe_left,safe_top,safe_right-safe_left,safe_bottom-safe_top],
                "point":[px,(safe_top+safe_bottom)//2],"role":"handoff_visible_interior"})
    return min(candidates,key=lambda c:abs((c["top"][1]+c["top"][3])/2-y)) if candidates else None


class HandSearchVision:
    def __init__(self,path):
        self.path=Path(path).resolve();self.sha256=file_sha(self.path)
        self.config=json.loads(self.path.read_text(encoding="utf-8"))
        if self.config.get("schema")!="dragondark-hand-search-v1" or self.config.get("tracking")!=TRACK:
            raise ValueError("手札search固定方式/観測段階が一致しません")
        self.files={str(self.path):self.sha256};self.scenes={};self.public=[]
        for name,spec in self.config["scenes"].items():
            refs=[self.load(ref) for ref in spec["references"]]
            samples=np.stack([fingerprint(img) for img in refs]);proto=np.median(samples,axis=0)
            mask=np.max(np.mean(abs(samples-proto),axis=3),axis=0)<=.01
            if int(mask.sum())<256:raise ValueError("hand-search scene安定画素が256未満: "+name)
            self.scenes[name]=(spec,proto,mask)
        refs=self.config.get("detail_references",[self.config.get("detail_reference")])
        native_details=[read_image(self.asset(ref)) for ref in refs]
        self.details=[cv2.resize(image,(64,96),interpolation=cv2.INTER_AREA).astype(np.float32)/255 for image in native_details]
        self.detail_mode=self.config.get("detail_recognition_mode","rgb")
        if self.detail_mode not in {"rgb",DETAIL_ART_MODE}:raise ValueError("未知のdetail方式")
        if self.detail_mode==DETAIL_ART_MODE and self.config.get("detail_art_parameters")!=DETAIL_ART_PARAMETERS:
            raise ValueError("detail art固定条件不一致")
        self.detail_art=NativeArtDetails(native_details) if self.detail_mode==DETAIL_ART_MODE else None
        self.source_mode=self.config.get("source_art_mode","hough_rectangle")
        if self.source_mode not in {"hough_rectangle",SOURCE_ART_MODE}:raise ValueError("未知source所属方式")
        if self.source_mode==SOURCE_ART_MODE and self.config.get("source_art_parameters")!=SOURCE_ART_PARAMETERS:
            raise ValueError("source art固定条件不一致")
        self.source_art=SelectedHandArt(self.detail_art or NativeArtDetails(native_details)) if self.source_mode==SOURCE_ART_MODE else None
        public_images=[self.load(ref) for ref in self.config["public_references"]]
        self.public=[cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) for image in public_images]
        if len(self.public)!=4:raise ValueError("公開fullface4参照が必要です")
        self.public_mode=self.config.get("public_anchor_mode","gray_ncc_v1")
        if self.public_mode not in {"gray_ncc_v1",PUBLIC_ART_MODE}:raise ValueError("未知public anchor方式")
        if self.public_mode==PUBLIC_ART_MODE and self.config.get("public_art_parameters")!=PUBLIC_ART_PARAMETERS:
            raise ValueError("public art固定条件不一致")
        self.public_art=PublicHandArt(public_images) if self.public_mode==PUBLIC_ART_MODE else None
        self.files[str(Path(__file__).resolve())]=file_sha(__file__)
        self.stats={name:(Path(name).stat().st_size,Path(name).stat().st_mtime_ns) for name in self.files}
        self.episode=None;self.points=None;self.box=None;self.gray=None

    def asset(self,ref):
        path=(self.path.parent/ref["image"]).resolve()
        if not path.is_relative_to(self.path.parent) or file_sha(path)!=ref["sha256"]:
            raise ValueError("手札search asset path/hash不一致")
        self.files[str(path)]=ref["sha256"]
        return path

    def load(self,ref):return read_image(self.asset(ref))

    def assert_unchanged(self):
        for name,expected in self.stats.items():
            stat=Path(name).stat()
            if (stat.st_size,stat.st_mtime_ns)!=expected:raise ValueError("手札search固定asset変更")

    def provenance(self):
        return {"profile_sha256":self.sha256,"files":dict(self.files),"tracking":TRACK,
            "detail_recognition":{"mode":self.detail_mode,"parameters":DETAIL_ART_PARAMETERS if self.detail_art else None,
                "reference_hashes":[r["sha256"] for r in self.config.get("detail_references",[self.config.get("detail_reference")])]},
            "source_recognition":{"mode":self.source_mode,"parameters":SOURCE_ART_PARAMETERS if self.source_art else None},
            "public_anchor":{"mode":self.public_mode,"parameters":PUBLIC_ART_PARAMETERS if self.public_art else None,
                "reference_hashes":[r["sha256"] for r in self.config["public_references"]],
                "edge_evidence":"2px-neighborhood Canny support of projected sides; not complete visible outline"},
            "scope":"known hand6/7 source slot3 only; destination from observed handoff bbox; binary predicates, not probabilities"}

    def scene_scores(self,pixels):
        scores={}
        for name,(spec,proto,mask) in self.scenes.items():
            x,y,w,h=spec["rect"];feature=fingerprint(pixels[y:y+h,x:x+w])
            scores[name]=float(1-np.mean(abs(feature-proto)[mask]))
        return scores

    def recognize(self,frame):
        self.assert_unchanged();pixels=frame.pixels
        if pixels.dtype!=np.uint8 or pixels.shape!=(720,1280,3):raise ValueError("hand-searchはnative1280x720のみです")
        score=self.scene_scores(pixels)
        detail=cv2.resize(pixels[151:301,27:130],(64,96),interpolation=cv2.INTER_AREA).astype(np.float32)/255
        detail_score=max(float(1-np.mean(abs(detail-ref))) for ref in self.details)
        art=self.detail_art.recognize(pixels[151:301,27:130]) if self.detail_art and detail_score<.98 else {
            "accepted":False,"reason":"rgb_sufficient" if detail_score>=.98 else "art_not_configured"}
        detail_recognition="rgb" if detail_score>=.98 else "native_art_sift" if art["accepted"] else None
        def positive(name):return score.get(name,0)>=.98
        source=[];geometry={};source_poses={}
        for layout in ["hand6-slot3","hand7-slot3"]:
            center=self.config["layouts"][layout]["effect_point"][0]
            if self.source_art is None:
                geometry[layout]=local_card_rectangle(pixels,(center-78,536,155,150),(540,592),center)
                supported=geometry[layout] is not None
            else:
                geometry[layout]=None  # Hough診断は新modeで省略。artをfullcard bboxへ転記しません。
                applicable=detail_recognition is not None and positive("effect_"+layout)
                pose=self.source_art.recognize(pixels,self.config["layouts"][layout]["effect_point"]) if applicable else {
                    "status":"not_applicable","accepted":None,"reason":"detail_or_effect_unconfirmed","art_bbox":None}
                pose.update(frame_seq=frame.sequence,observed_at=frame.captured_at,detail_cid="13906" if detail_recognition else None,
                    reference_hashes=[r["sha256"] for r in self.config["detail_references"]])
                source_poses[layout]=pose;supported=pose["accepted"] is True and not pose.get("ambiguous",False)
            if supported and positive("effect_"+layout) and detail_recognition is not None:
                source.append(layout)
        source_layout=source[0] if len(source)==1 else None
        return {"scores":score,"detail_score":detail_score,"detail_cid":"13906" if detail_recognition is not None else None,
            "detail_recognition":detail_recognition,"detail_art":art,
            "source_art_pose":source_poses,"source_geometry_mode":"hough_rectangle" if self.source_art is None else "not_run_source_art_mode",
            "source_layout":source_layout,"source_geometry":geometry,"own_chain":positive("own_chain"),"gy_panel":positive("gy_panel"),
            "ready_layouts":[layout for layout in ["hand6-slot3","hand7-slot3"] if positive("ready_"+layout)],
            "selected_layouts":[layout for layout in ["hand6-slot3","hand7-slot3"] if positive("selected_"+layout)]}

    def invalidate(self,reason):
        if self.episode:self.episode.update(failed=reason,ready=False)
        self.points=None

    def pre_entry_upward_supported(self,episode,frame,points,flowbox):
        """品質条件を通過したflowだけに呼ぶ、現在一意公開faceの入場前例外。"""
        result={"permitted":False,"reason":"not_pre_entry_art_mode"}
        if (self.public_art is None or episode.get("entered")
                or (episode.get("anchor") or {}).get("cid")!="13906"):return result
        candidate=self.public_art.recognize(frame.pixels)
        face=candidate["representative"]
        result.update(candidate=candidate,frame_seq=frame.sequence,observed_at=frame.captured_at)
        if not candidate["accepted"] or candidate["ambiguous"] or face is None:return result
        left,top,width,height=face["bbox"]
        contained=bool(len(points)>=6 and np.all((points[:,0]>=left)&(points[:,0]<=left+width)
            &(points[:,1]>=top)&(points[:,1]<=top+height)))
        l,t=flowbox.min(axis=0);r,b=flowbox.max(axis=0)
        inside=bool(500<=l and 400<=t and r<830 and b<636 and face["roi_inside"])
        result.update(permitted=contained and inside,all_good_points_contained=contained,
            both_bboxes_inside_public_roi=inside,reason=None if contained and inside else "containment_failed")
        return result

    def observe(self,frame,context,static):
        """実receipt contextのあるverifyだけ追跡。初回認識/保存画像を操作証拠へ昇格しません。"""
        if not context:return None
        steps=context.get("steps",[])
        if not steps or not context.get("hand_search_confirmation"):return None
        first=steps[0];last=steps[-1]
        if (first.get("input_sent") is not True or last.get("input_sent") is not True
                or frame.capture_source!="live_mss" or frame.capture_rect!=tuple(last.get("client_rect") or ())
                or frame.input_epoch!=last.get("input_epoch") or frame.sequence<=last["before_sequence"]):
            self.invalidate("receipt_capture_scope_mismatch");return self.episode
        if self.episode is None or self.episode["action_id"]!=context["action_id"]:
            before=first.get("hand_before",{});layout=before.get("facts",{}).get("hand_search.layout",{}).get("value")
            if layout not in self.config["layouts"]:return None
            self.episode={"action_id":context["action_id"],"layout":layout,"profile_sha256":self.sha256,
                "source_sequence":first["before_sequence"],"anchor":None,"handoff":None,"trace":[],"failed":None,"ready":False}
            self.points=None;self.gray=None
        episode=self.episode
        if episode["failed"] or len(steps)<2:return episode
        # handoff後も同じnonce/取得時刻順を検査。early returnで迂回しません。
        if episode.get("anchor") is not None:
            if (not math.isfinite(frame.captured_at) or frame.sequence<=episode["last_seq"]
                    or frame.captured_at<=episode["last_at"]):
                self.invalidate("expired_or_repeated_frame");return episode
        if episode["handoff"] and frame.captured_at-episode["handoff"]["at"]>HANDOFF_MAX_AGE_SECONDS+TIME_EPSILON_SECONDS:
            self.invalidate("expired_handoff");return episode
        if static["own_chain"] or static["gy_panel"]:return episode
        if episode["handoff"]:
            self.update_hand_geometry(frame,static)
            episode.update(last_seq=frame.sequence,last_at=frame.captured_at)
            return episode
        gray=cv2.cvtColor(frame.pixels,cv2.COLOR_BGR2GRAY)
        if self.points is None:
            if self.public_art is not None:
                candidate=self.public_art.recognize(frame.pixels)
                episode["public_anchor_diagnostic"]=candidate
                if not candidate["accepted"] or candidate["ambiguous"]:return episode
                representative=candidate["representative"];x,y,w,h=representative["bbox"]
            else:
                roi=gray[400:636,500:830];best=(-1,None,None)
                for ref in self.public:
                    for scale in [.96,1.,1.04]:
                        template=cv2.resize(ref,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
                        values=cv2.matchTemplate(roi,template,cv2.TM_CCOEFF_NORMED)
                        _,score,_,point=cv2.minMaxLoc(values)
                        if score>best[0]:best=(score,point,template.shape)
                if best[0]<.98:return episode
                x,y=500+best[1][0],400+best[1][1];h,w=best[2]
            xx,yy,ww,hh=map(round,[x,y,w,h])
            mask=np.zeros_like(gray);mask[yy+14:yy+hh-24,xx+8:xx+ww-8]=255
            self.points=cv2.goodFeaturesToTrack(gray,24,.02,5,mask=mask)
            if self.points is None or len(self.points)<6:return episode
            self.box=np.float32([[x,y],[x+w,y],[x+w,y+h],[x,y+h]])
            anchor={"seq":frame.sequence,"at":frame.captured_at,"bbox":[x,y,w,h],"cid":"13906"}
            if self.public_art is not None:
                ref_index=representative["reference_index"]
                anchor.update(method=self.public_mode,pose=representative,representative_ref=ref_index,
                    reference_sha256=self.config["public_references"][ref_index]["sha256"],profile_sha256=self.sha256)
            else:anchor["score"]=best[0]
            episode.update(anchor=anchor,
                entered=False,raised=False,last_seq=frame.sequence,last_at=frame.captured_at)
            self.gray=gray
            return episode
        delta_time=frame.captured_at-episode["last_at"]
        if not 0<delta_time<=TRACK["max_gap"]+TIME_EPSILON_SECONDS:
            self.invalidate("expired_or_repeated_frame");return episode
        left,top=self.box.min(axis=0);right,bottom=self.box.max(axis=0)
        x,y=int(round(left)),int(round(top));w=int(round(right-left));h=min(int(round((bottom-top)*.65)),720-y)
        if not (0<=x<x+w<=1280 and 0<=y<y+h<=720):self.invalidate("track_box_outside");return episode
        fragment=self.gray[y:y+h,x:x+w];lower=-50 if episode["entered"] and not episode["raised"] else -8
        sx=max(0,x-40);sy=max(0,y+lower);ex=min(1280,x+w+40);ey=min(720,y+h+120);roi=gray[sy:ey,sx:ex]
        candidates=[];maps=[]
        for scale in [.8,.9,1.,1.1]:
            ref=cv2.resize(fragment,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
            if ref.shape[0]>roi.shape[0] or ref.shape[1]>roi.shape[1]:continue
            values=cv2.matchTemplate(roi,ref,cv2.TM_CCOEFF_NORMED);_,score,_,point=cv2.minMaxLoc(values)
            candidates.append((score,point[0]+sx,point[1]+sy,scale));maps.append(values)
        if not candidates:self.invalidate("no_coarse_candidate");return episode
        best=max(candidates);bx,by=best[1:3];runner=0.
        for values in maps:
            masked=values.copy();l=max(0,int(bx-sx-w/2));r=min(masked.shape[1],int(bx-sx+w/2)+1)
            u=max(0,int(by-sy-h/2));d=min(masked.shape[0],int(by-sy+h/2)+1);masked[u:d,l:r]=-1
            runner=max(runner,float(masked.max()))
        prediction=(self.points-np.float32([x,y]))*best[3]+np.float32([bx,by])
        new,status,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,self.points,prediction.copy(),winSize=(21,21),maxLevel=3,flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
        back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,new,self.points.copy(),winSize=(21,21),maxLevel=3,flags=cv2.OPTFLOW_USE_INITIAL_FLOW)
        fb=np.linalg.norm(back-self.points,axis=2).ravel();good=(status.ravel()>0)&(back_status.ravel()>0)&(fb<=1.5)
        old=self.points[good].reshape(-1,2);new_good=new[good].reshape(-1,2)
        if len(old)<6:self.invalidate("track_points_under6");return episode
        affine,inliers=cv2.estimateAffinePartial2D(old,new_good,method=cv2.RANSAC,ransacReprojThreshold=2.,maxIters=300,confidence=.99)
        if affine is None:self.invalidate("no_affine");return episode
        selected=inliers.ravel().astype(bool);scale=float(np.hypot(affine[0,0],affine[0,1]));box=cv2.transform(self.box[None],affine)[0]
        displacement=box.mean(axis=0)-self.box.mean(axis=0)
        other_motion=(int(selected.sum())>=6 and np.mean(selected)>=.7 and .75<=scale<=1.2
            and abs(displacement[0])<=40 and best[0]-runner>=.03)
        dy_supported=lower<=displacement[1]<=120
        pre_entry_upward=False
        if other_motion and not dy_supported and displacement[1]<lower and self.public_art is not None:
            stage=self.pre_entry_upward_supported(episode,frame,new_good,box)
            episode["pre_entry_upward_diagnostic"]=stage
            pre_entry_upward=stage["permitted"]
        good_motion=other_motion and (dy_supported or pre_entry_upward)
        if not good_motion:self.invalidate("track_quality_or_ambiguous");return episode
        if episode["entered"] and displacement[1]<-8:episode["raised"]=True
        if box[:,1].min()>=585:episode["entered"]=True
        record={"seq":frame.sequence,"at":frame.captured_at,"bbox":[float(box[:,0].min()),float(box[:,1].min()),float(np.ptp(box[:,0])),float(np.ptp(box[:,1]))],
            "points":len(old),"inliers":int(selected.sum()),"ratio":float(np.mean(selected)),"scale":scale,
            "dx":float(displacement[0]),"dy":float(displacement[1]),"coarse_margin":best[0]-runner}
        if self.public_art is not None:record["pre_entry_upward_exception"]=pre_entry_upward
        episode["trace"].append(record)
        if episode["raised"] and box[:,1].min()>=585:
            episode["handoff"]=record
            self.update_hand_geometry(frame,static)
        self.box=box;self.points=new_good[selected].reshape(-1,1,2).astype(np.float32);self.gray=gray
        episode.update(last_seq=frame.sequence,last_at=frame.captured_at)
        return episode

    def update_hand_geometry(self,frame,static):
        ep=self.episode;x,y,w,h=ep["handoff"]["bbox"];center=x+w/2
        ready=ready_visible_card(frame.pixels,ep["handoff"]["bbox"])
        selected=local_card_rectangle(frame.pixels,(round(center-78),max(0,round(y-68)),155,180),(round(y-68),round(y-15)),center)
        ep["current_ready_geometry"]=ready;ep["current_selected_geometry"]=selected
        ep["ready"]=ready is not None and not static["own_chain"] and not static["gy_panel"]
