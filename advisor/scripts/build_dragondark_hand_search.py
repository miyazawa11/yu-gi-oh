"""完成原MSSから限定hand-search校正を新規作成。入力画像を上書きしません。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from master_duel_advisor.hand_search import TRACK,DETAIL_ART_MODE,DETAIL_ART_PARAMETERS,SOURCE_ART_MODE,SOURCE_ART_PARAMETERS,PUBLIC_ART_MODE,PUBLIC_ART_PARAMETERS
from master_duel_advisor.image_io import read_image,write_image
from master_duel_advisor.strategy_rules import StrategyBook,LogicalHandSearchConfirmation

ROOT=Path(__file__).resolve().parents[1]
V1=ROOT/"artifacts/baseline-tester/DRAGONDARK_SEARCH_TRAIN_v1_20261006"
V2=ROOT/"artifacts/baseline-tester/DRAGONDARK_REVEAL_TEMPORAL_TRAIN_v2_20261006"


def records(folder):
    manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"));rows=[]
    for item in manifest["frames"]:
        path=(folder/item["file"]).resolve()
        if (not path.is_relative_to(folder.resolve()) or not item["eligible"]
                or hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]):
            raise ValueError("原MSS入力整合性不成立: "+str(path))
        rows.append((path,item))
    return rows


def build(output):
    output=Path(output).resolve();base=ROOT/"artifacts/solo-basic-calibration-v5"
    if (output.exists() or not output.is_relative_to(ROOT.resolve())
            or any(output.is_relative_to(src.resolve()) for src in [base,ROOT/"artifacts/baseline-tester"])):
        raise ValueError("新規workspace出力かつ全入力非重複のみです")
    groups={"before6":records(V1/"effect-menu-before"),"before7":records(V2/"effect-menu-before"),
        "chain":records(V1/"own-chain-optional-before")+records(V2/"own-chain-before"),
        "ready6":records(V1/"post-search-hand-unselected"),"selected6":records(V1/"post-search-hand-inspected"),
        "selected7":records(V2/"post-reveal-fresh-hand-inspect"),"gy":records(V1/"gy-list-before-fresh-inspect")}
    burst=records(V2/"chain-cancel-reveal-continuous");groups["ready7"]=burst[41:51]
    fixed=json.loads((ROOT/"evaluation/solo-basic-fixed-v5.json").read_text(encoding="utf-8"))
    for name,sha in {**fixed["files"],**fixed["recognition_components"]["files"]}.items():
        file=Path(name)
        if file.is_relative_to(base) and hashlib.sha256(file.read_bytes()).hexdigest()!=sha:raise ValueError("旧asset変更")
    shutil.copytree(base,output)
    def crop_asset(path,record,rect,name):
        target=(output/name).resolve()
        if target.exists() or target==path.resolve() or not target.is_relative_to(output):raise ValueError("asset出力衝突")
        x,y,w,h=rect
        if not write_image(target,read_image(path)[y:y+h,x:x+w]):raise OSError("asset保存失敗")
        return {"image":name,"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"original":str(path),
            "original_sha256":record["sha256"],"capture_sequence":record["capture_sequence"],
            "captured_at_monotonic":record["captured_at_monotonic"],"rect":rect,"use":"known method selection, not holdout"}
    scene_defs={"source_hand6-slot3":("before6",[320,540,650,180]),"source_hand7-slot3":("before7",[320,540,650,180]),
        "effect_hand6-slot3":("before6",[645,487,78,91]),"effect_hand7-slot3":("before7",[601,487,78,91]),
        "own_chain":("chain",[424,439,432,53]),"ready_hand6-slot3":("ready6",[320,595,650,125]),
        "ready_hand7-slot3":("ready7",[320,595,650,125]),"selected_hand6-slot3":("selected6",[320,540,650,180]),
        "selected_hand7-slot3":("selected7",[320,540,650,180]),"gy_panel":("gy",[1130,130,135,250])}
    scenes={}
    for name,(group,rect) in scene_defs.items():
        scenes[name]={"rect":rect,"references":[crop_asset(path,item,rect,f"hand-search-{name}-{i:03d}.png")
            for i,(path,item) in enumerate(groups[group])]}
    details=[crop_asset(*groups[key][0],[27,151,103,150],f"hand-search-detail13906-{key}.png") for key in ["before6","before7"]]
    prior=json.loads((ROOT/"evaluation/dragondark-public-face-calibration-v1.json").read_text(encoding="utf-8"))
    public=[crop_asset(*burst[i],prior["rows"][i]["full_face_bbox"],f"hand-search-public-{i}.png") for i in [23,24,25,26]]
    config={"schema":"dragondark-hand-search-v1","tracking":TRACK,"scenes":scenes,"detail_references":details,
        "detail_recognition_mode":DETAIL_ART_MODE,"detail_art_parameters":DETAIL_ART_PARAMETERS,
        "source_art_mode":SOURCE_ART_MODE,"source_art_parameters":SOURCE_ART_PARAMETERS,
        "public_anchor_mode":PUBLIC_ART_MODE,"public_art_parameters":PUBLIC_ART_PARAMETERS,
        "public_references":public,"layouts":{"hand6-slot3":{"effect_box":[645,487,78,91],"effect_point":[683,524]},
            "hand7-slot3":{"effect_box":[601,487,78,91],"effect_point":[640,522]}},
        "scope":"known source hand6/7 slot3. Destination from actual public-instance handoff, not source slot label.",
        "original_training_integrity":False,"unrelated_original_missing":1}
    (output/"hand-search.json").write_text(json.dumps(config,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    goal=LogicalHandSearchConfirmation(own_chain_mode="parent_activation_ui");spec=goal.model_dump(mode="json")
    rows=[]
    for i,(ident,kind,region,cid,target,prompt,observed,expected) in enumerate([
        ("dragondark_hand_activate","ACTIVATE",goal.activate_region,"13906",None,"hand.dragondark.effect_menu",
            {goal.source_ready_fact:"true",goal.detail_fact:"13906"},{goal.own_chain_fact:"true"}),
        ("dragondark_own_chain_decline","CANCEL",goal.cancel_region,None,None,"hand.dragondark.own_chain",
            {goal.own_chain_fact:"true"},{goal.result_ready_fact:"true"}),
        ("dragondark_hand_result_inspect","SELECT_CARD",goal.inspect_region,"13906","self.hand.received","hand.dragondark.result_ready",
            {goal.result_ready_fact:"true"},{goal.result_selected_fact:"true",goal.detail_fact:"13906"})]):
        rows.append({"id":ident,"description":"Solo公開UI雷電龍手札①→同名追加確認","type":kind,"source_region":region,
            "card_id":cid,"target":target,"priority":600,"players":["self"],"phases":["MAIN1"],"prompt":prompt,
            "observed_facts":observed,"expected_facts":expected,"expected_prompts":[],
            "follows":[rows[-1]["id"]] if rows else [],"logical_action":"dragondark_hand_search","logical_category":"ACTIVATE_EFFECT",
            "logical_start":i==0,"logical_end":i==2,"logical_hand_search_confirmation":spec})
    book=json.loads((output/"solo-route.json").read_text(encoding="utf-8"));book["rules"].extend(rows);StrategyBook.model_validate(book)
    (output/"solo-route.json").write_text(json.dumps(book,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    cal=json.loads((output/"calibration.json").read_text(encoding="utf-8"))
    for region,kind,cid,target,box,ref in [
        (goal.activate_region,"ACTIVATE","13906",None,[500,470,340,110],scenes["effect_hand7-slot3"]["references"][0]),
        (goal.cancel_region,"CANCEL",None,None,[456,661,178,40],scenes["own_chain"]["references"][0]),
        (goal.inspect_region,"SELECT_CARD","13906","self.hand.received",[320,580,650,140],scenes["ready_hand7-slot3"]["references"][0])]:
        x,y,w,h=box
        cal["regions"][region]={"kind":"action","rect":{"x":x/1280,"y":y/720,"width":w/1280,"height":h/720},
            "exemplars":[{"label":kind,"image":ref["image"]}],"threshold":.98,"margin":.03,"card_id":cid,"target":target}
    (output/"calibration.json").write_text(json.dumps(cal,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    ui=json.loads((output/"ui-rules.json").read_text(encoding="utf-8"))
    for row in rows:ui["rules"].append({key:row[key] for key in ["prompt","type","source_region","card_id","target"]})
    (output/"ui-rules.json").write_text(json.dumps(ui,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (output/"hand-search-trials.json").write_text('["dragondark_hand_search"]\n',encoding="utf-8")
    return config


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();build(args.output);print(args.output)
