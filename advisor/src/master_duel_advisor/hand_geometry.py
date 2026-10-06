"""既知normalメニュー直下のせり上がった手札矩形。CIDや合法手は判定しません。"""
from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np

PARAMETERS = {"roi_offset": [20, 70, 135, 150], "canny": [50, 150],
    "hough_rho": 1, "hough_theta_degrees": 1, "hough_threshold": 40,
    "minimum_line_length": 65, "maximum_line_gap": 8, "maximum_vertical_dx": 3,
    "maximum_horizontal_dy": 3, "left_offset": [30, 48], "right_offset": [126, 150],
    "top_offset": [70, 94], "pair_width": [80, 120], "minimum_overlap": 65,
    "connection_tolerance": 8, "maximum_lines": 128}
PARAMETERS_SHA256 = hashlib.sha256(json.dumps(PARAMETERS, sort_keys=True).encode()).hexdigest()


def connected_rectangle(vertical, horizontal, anchor):
    """上辺と同じ左右辺の交差を拘束。許容8pxはHoughの最大line gapと同じです。"""
    x, y = anchor
    for left in vertical:
        lx = (left[0]+left[2])/2
        if not x+30 <= lx <= x+48:
            continue
        for right in vertical:
            rx = (right[0]+right[2])/2
            if not x+126 <= rx <= x+150 or not 80 <= rx-lx <= 120:
                continue
            ly = sorted([left[1], left[3]]); ry = sorted([right[1], right[3]])
            if min(ly[1],ry[1])-max(ly[0],ry[0]) < 65:
                continue
            for top in horizontal:
                tx = sorted([top[0],top[2]]); ty = (top[1]+top[3])/2
                # Houghは角を越える同一直線も返します。端点ではなく両側への実線の交差を拘束。
                if (tx[0]-8 <= lx <= tx[1]+8 and tx[0]-8 <= rx <= tx[1]+8
                        and ly[0]-8 <= ty <= ly[1] and ry[0]-8 <= ty <= ry[1]
                        and min(ly[1],ry[1])-ty >= 65
                        and y+70 <= ty <= y+94):
                    return {"left": left, "right": right, "top": top}
    return None


def extend_vertical_with_edges(vertical, edges, roi):
    """線分端点の欠落を実edgeで補います。axis±3px、連続欠落は既存gap8まで。"""
    extended = []
    for line in vertical:
        xx = round((line[0]+line[2])/2)
        lower, upper = sorted([line[1],line[3]])
        first_supported = lower
        missing = 0
        left = max(0,xx-roi[0]-3); right = min(edges.shape[1],xx-roi[0]+4)
        for yy in range(lower-1,roi[1]-1,-1):
            if np.any(edges[yy-roi[1],left:right]):
                first_supported = yy
                missing = 0
            else:
                missing += 1
                if missing > 8:
                    break
        extended.append([xx,first_supported,xx,upper])
    return extended


def recognize_hand_geometry(pixels, evidence_bbox):
    if (not isinstance(pixels,np.ndarray) or pixels.shape != (720,1280,3) or pixels.dtype != np.uint8
            or len(evidence_bbox) != 4 or any(type(v) is not int for v in evidence_bbox)
            or evidence_bbox[2:] != (74,79) or not 316 <= evidence_bbox[0] <= 444
            or not 473 <= evidence_bbox[1] <= 521):
        raise ValueError("限定normalの実client画像と検出cropが必要です")
    x, y = evidence_bbox[:2]
    roi = (x+20,y+70,135,min(150,720-(y+70)))
    crop = pixels[roi[1]:roi[1]+roi[3],roi[0]:roi[0]+roi[2]]
    edges = cv2.Canny(cv2.cvtColor(crop,cv2.COLOR_BGR2GRAY),50,150)
    lines = cv2.HoughLinesP(edges,1,np.pi/180,40,minLineLength=65,maxLineGap=8)
    count = 0 if lines is None else len(lines)
    vertical, horizontal = [], []
    if count <= 128 and lines is not None:
        for a,b,c,d in lines[:,0,:]:
            a,b,c,d = map(int,(a,b,c,d))
            line = [a+roi[0],b+roi[1],c+roi[0],d+roi[1]]
            if abs(c-a) <= 3 and abs(d-b) >= 65:
                vertical.append(line)
            if abs(d-b) <= 3 and abs(c-a) >= 65 and y+70 <= min(line[1],line[3]) <= y+94:
                horizontal.append(line)
    extended = extend_vertical_with_edges(vertical,edges,roi)
    selected = connected_rectangle(extended,horizontal,(x,y))
    return {"schema": "raised-hand-connected-lines-v1", "passed": selected is not None,
        "roi": roi, "line_count": count, "selected_rectangle": selected,
        "vertical_lines": vertical, "top_lines": horizontal, "parameters_sha256": PARAMETERS_SHA256,
        "edge_supported_vertical_projections": extended,
        "confidence_semantics": "binary geometric constraints satisfied; not CID/probability/legal-action proof",
        "unknown_reason": None if selected is not None else "too_many_lines" if count > 128 else "connected_rectangle_not_found"}
