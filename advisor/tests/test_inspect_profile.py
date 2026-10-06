"""限定inspectの因果証拠・取得由来の境界。全て合成検証で実機KPIではありません。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from master_duel_advisor.capture import Frame
from master_duel_advisor.models import Action, GameState, Observation, UiCoordinateProof
from master_duel_advisor.regions import Calibration
from master_duel_advisor.strategy_rules import StrategyBook
from master_duel_advisor.telemetry import ActionTelemetry, MeasuredCapture

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'artifacts/ash-normal-inspect-calibration-v1'


def book():
    return StrategyBook.model_validate_json((BASE/'normal-route.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('index,change', [(0,{'type':'SPECIAL_SUMMON'}),(0,{'facts':{'used.normal_summon':'false'}}),
    (0,{'logical_start':False}),(0,{'observed_facts':{}}),(1,{'target':'self.monster_3'}),
    (1,{'prompt':'chain.select'}),(2,{'follows':[]}),(2,{'expected_facts':{}}),(2,{'logical_end':False})])
def test_inspect_structure_rejects_unrelated_action(index, change):
    raw=book().model_dump(mode='json'); raw['rules'][index].update(change)
    with pytest.raises(ValidationError): StrategyBook.model_validate(raw)


def inspect_case(tmp_path):
    b=book(); layout=Calibration.model_validate_json((BASE/'calibration.json').read_text(encoding='utf-8'))
    telemetry=ActionTelemetry(tmp_path,clock=lambda:9,mode='synthetic')
    components={'registry_sha256':'registry-fixture','detector':{'detector_sha256':'detector-fixture','profile_sha256':{'solar-menu-v2':'profile-fixture'}}}
    rect=(100,200,1380,920)
    telemetry.configure(calibration=layout.model_dump(mode='json'),capture={'rect':rect},recognition_components=components)
    telemetry.metadata['data_integrity']=True

    def state(at, prompt, occupancy, detail=None, blank=False):
        obs=lambda value,source='template:fixture':Observation(value=value,confidence=1 if value is not None else 0,observed_at=at,source=source)
        facts={'zone.self.monster_2.occupancy':obs(occupancy),'detail.card_id':obs(detail,'detail_registry:registry-fixture')}
        if prompt=='card.menu': facts.update({'inspect_context.hand_selected':obs('true'), 'inspect_context.summon_enabled':obs('true','readonly_detector:detector-fixture')})
        if prompt=='placement.select': facts.update({'inspect_context.placement':obs('true'),'inspect_context.placement_target':obs('true')})
        facts['inspect_context.detail_blank']=obs('true' if blank else None)
        return GameState(sequence=int(at*10),captured_at=at,phase=obs('MAIN1'),turn_player=obs('self'),prompt=obs(prompt),animation=obs(False),terminal=obs(False),facts=facts)

    states=[state(1,'card.menu','empty','12950'),state(2,'placement.select','empty','12950'),state(3,'none','occupied',blank=True)]
    proof=UiCoordinateProof(frame_seq=10,observed_at=1,client_rect=rect,evidence_bbox=(380,497,74,79),score=.99,position_margin=.1,detector_sha256='detector-fixture',profile_sha256='profile-fixture',profile_id='solar-menu-v2')
    points=[(517,736),(738,645),(740,645)]
    for index,(rule,s) in enumerate(zip(b.rules,states)):
        action=Action(type=rule.type,card_id=rule.card_id,target=rule.target,confidence=1,source_region=rule.source_region,observed_at=s.captured_at,coordinate_proof=proof if index==0 else None)
        telemetry.begin_step(action,rule,s,Frame(np.zeros((720,1280,3),np.uint8),s.captured_at,s.sequence,capture_start=s.captured_at-.1,capture_end=s.captured_at),{})
        telemetry.input_result(True,points[index])
        telemetry.current_step.update(input_epoch_verified=True,input_epoch=100+index,result='changed',after_sequence=s.sequence+1)
    final=state(4,'field.inspect','occupied','12950')
    return telemetry,b.rules[-1],final


def test_inspect_positive_requires_no_field_cid_copy(tmp_path):
    t,r,s=inspect_case(tmp_path)
    assert not s.self.zones
    assert t.goal_confirmed(r,s)
    t.complete_step('changed',r,s,at=4)
    assert t.records[0]['result']=='success' and t.records[0]['mode']=='synthetic'


@pytest.mark.parametrize('case', ['false_input','unknown_input','wrong_type','wrong_target','wrong_point','wrong_client',
    'wrong_sequence','wrong_proof_hash','low_score','low_margin','fraction_bbox','outside_bbox','epoch_unverified',
    'initial_wrong_cid','initial_hand_unknown','initial_enabled_unknown','initial_wrong_prompt','initial_occupied',
    'placement_wrong_prompt','placement_target_unknown','blank_unknown','blank_wrong_source','stale_detail_before',
    'final_wrong_cid','final_stale_cid','final_wrong_source','final_unknown_prompt','final_unknown_occupancy','same_final_sequence','changed_integrity','final_blank_still_true'])
def test_inspect_goal_rejects_each_missing_or_conflicting_proof(tmp_path,case):
    t,r,s=inspect_case(tmp_path); first,place,last=t.active['steps']; proof=first['action']['coordinate_proof']
    if case=='false_input':last['input_sent']=False
    elif case=='unknown_input':last['input_sent']=None
    elif case=='wrong_type':first['action']['type']='SPECIAL_SUMMON'
    elif case=='wrong_target':last['action']['target']='self.monster_3'
    elif case=='wrong_point':last['screen_point']=[100,200]
    elif case=='wrong_client':first['client_rect']=[101,200,1381,920]
    elif case=='wrong_sequence':proof['frame_seq']=11
    elif case=='wrong_proof_hash':proof['detector_sha256']='wrong'
    elif case=='low_score':proof['score']=.979
    elif case=='low_margin':proof['position_margin']=.029
    elif case=='fraction_bbox':proof['evidence_bbox'][0]=380.1
    elif case=='outside_bbox':proof['evidence_bbox'][0]=315
    elif case=='epoch_unverified':last['input_epoch_verified']=False
    elif case=='initial_wrong_cid':first['inspect_before']['facts']['detail.card_id']['value']='9455'
    elif case=='initial_hand_unknown':first['inspect_before']['facts']['inspect_context.hand_selected'].update(value=None,confidence=0)
    elif case=='initial_enabled_unknown':first['inspect_before']['facts']['inspect_context.summon_enabled'].update(value=None,confidence=0)
    elif case=='initial_wrong_prompt':first['inspect_before']['prompt']['value']='chain.select'
    elif case=='initial_occupied':first['inspect_before']['facts']['zone.self.monster_2.occupancy']['value']='occupied'
    elif case=='placement_wrong_prompt':place['inspect_before']['prompt']['value']='none'
    elif case=='placement_target_unknown':place['inspect_before']['facts']['inspect_context.placement_target'].update(value=None,confidence=0)
    elif case=='blank_unknown':last['inspect_before']['facts']['inspect_context.detail_blank'].update(value=None,confidence=0)
    elif case=='blank_wrong_source':last['inspect_before']['facts']['inspect_context.detail_blank']['source']='registry_unknown'
    elif case=='stale_detail_before':last['inspect_before']['facts']['detail.card_id'].update(value='12950',confidence=1)
    elif case=='changed_integrity':t.metadata['data_integrity']=False
    elif case=='same_final_sequence':s=s.model_copy(update={'sequence':30})
    elif case=='final_unknown_prompt':s=s.model_copy(update={'prompt':Observation(observed_at=4)})
    else:
        facts=dict(s.facts)
        if case=='final_wrong_cid':facts['detail.card_id']=facts['detail.card_id'].model_copy(update={'value':'9455'})
        elif case=='final_stale_cid':facts['detail.card_id']=facts['detail.card_id'].model_copy(update={'observed_at':3})
        elif case=='final_wrong_source':facts['detail.card_id']=facts['detail.card_id'].model_copy(update={'source':'card:fake'})
        elif case=='final_unknown_occupancy':facts['zone.self.monster_2.occupancy']=Observation(observed_at=4)
        elif case=='final_blank_still_true':facts['inspect_context.detail_blank']=Observation(value='true',confidence=1,observed_at=4,source='template:blank')
        s=s.model_copy(update={'facts':facts})
    assert not t.goal_confirmed(r,s)


@pytest.mark.parametrize('field,value',[('frame_seq',True),('frame_seq',1.5),('evidence_bbox',(380.5,497,74,79)),('client_rect',(100,200,1380.1,920))])
def test_coordinate_proof_requires_actual_integer_pixels(tmp_path,field,value):
    t,_,_=inspect_case(tmp_path); raw=deepcopy(t.active['steps'][0]['action']['coordinate_proof']);raw[field]=value
    with pytest.raises(ValidationError):UiCoordinateProof.model_validate(raw)


@pytest.mark.parametrize('source',['saved_image','saved_video','unclassified'])
def test_saved_capture_never_receives_dynamic_live_coordinates(tmp_path,source):
    from test_agent_loop import setup
    loop,_,_=setup(tmp_path/'loop');t,_,_=inspect_case(tmp_path/'telemetry')
    a=Action.model_validate(t.active['steps'][0]['action'])
    loop.calibration=Calibration.model_validate_json((BASE/'calibration.json').read_text(encoding='utf-8'))
    loop.inspection_goal=book().rules[0].logical_inspect_confirmation
    loop.inspection_live_bound=True;loop.screen_rect=(100,200,1380,920);loop.clock=lambda:1.1
    frame=Frame(np.zeros((720,1280,3),np.uint8),1,10,capture_source=source,capture_rect=loop.screen_rect,input_epoch=3)
    state=GameState.model_validate(t.active['steps'][0]['inspect_before'])
    with pytest.raises(ValueError,match='MSS'):loop._coordinates(a,frame.pixels.shape,frame=frame,state=state)


def test_capture_input_activity_change_does_not_yield_frame(tmp_path):
    t=ActionTelemetry(tmp_path,mode='synthetic');tokens=iter([1,2])
    source=SimpleNamespace(read=lambda:Frame(np.zeros((2,2,3),np.uint8),1,1))
    measured=MeasuredCapture(source,t,activity_probe=lambda:next(tokens))
    assert measured.read() is None and t.events[-1]['status']=='capture_input_activity_changed'


def test_fixed_calibration_structural_and_training_integration():
    from master_duel_advisor.cli import build_pipeline
    pipeline=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    report=json.loads((ROOT/'evaluation/ash-normal-inspect-training-v1.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['cases']==40 and report['e2e_count']==0
    assert pipeline.perception.inspect_goal==book().rules[0].logical_inspect_confirmation
    pipeline.perception.cards.close()


def test_offline_image_with_client_binding_stays_without_live_proof():
    from master_duel_advisor.cli import build_pipeline
    from master_duel_advisor.image_io import read_image
    pipeline=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    pipeline.perception.inspect_client_rect=(100,200,1380,920)
    image=read_image(ROOT/'artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006/menu/frame-0000.png')
    state=pipeline.perception.process(Frame(image,0,0,capture_source='saved_image'))
    normals=[a for a in state.visible_actions if a.type.value=='NORMAL_SUMMON']
    assert len(normals)==1 and normals[0].coordinate_proof is None
    state=pipeline.perception.process(Frame(image,999999,1,capture_source='saved_image'))
    assert not any(a.type.value=='NORMAL_SUMMON' for a in state.visible_actions)
    pipeline.perception.cards.close()


@pytest.mark.parametrize('change',['none','sequence','timestamp','client','stale','hash','profile_hash','bbox'])
def test_dynamic_coordinates_check_frame_source_freshness_and_fixed_assets(tmp_path,change):
    from test_agent_loop import setup
    loop,_,_=setup(tmp_path/'loop');t,_,_=inspect_case(tmp_path/'telemetry')
    a=Action.model_validate(t.active['steps'][0]['action'])
    loop.calibration=Calibration.model_validate_json((BASE/'calibration.json').read_text(encoding='utf-8'))
    loop.inspection_goal=book().rules[0].logical_inspect_confirmation
    loop.inspection_live_bound=True;loop.screen_rect=(100,200,1380,920);loop.clock=lambda:1.1
    loop.pipeline.perception.inspect_detector=SimpleNamespace(sha256='detector-fixture',profiles={'solar-menu-v2':(None,None,'profile-fixture')})
    frame=Frame(np.zeros((720,1280,3),np.uint8),1,10,capture_source='live_mss',capture_rect=loop.screen_rect,input_epoch=3)
    state=GameState.model_validate(t.active['steps'][0]['inspect_before'])
    if change=='sequence':state=state.model_copy(update={'sequence':11})
    elif change=='timestamp':state=state.model_copy(update={'captured_at':1.01})
    elif change=='client':loop.screen_rect=(101,200,1381,920)
    elif change=='stale':loop.clock=lambda:4
    elif change in ['hash','profile_hash','bbox']:
        proof=a.coordinate_proof.model_copy(update={ {'hash':'detector_sha256','profile_hash':'profile_sha256','bbox':'evidence_bbox'}[change]: (315,497,74,79) if change=='bbox' else 'wrong'})
        a=a.model_copy(update={'coordinate_proof':proof})
    if change=='none':assert loop._coordinates(a,frame.pixels.shape,frame=frame,state=state)==(517,736)
    else:
        with pytest.raises(ValueError):loop._coordinates(a,frame.pixels.shape,frame=frame,state=state)


def test_actual_pipeline_three_step_planner_on_saved_training_pixels():
    """実部品間の接続を検証するが、Frame/Inputは合成で実機成功には数えません。"""
    import time
    from master_duel_advisor.cli import build_pipeline
    from master_duel_advisor.image_io import read_image
    pipeline=build_pipeline(BASE/'calibration.json',ROOT/'data/decks/thunder-dragon-review/cards.sqlite3',BASE/'normal-route.json')
    pipeline.perception.inspect_client_rect=(100,200,1380,920)
    folder=ROOT/'artifacts/baseline-tester/ASH_NORMAL_INSPECT_TRAIN_v1_20261006'
    stages=['menu','placement','post-unselected','post-inspected']
    for index,stage in enumerate(stages):
        image=read_image(folder/stage/'frame-0000.png')
        frame=Frame(image,time.monotonic(),index,capture_source='live_mss',capture_rect=(100,200,1380,920),input_epoch=1)
        result=pipeline.process(frame)
        state=GameState.model_validate(result['state'])
        if index:
            assert pipeline.planner.expected(prior,state)
            pipeline.action_feedback('changed')
            # 認識した同一frameは再取得せず判断を更新します。
            result=pipeline.process(frame,observed_state=state)
        if index<3:
            prior=Action.model_validate(result['recommendation']['action'])
            assert prior.type.value==['NORMAL_SUMMON','CONFIRM','SELECT_CARD'][index]
            pipeline.action_issued(prior)
        else:assert state.facts['detail.card_id'].value=='12950' and not state.self.zones
    pipeline.perception.cards.close()
