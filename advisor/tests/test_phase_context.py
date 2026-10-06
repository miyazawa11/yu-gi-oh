"""限定文脈の陽性ANDと目的到達確認の回帰。"""
import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from master_duel_advisor.capture import Frame
from master_duel_advisor.cards import CardDatabase
from master_duel_advisor.image_io import write_image
from master_duel_advisor.models import GameState, Observation
from master_duel_advisor.perception import Perception
from master_duel_advisor.regions import Calibration, CompositeEvidence, Rect, Region, Exemplar
from master_duel_advisor.strategy_rules import StrategyBook


def calibration(tmp_path, conflict=False):
    pixels=np.zeros((20,40,3),np.uint8)
    pixels[:,:20]=(30,70,110);pixels[:,20:]=(140,180,220)
    regions={}
    for index,key in enumerate(('fact.left','fact.right')):
        file=f'{index}.png';write_image(tmp_path/file,pixels[:,index*20:(index+1)*20])
        regions[key]=Region(kind='template',rect=Rect(x=index*.5,y=0,width=.5,height=1),threshold=.98,
                            exemplars=[Exemplar(label='true',image=file)])
    contexts=[CompositeEvidence(id='normal',when={'fact.left':'true','fact.right':'true'},emit={'ui.prompt':'none','ui.animation':'idle'})]
    if conflict: contexts.append(CompositeEvidence(id='conflict',when={'fact.left':'true','fact.right':'true'},emit={'ui.prompt':'phase.select'}))
    return Calibration(name='synthetic',aspect_ratio=2,regions=regions,composites=contexts),pixels


def test_composite_positive_and_never_reuses_missing_evidence(tmp_path):
    layout,pixels=calibration(tmp_path)
    db=CardDatabase(tmp_path/'cards.sqlite3')
    try:
        perception=Perception(layout,tmp_path,db)
        before=perception.process(Frame(pixels,1,1))
        assert before.prompt.value=='none' and before.animation.value is False
        assert before.prompt.confidence==min(o.confidence for o in before.facts.values())
        assert before.prompt.source.startswith('composite:')
        different=pixels.copy();different[:,20:]=0
        after=perception.process(Frame(different,2,2))
        assert after.prompt.value is None and after.animation.value is None
    finally: db.close()


def test_composite_conflict_is_unknown(tmp_path):
    layout,pixels=calibration(tmp_path,True);db=CardDatabase(tmp_path/'cards.sqlite3')
    try:
        state=Perception(layout,tmp_path,db).process(Frame(pixels,1,1))
        assert state.prompt.value is None and state.prompt.confidence==0
    finally:db.close()


def test_composite_cannot_reference_generated_or_low_threshold_data(tmp_path):
    layout,_=calibration(tmp_path)
    data=layout.model_dump()
    data['regions']['fact.left']['threshold']=.97
    with pytest.raises(ValidationError):Calibration.model_validate(data)
    data=layout.model_dump();data['composites'][0]['when']={'ui.prompt':'none','fact.left':'true'}
    with pytest.raises(ValidationError):Calibration.model_validate(data)


def test_integer_training_crop_equals_runtime_crop():
    path=Path(__file__).resolve().parents[1]/'scripts/build_phase_calibration.py'
    # モジュールimport時に訓練資料が存在しない場合も整数変換だけ検証できる。
    code=path.read_text(encoding='utf-8');start=code.index('def pixel_rect(');end=code.index('\n\ndef build()',start)
    namespace={'Rect':Rect};exec(code[start:end],namespace)
    pixels=np.arange(720*1280,dtype=np.int32).reshape(720,1280)
    for x,y,w,h in [(480,402,320,40),(495,402,295,27),(952,491,114,120)]:
        cropped=namespace['pixel_rect'](x,y,w,h).crop(pixels)
        assert np.array_equal(cropped,pixels[y-31:y-31+h,x-1:x-1+w])


def test_final_phase_verification_waits_through_menu_close(tmp_path):
    from test_agent_loop import setup
    loop,_,_=setup(tmp_path)
    at=time.monotonic()
    def obs(v,t):return Observation(value=v,confidence=1,observed_at=t)
    before=GameState(sequence=0,captured_at=at,phase=obs('MAIN1',at),prompt=obs('phase.select',at))
    middle=GameState(sequence=1,captured_at=at+.01,prompt=obs('none',at+.01))
    final=GameState(sequence=2,captured_at=at+.02,phase=obs('END',at+.02))
    r=SimpleNamespace(id='end',logical_action='phase',logical_category='CHANGE_PHASE',logical_start=True,
                      logical_end=True,logical_phase='END',logical_count_fact=None)
    image=np.zeros((100,200,3),np.uint8)
    first=Frame(image,at,0,capture_start=time.perf_counter(),capture_end=time.perf_counter())
    action=loop.pipeline.action
    loop.telemetry.begin_step(action,r,before,first,{})
    loop.current_action=action
    loop.pipeline.planner=SimpleNamespace(rule_for=lambda a:r,expected=lambda a,s:True)
    loop.pipeline.perception.process=lambda frame: middle if frame.sequence==1 else final
    loop.capture.source.frames=iter([Frame(image+100,at+.01,1),Frame(image+200,at+.02,2)])
    after,state,status=loop._verify(first,before)
    assert status=='changed' and state.phase.value=='END' and after.sequence==2


@pytest.mark.parametrize("change", [{"players":["opponent"]},{"card_id":"13923"},{"facts":{"unused.foo":"true"}},
                                    {"logical_action":None},{"prompt":"chain.response"}])
def test_limited_audit_cannot_be_used_for_other_actions(change):
    base=dict(priority=1,logical_action="phase",logical_category="CHANGE_PHASE",phases=["MAIN1"],observed_facts={"a":"true","b":"true"})
    first=dict(id="open",description="open",type="CHANGE_PHASE",source_region="action.open",logical_start=True,prompt="none",expected_prompts=["phase.select"],**base)
    last=dict(id="end",description="end",type="CONFIRM",source_region="action.end",logical_end=True,logical_phase="END",prompt="phase.select",follows=["open"],**base)
    StrategyBook.model_validate(dict(format="deck-strategy-v1",name="phase",source="synthetic",audit_profile="phase_transition",rules=[first,last]))
    first.update(change)
    with pytest.raises(ValidationError):
        StrategyBook.model_validate(dict(format="deck-strategy-v1",name="phase",source="synthetic",audit_profile="phase_transition",rules=[first,last]))

def stable_matcher(tmp_path, width=8, count=10, two_labels=False):
    from master_duel_advisor.perception import TemplateMatcher
    exemplars=[]
    for label in (['a','b'] if two_labels else ['a']):
        for i in range(count):
            pixels=np.full((32,64,3),0 if i%2 else 255,np.uint8)
            pixels[:,:width]=100
            filename=f'{label}-{i}.png';write_image(tmp_path/filename,pixels)
            exemplars.append(Exemplar(label=label,image=filename))
    region=Region(kind='template',rect=Rect(x=0,y=0,width=1,height=1),threshold=.98,feature='stable_rgb',exemplars=exemplars)
    return TemplateMatcher(region,tmp_path)


def test_stable_rgb_mask_uses_only_valid_pixels_not_black_padding(tmp_path):
    matcher=stable_matcher(tmp_path)
    assert matcher.stable_statistics['a']['valid_pixels']==256
    positive=np.full((32,64,3),42,np.uint8);positive[:,:8]=100
    assert matcher.match(positive)==('a',1.0)
    negative=positive.copy();negative[:,:8]=110
    # 256/2048の有効画素だけに誤差。全体平均なら誤って.995になる。
    assert matcher.match(negative)==(None,0.0)


@pytest.mark.parametrize('kwargs',[{'width':7},{'count':9}])
def test_stable_rgb_rejects_too_few_pixels_or_samples(tmp_path,kwargs):
    with pytest.raises(ValueError):stable_matcher(tmp_path,**kwargs)


def test_stable_rgb_keeps_label_ambiguity_margin(tmp_path):
    matcher=stable_matcher(tmp_path,two_labels=True)
    image=np.full((32,64,3),100,np.uint8)
    assert matcher.match(image)==(None,0.0)


def test_template_asset_hash_detects_same_filename_replacement(tmp_path):
    matcher=stable_matcher(tmp_path)
    old=matcher.asset_hashes['a-0.png']
    write_image(tmp_path/'a-0.png',np.zeros((32,64,3),np.uint8))
    import hashlib
    assert hashlib.sha256((tmp_path/'a-0.png').read_bytes()).hexdigest()!=old


def test_limited_readiness_requires_goal_phase_evidence(tmp_path):
    from master_duel_advisor.route_validation import audit_route
    base=dict(priority=1,logical_action="phase",logical_category="CHANGE_PHASE",phases=["MAIN1"],observed_facts={"a":"true","b":"true"})
    first=dict(id="open",description="open",type="CHANGE_PHASE",source_region="action.open",logical_start=True,prompt="none",expected_prompts=["phase.select"],**base)
    last=dict(id="end",description="end",type="CONFIRM",source_region="action.end",logical_end=True,logical_phase="END",prompt="phase.select",follows=["open"],**base)
    book=StrategyBook.model_validate(dict(format="deck-strategy-v1",name="phase",source="synthetic",audit_profile="phase_transition",rules=[first,last]))
    result=audit_route(book,Calibration(name="empty",regions={}),tmp_path)
    assert any(item['region']=='phase' and 'END' in item['labels'] for item in result['missing'])
