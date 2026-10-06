"""実MSS訓練/既知対比の回帰。新holdout・入力・実機E2Eではありません。"""
import json
import hashlib
from pathlib import Path
import pytest

from master_duel_advisor.capture import Frame
from master_duel_advisor.cli import build_pipeline, close_pipeline
from master_duel_advisor.image_io import read_image

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/solo-basic-calibration-v2"
TRAIN=ROOT/"artifacts/baseline-tester/OPTIONAL_RESPONSE_TRAIN_v1_20261006"


@pytest.fixture(scope="module")
def pipeline():
    p=build_pipeline(BASE/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",BASE/"solo-route.json",BASE/"ui-rules.json")
    yield p
    close_pipeline(p)


def test_available81_training_and_class_contrasts_with_explicit_original_loss(pipeline):
    counts={};negative_count=0;missing=[]
    for folder in sorted(x for x in TRAIN.iterdir() if x.is_dir()):
        manifest=json.loads((folder/"manifest.json").read_text(encoding="utf-8"))
        for row in manifest["frames"]:
            path=folder/row["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:
                missing.append(path);continue
            state=pipeline.perception.process(Frame(read_image(folder/row["file"]),0,row["capture_sequence"],capture_source="saved_image"))
            actions=pipeline.planner.filter_actions(state,state.visible_actions)
            if folder.name=="summon-response-before":
                expected="response.opponent_summon_success"
            elif folder.name in {"end-response-before","summon-response-after"}:
                expected="response.opponent_turn_end"
            elif folder.name=="end-response-after":
                expected="none"
                assert state.phase.value=="DRAW" and state.turn_player.value=="self"
                assert state.animation.value is None  # 演出をidleへ偽装しない。
            else:
                expected=None;negative_count+=1
            assert state.prompt.value==expected
            assert len(actions)==(1 if expected and expected.startswith("response.") else 0)
            if actions:
                choice=pipeline.ui_policy.decide(state,tuple(actions))
                assert choice.action==actions[0] and choice.action.card_id is None
            counts[folder.name]=counts.get(folder.name,0)+1
    assert sum(counts.values())==81 and negative_count==32
    assert missing==[TRAIN/"end-response-before/frame-0009.png"]


@pytest.mark.parametrize("stage",["menu","placement","post-unselected","post-inspected"])
def test_old_normal_40_same_semantics_under_combined_calibration(pipeline,stage):
    before=ROOT/"artifacts/ash-normal-inspect-calibration-v5"
    p=build_pipeline(before/"calibration.json",ROOT/"data/decks/thunder-dragon-review/cards.sqlite3",before/"normal-route.json")
    try:
        for path in sorted((ROOT/"artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006"/stage).glob("frame-*.png")):
            frame=Frame(read_image(path),0,0,capture_source="saved_image")
            old=p.perception.process(frame);new=pipeline.perception.process(frame)
            assert (new.prompt.value,new.phase.value,new.turn_player.value)==(old.prompt.value,old.phase.value,old.turn_player.value)
            for key in ("detail.card_id","inspect_context.hand_selected","inspect_context.summon_enabled","zone.self.monster_2.occupancy"):
                assert new.facts[key].value==old.facts[key].value
    finally:close_pipeline(p)


def test_rgb_button_uses_full_descriptor_without_mask_bypass(pipeline):
    for name in ("action.cancel_opponent_turn_end","fact.response.cancel_enabled.opponent_turn_end"):
        matcher=pipeline.perception.matchers[name]
        assert matcher.region.feature=="rgb" and matcher.region.threshold==.98 and matcher.region.margin==.03
        assert not matcher.stable_profiles
        assert all(feature.shape==(32,64,3) for _,feature in matcher.templates)
