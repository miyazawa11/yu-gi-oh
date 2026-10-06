"""限定通常召喚の構造監査。画像認識や実機成功の評価とは別。"""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from master_duel_advisor.regions import Calibration
from master_duel_advisor.route_validation import audit_route
from master_duel_advisor.strategy_rules import StrategyBook


def normal_book():
    goal=dict(side='self',zone='monster_2',card_id='9455',selected_card_fact='selection.card_id',placement_region='action.place')
    common=dict(description='synthetic',priority=1,card_id='9455',phases=['MAIN1'],logical_action='normal_9455',logical_category='NORMAL_SUMMON',logical_zone_transition=goal)
    rules=[dict(**common,id='open',type='SELECT_CARD',source_region='action.hand',logical_start=True,expected_prompts=['card.menu'],observed_facts={'zone.self.monster_2.occupancy':'empty','normal_context.hand_layout':'true','normal_context.hand_card':'9455'}),
           dict(**common,id='summon',type='NORMAL_SUMMON',source_region='action.summon',prompt='card.menu',follows=['open'],expected_prompts=['placement.select'],observed_facts={'selection.card_id':'9455','normal_context.summon_enabled':'true'}),
           dict(**common,id='place',type='CONFIRM',source_region='action.place',target='self.monster_2',prompt='placement.select',follows=['summon'],logical_end=True,observed_facts={'normal_context.placement':'true'})]
    return dict(format='deck-strategy-v1',name='normal',source='synthetic',audit_profile='normal_summon',rules=rules)


def test_normal_structure_requires_real_goal_artifacts(tmp_path):
    book=StrategyBook.model_validate(normal_book())
    report=audit_route(book,Calibration(name='empty',regions={}),tmp_path)
    missing={item['region']:item for item in report['missing']}
    assert not report['structural_ready']
    assert 'turn' not in missing
    assert missing['self.zones.monster_2']['labels']==['9455']
    assert {'empty','occupied'}<=set(missing['fact.zone.self.monster_2.occupancy']['labels'])
    assert missing['fact.selection.card_id']['labels']==['9455']


@pytest.mark.parametrize('index,change',[
 (0,{'card_id':'other'}),(0,{'players':['opponent']}),(0,{'phases':['MAIN2']}),
 (0,{'logical_start':False}),(0,{'logical_end':True}),(0,{'logical_action':None}),
 (0,{'facts':{'used.normal_summon':'false'}}),(0,{'observed_facts':{}}),
 (1,{'type':'ACTIVATE'}),(1,{'follows':[]}),(1,{'additional_prompts':['chain.select']}),
 (1,{'observed_facts':{'selection.card_id':'other','normal_context.summon_enabled':'true'}}),
 (2,{'target':'self.monster_3'}),(2,{'source_region':'action.unrelated'}),
 (2,{'logical_end':False}),(2,{'enabled':False}),(2,{'expected_prompts':['none']}),
])
def test_normal_profile_rejects_unrelated_or_unproven_action(index,change):
    raw=normal_book();raw['rules'][index].update(change)
    with pytest.raises(ValidationError):StrategyBook.model_validate(raw)


@pytest.mark.parametrize('change',[{'inference_mode':'provisional'},{'min_confidence':.9}])
def test_normal_profile_cannot_relax_certainty(change):
    raw=normal_book();raw.update(change)
    with pytest.raises(ValidationError):StrategyBook.model_validate(raw)


def test_normal_profile_declared_card_is_not_hardcoded():
    raw=normal_book()
    for r in raw['rules']:
        r['card_id']='test-other';r['logical_zone_transition']=dict(r['logical_zone_transition'],card_id='test-other')
        r['observed_facts']={key:'test-other' if value=='9455' else value for key,value in r['observed_facts'].items()}
    assert StrategyBook.model_validate(raw).rules[0].card_id=='test-other'

@pytest.mark.parametrize('sent,changed,planner_ok,expected',[(True,True,True,'changed'),(False,True,True,'unchanged'),(None,True,True,'unchanged'),(True,False,True,'unchanged'),(True,True,False,'unexpected_state')])
def test_zone_goal_verification_accepts_partial_before_only_with_complete_goal(tmp_path,sent,changed,planner_ok,expected):
    import time
    import numpy as np
    from types import SimpleNamespace
    from test_agent_loop import setup
    from test_telemetry import zone_case
    from master_duel_advisor.capture import Frame
    loop,_,_=setup(tmp_path/'loop')
    telemetry,rule,final,zstate=zone_case(tmp_path/'telemetry',sent=sent)
    loop.telemetry=telemetry
    before_state=zstate(2,None)
    before_state=before_state.model_copy(update={'facts':{}})
    loop.current_action=loop.pipeline.action
    loop.pipeline.planner=SimpleNamespace(rule_for=lambda action:rule,expected=lambda action,state:planner_ok)
    pixels=np.zeros((100,200,3),np.uint8)
    before=Frame(pixels,2,2000)
    after=Frame(pixels+100 if changed else pixels,3,3000)
    loop.capture.source.frames=iter([after])
    loop.pipeline.perception.process=lambda frame:final
    # 直前の配置画像はunknownで、通常known→known差分はない。
    assert not loop.verification.expected(before.pixels,after.pixels,before_state,final,loop.current_action)
    _,_,status=loop._verify(before,before_state)
    assert status==expected
