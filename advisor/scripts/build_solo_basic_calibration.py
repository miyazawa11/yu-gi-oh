"""観測済み2応答と既存normal/phaseを新cohort校正へ合成。入力は行いません。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from master_duel_advisor.capture import Frame
from master_duel_advisor.image_io import read_image, write_image
from master_duel_advisor.regions import Calibration, CompositeEvidence, Exemplar, Rect, Region
from master_duel_advisor.strategy_rules import LogicalResponseDecline, StrategyBook, StrategyRule
from master_duel_advisor.ui_policy import UiPolicy, UiRule

ROOT=Path(__file__).resolve().parents[1]
TRAIN=ROOT/"artifacts/baseline-tester/OPTIONAL_RESPONSE_TRAIN_v1_20261006"


def pixel_rect(roi):
    x,y,w,h=roi;epsilon=.0001
    return Rect(x=(x+epsilon)/1280,y=(y+epsilon)/720,width=(w-2*epsilon)/1280,height=(h-2*epsilon)/720)


def load_batch(stage):
    folder=TRAIN/stage;manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
    if manifest.get("capture_source")!="mss" or not all(r["eligible"] for r in manifest["frames"]):
        raise ValueError("元MSSと適合captureが必要です")
    rows=[]
    for item in manifest["frames"]:
        path=folder/item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]:
            raise ValueError("元訓練画像hash不一致")
        pixels=read_image(path)
        if pixels.shape!=(720,1280,3):raise ValueError("native client1280x720が必要です")
        rows.append((stage,item,pixels))
    return rows


def build(output):
    output=Path(output).resolve()
    if output.exists():raise ValueError("既存校正は上書きできません")
    normal_base=ROOT/"artifacts/ash-normal-inspect-calibration-v5"
    shutil.copytree(normal_base,output)
    layout=Calibration.model_validate_json((output/"calibration.json").read_text(encoding="utf-8"))
    normal=StrategyBook.model_validate_json((output/"normal-route.json").read_text(encoding="utf-8"))
    phase_base=ROOT/"artifacts/phase-only-calibration"
    phase_layout=Calibration.model_validate_json((phase_base/"calibration.json").read_text(encoding="utf-8"))
    phase=StrategyBook.model_validate_json((phase_base/"phase-route.json").read_text(encoding="utf-8"))
    regions=dict(layout.regions);composites=list(layout.composites)
    for name,region in phase_layout.regions.items():
        refs=[]
        for ex in region.exemplars:
            file="phase_"+ex.image;shutil.copyfile(phase_base/ex.image,output/file)
            refs.append(ex.model_copy(update={"image":file}))
        if name in regions and regions[name].kind!="unobserved":
            raise ValueError("既存normal領域との衝突: "+name)
        regions[name]=region.model_copy(update={"exemplars":refs})
    composites.extend(phase_layout.composites)
    summon=load_batch("summon-response-before")
    end=load_batch("end-response-before")+load_batch("summon-response-after")
    draw=load_batch("end-response-after")
    sources=[]
    def add(name,roi,label,rows,kind="template",feature="stable_rgb"):
        x,y,w,h=roi;refs=[]
        for n,(stage,item,pixels) in enumerate(rows):
            file="response_"+name.replace(".","_")+f"_{n:03d}.png"
            if not write_image(output/file,pixels[y:y+h,x:x+w]):raise OSError(file)
            refs.append(Exemplar(label=label,image=file))
            sources.append({"source_stage":stage,"source":str(TRAIN/stage/item["file"]),
                "sha256":item["sha256"],"capture_sequence":item["capture_sequence"],
                "captured_at_monotonic":item["captured_at_monotonic"],"roi":roi,"asset":file})
        regions[name]=Region(rect=pixel_rect(roi),kind=kind,exemplars=refs,feature=feature,threshold=.98,margin=.03)

    phrase=(501,449,263,17);fulltext=(500,449,267,34);badge=(946,320,86,26);cancel=(456,661,178,40)
    for kind,rows in (("opponent_summon_success",summon),("opponent_turn_end",end)):
        add("fact.response.prompt."+kind,fulltext,"true",rows)
        add("fact.response.phrase."+kind,phrase,"true",rows)
        add("fact.response.badge."+kind,badge,"true",rows)
        # hover/非hoverは同義ボタン。色の異なる20枚をstable medianへ混ぜません。
        add("fact.response.cancel_enabled."+kind,cancel,"true",rows,feature="rgb")
        add("action.cancel_"+kind,cancel,"CANCEL",rows,"action",feature="rgb")
        when={"fact.response.prompt."+kind:"true","fact.response.phrase."+kind:"true",
              "fact.response.badge."+kind:"true","fact.response.cancel_enabled."+kind:"true"}
        composites.append(CompositeEvidence(id="response_"+kind,when=when,emit={
            "ui.prompt":"response."+kind,"phase":"MAIN1" if kind.endswith("success") else "END",
            "turn_player":"opponent","ui.animation":"idle","game.terminal":"active"}))
    add("fact.response.outcome.opponent_end_response",badge,"true",end)
    add("fact.response.modal_absent",(425,440,427,42),"true",draw)
    add("fact.response.outcome.self_draw",badge,"true",draw)
    composites.append(CompositeEvidence(id="response_self_draw",when={
        "fact.response.modal_absent":"true","fact.response.outcome.self_draw":"true"},emit={
        "ui.prompt":"none","phase":"DRAW","turn_player":"self","game.terminal":"active"}))
    # Draw演出のidle/playingは校正しません。未知のまま次入力を許可しません。
    goals=[LogicalResponseDecline(kind="opponent_summon_success",outcome="opponent_end_response",cancel_region="action.cancel_opponent_summon_success"),
           LogicalResponseDecline(kind="opponent_turn_end",outcome="self_draw",cancel_region="action.cancel_opponent_turn_end")]
    response_rules=[];policy=[]
    for goal in goals:
        response_rules.append(StrategyRule(id="decline_"+goal.kind,description="Solo試験policyで表示中の任意発動を辞退",
            type="CANCEL",source_region=goal.cancel_region,priority=1000,players=["opponent"],phases=[goal.before_phase],
            prompt=goal.semantic_prompt,observed_facts={goal.prompt_fact:"true",goal.cancel_fact:"true"},
            expected_prompts=[goal.completion_prompt],expected_facts={goal.completion_fact:"true",goal.outcome_fact:"true"},
            logical_action="decline_"+goal.kind,logical_category="CHAIN",logical_start=True,logical_end=True,logical_response_decline=goal))
        policy.append(UiRule(prompt=goal.semantic_prompt,type="CANCEL",source_region=goal.cancel_region))
    final=layout.model_copy(update={"name":"Solo-normal-phase-typed-response-MSS-v1","regions":regions,"composites":composites})
    Calibration.model_validate(final.model_dump(mode="json"))
    book=StrategyBook(format="deck-strategy-v1",name="Solo既知normal/phase/任意応答辞退",source="v5 normal＋既存phase＋元MSS訓練50枚",
        audit_profile="solo_basic_operations",rules=[*normal.rules,*phase.rules,*response_rules])
    ui=UiPolicy(rules=policy);ui.validate_responses(book)
    (output/"calibration.json").write_text(final.model_dump_json(indent=2)+"\n",encoding="utf-8")
    (output/"solo-route.json").write_text(book.model_dump_json(indent=2)+"\n",encoding="utf-8")
    (output/"ui-rules.json").write_text(ui.model_dump_json(indent=2)+"\n",encoding="utf-8")
    (output/"training-response-manifest.json").write_text(json.dumps({"schema":"typed-response-training-v1","sources":sources,
        "outcomes":[g.model_dump(mode="json") for g in goals],"threshold":.98,"margin":.03,
        "limitation":"補助収集・方式選択資料、E2E0。Draw解決/idle/候補CID/戦略最善を主張しない。clearMain1 after欠測。"},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return final,book


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    build(args.output);print(args.output)
