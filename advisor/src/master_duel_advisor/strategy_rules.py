"""表示候補を、デッキ固有条件で絞って即時評価するローカル展開ルール。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .models import Action, ActionType, GameState, Model, Phase, Player, Recommendation
from .planning import CardRequirement, PlanBook, TurnPlanner
from .materials import valid_materials


class LogicalZoneTransition(Model):
    """実観測の空→指定カード占有と、対応配置入力を結び付ける目的。"""
    side: Literal["self"] = "self"
    zone: str = Field(pattern=r"^monster_[0-9]+$")
    card_id: str = Field(min_length=1)
    selected_card_fact: str = Field(min_length=1)
    placement_region: str = Field(pattern=r"^action\.")


class LogicalInspectConfirmation(Model):
    """通常召喚・指定配置・blankからの実field inspectを結ぶ別目的。"""
    side: Literal["self"] = "self"
    zone: str = Field(pattern=r"^monster_[0-9]+$")
    card_id: str = Field(min_length=1)
    summon_region: str = Field(pattern=r"^action\.")
    placement_region: str = Field(pattern=r"^action\.")
    inspect_region: str = Field(pattern=r"^action\.")
    clear_region: str | None = Field(default=None, pattern=r"^action\.")
    detail_card_fact: str = "detail.card_id"
    hand_selected_fact: str = "inspect_context.hand_selected"
    evidence_mode: Literal["blank_to_detail_with_verified_zone_input"] = "blank_to_detail_with_verified_zone_input"
    detail_blank_fact: str = "inspect_context.detail_blank"
    summon_enabled_fact: str = "inspect_context.summon_enabled"

    @model_validator(mode="after")
    def distinct_regions(self):
        names = [self.summon_region, self.placement_region, self.inspect_region]
        if self.clear_region:
            names.append(self.clear_region)
        if len(set(names)) != len(names):
            raise ValueError("召喚・配置・inspect・clearの操作領域は別々にしてください")
        return self


class LogicalResponseDecline(Model):
    """Soloで表示された任意発動を辞退する目的。候補CIDや隠れた効果は推定しません。"""
    kind: Literal["opponent_summon_success", "opponent_turn_end"]
    outcome: Literal["opponent_main1", "opponent_end_response", "self_turn_notice", "self_draw"]
    cancel_region: str = Field(pattern=r"^action\.")
    modal_absent_fact: str = "response.modal_absent"
    evidence_mode: Literal["modal_absent_and_outcome", "observed_self_draw"] = Field(
        default="modal_absent_and_outcome", exclude_if=lambda value: value == "modal_absent_and_outcome")

    @model_validator(mode="after")
    def compatible_outcome(self):
        if (self.kind == "opponent_summon_success") != (self.outcome in {"opponent_main1", "opponent_end_response"}):
            raise ValueError("召喚応答と終了応答の結果を混同できません")
        if self.evidence_mode == "observed_self_draw" and (self.kind,self.outcome) != ("opponent_turn_end","self_draw"):
            raise ValueError("直接Draw観測は相手End辞退→自Drawだけです")
        return self

    @property
    def semantic_prompt(self):
        return "response." + self.kind

    @property
    def before_phase(self):
        return Phase.MAIN1 if self.kind == "opponent_summon_success" else Phase.END

    @property
    def prompt_fact(self):
        return "response.prompt." + self.kind

    @property
    def cancel_fact(self):
        return "response.cancel_enabled." + self.kind

    @property
    def outcome_fact(self):
        return "response.outcome." + self.outcome

    @property
    def completion_prompt(self):
        return "response.opponent_turn_end" if self.outcome == "opponent_end_response" else "none"

    @property
    def completion_fact(self):
        if self.evidence_mode == "observed_self_draw":return self.outcome_fact
        return "response.prompt.opponent_turn_end" if self.outcome == "opponent_end_response" else self.modal_absent_fact

    @property
    def completion_prompts(self):
        return [] if self.evidence_mode == "observed_self_draw" else [self.completion_prompt]


def response_ui_contradiction(state):
    """残っている応答UIの陽性は矛盾。unknownを消失証拠へ変換しません。"""
    names=["response.prompt.opponent_summon_success","response.prompt.opponent_turn_end",
        "response.cancel_enabled.opponent_summon_success","response.cancel_enabled.opponent_turn_end"]
    return (any((ob:=state.facts.get(name)) is not None and ob.value == "true" and ob.confidence >= .98
                and ob.observed_at == state.captured_at for name in names)
        or (state.prompt.value not in (None,"none") and state.prompt.confidence >= .98
            and state.prompt.observed_at == state.captured_at))


class LogicalHandSearchConfirmation(Model):
    """雷電龍手札①の公開incoming→hand格納を実入力episodeで確認します。"""
    card_id: Literal["13906"] = "13906"
    activate_region: str = "action.dragondark_hand_activate"
    cancel_region: str = "action.dragondark_own_chain_cancel"
    inspect_region: str = "action.dragondark_result_hand_inspect"
    evidence_mode: Literal["observed_ui_public_face_handoff"] = "observed_ui_public_face_handoff"
    own_chain_mode: Literal["current_main1","parent_activation_ui"] = "current_main1"
    detail_fact: str = "hand_search.detail_card_id"
    source_ready_fact: str = "hand_search.source_ready"
    own_chain_fact: str = "hand_search.own_chain"
    result_ready_fact: str = "hand_search.result_ready"
    result_selected_fact: str = "hand_search.result_selected"


class StrategyRule(Model):
    id: str
    card_id: str | None = None
    description: str
    type: ActionType
    source_region: str = Field(pattern=r"^action\.")
    target: str | None = None
    priority: int
    players: list[Player] = Field(default_factory=lambda: [Player.SELF])
    phases: list[Phase] = Field(default_factory=lambda: [Phase.MAIN1, Phase.MAIN2])
    prompt: str = "none"
    additional_prompts: list[str] = Field(default_factory=list)
    # UIの中間操作は、確認済みの直前操作と画面証拠を必要とする。
    follows: list[str] = Field(default_factory=list)
    observed_facts: dict[str, str] = Field(default_factory=dict)
    expected_prompts: list[str] = Field(default_factory=list)
    requires: list[CardRequirement] = Field(default_factory=list)
    facts: dict[str, str] = Field(default_factory=dict)
    expected_facts: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True
    material_method: str | None = None
    # 計測用。操作の許可条件を変更しません。
    logical_action: str | None = None
    logical_category: str | None = None
    logical_start: bool = False
    logical_end: bool = False
    logical_count_fact: str | None = None
    logical_phase: Phase | None = None
    logical_turn_advance: bool = False
    logical_zone_transition: LogicalZoneTransition | None = None
    logical_inspect_confirmation: LogicalInspectConfirmation | None = Field(default=None, exclude_if=lambda value: value is None)
    logical_response_decline: LogicalResponseDecline | None = Field(default=None, exclude_if=lambda value: value is None)
    logical_hand_search_confirmation: LogicalHandSearchConfirmation | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def validate_logical_zone_goal(self):
        if self.logical_zone_transition is not None and (
                not self.logical_action or self.logical_count_fact is not None
                or self.logical_phase is not None or self.logical_turn_advance):
            raise ValueError("ゾーン遷移目的には目的IDが必要で、他の完了条件とは混在できません")
        if self.logical_inspect_confirmation is not None and (
                not self.logical_action or self.logical_count_fact is not None or self.logical_phase is not None
                or self.logical_turn_advance or self.logical_zone_transition is not None):
            raise ValueError("inspect目的には目的IDが必要で、旧ゾーン目的等とは混在できません")
        if self.logical_response_decline is not None and (
                not self.logical_action or self.logical_count_fact is not None or self.logical_phase is not None
                or self.logical_turn_advance or self.logical_zone_transition is not None
                or self.logical_inspect_confirmation is not None):
            raise ValueError("応答辞退は独立した意味別目的です。異なるgoalとは混在できません")
        if self.logical_hand_search_confirmation is not None and (
                not self.logical_action or self.logical_count_fact is not None or self.logical_phase is not None
                or self.logical_turn_advance or self.logical_zone_transition is not None
                or self.logical_inspect_confirmation is not None or self.logical_response_decline is not None):
            raise ValueError("手札searchは独立した公開incoming目的です。他型と混在できません")
        return self

    def matches(self, action: Action) -> bool:
        return (action.type == self.type and action.source_region == self.source_region
                and action.card_id == self.card_id and action.target == self.target)

    def missing(self, state: GameState, threshold: float, *, action: Action | None = None) -> list[str]:
        def known(obs, values):
            return (obs.value in values and obs.confidence >= threshold
                    and obs.observed_at == state.captured_at)
        result = []
        goal=self.logical_hand_search_confirmation
        permission=state.facts.get("hand_search.own_chain_permission")
        own=state.facts.get(goal.own_chain_fact) if goal else None
        own_reply=(goal is not None and goal.own_chain_mode=="parent_activation_ui"
            and self.type==ActionType.CANCEL and self.source_region==goal.cancel_region
            and self.prompt=="hand.dragondark.own_chain" and action is not None and self.matches(action)
            and permission is not None and known(permission,["true"]) and permission.source.startswith("hand_search:")
            and own is not None and known(own,["true"]) and own.source==permission.source
            and state.animation.value is not True
            and all(o.source!="conflicting_positive_evidence" for o in [state.animation,state.phase,state.turn_player]))
        if not self.enabled:
            result.append("disabled")
        for name, obs, values in (("turn_player", state.turn_player, self.players),
                                  ("phase", state.phase, self.phases),
                                  ("prompt", state.prompt, [self.prompt, *self.additional_prompts])):
            if not known(obs, values) and not (own_reply and name in {"turn_player","phase"} and obs.value is None):
                result.append(name)
        goal=self.logical_hand_search_confirmation
        hand_inspect=False
        if (goal is not None and self.type==ActionType.SELECT_CARD and self.source_region==goal.inspect_region
                and self.prompt=="hand.dragondark.result_ready" and action is not None and self.matches(action)
                and state.animation.value is None and state.animation.source!="conflicting_positive_evidence"):
            proof=action.hand_search_proof;ready=state.facts.get(goal.result_ready_fact)
            blank=state.facts.get("inspect_context.detail_blank")
            if proof is not None:
                x,y,w,h=proof.evidence_bbox;px,py=proof.point
                hand_inspect=(proof.action_type=="SELECT_CARD" and proof.frame_seq==state.sequence
                    and proof.observed_at==state.captured_at and action.observed_at==state.captured_at
                    and ready is not None and known(ready,["true"]) and ready.source=="hand_search:"+proof.profile_sha256
                    and blank is not None and known(blank,["true"]) and blank.source.startswith("template:")
                    and 0<=x<px<x+w<=1280 and 0<=y<py<y+h<=720)
        if (not known(state.animation, [False]) and not hand_inspect and not (own_reply and state.animation.value is None)) or not known(state.terminal, [False]):
            result.append("active_idle")
        for requirement in self.requires:
            if not requirement.matches(state, threshold):
                result.append(f"{requirement.side}.{requirement.zone_prefix}{requirement.card_id}")
        for key, value in self.facts.items():
            if key not in state.facts or not known(state.facts[key], [value]):
                result.append(key)
        for key, value in self.observed_facts.items():
            if key not in state.facts or not known(state.facts[key], [value]):
                result.append("observed:" + key)
        if self.material_method:
            method = self.material_method
            if method == "fusion":
                target = state.facts.get("fusion.target")
                if target is None or not known(target, ["13923", "13924"]):
                    result.append("fusion.target")
                else:
                    method = "fusion_colossus" if target.value == "13923" else "fusion_titan"
            evidence = state.material_sets.get(self.material_method)
            if (evidence is None or evidence.value is None or evidence.confidence < threshold
                    or evidence.observed_at != state.captured_at
                    or not valid_materials(method, evidence.value)):
                result.append("material_set." + self.material_method)
        return result


class StrategyBook(Model):
    format: Literal["deck-strategy-v1"]
    name: str
    source: str
    rules: list[StrategyRule] = Field(min_length=1)
    min_confidence: float = Field(default=.98, gt=0, le=1)
    inference_mode: Literal["strict", "provisional"] = "strict"
    audit_profile: Literal["full_deck", "phase_transition", "normal_summon", "normal_inspect_confirmation",
                           "response_decline", "hand_search_confirmation", "solo_basic_operations"] = "full_deck"

    @model_validator(mode="after")
    def unique_rules(self):
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("展開ルールIDが重複しています")
        keys = [(r.type, r.source_region, r.card_id, r.target) for r in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("同じ操作に複数のルールが割り当てられています")
        ids = {r.id for r in self.rules}
        if any(set(r.follows) - ids for r in self.rules):
            raise ValueError("操作の前提に未登録のルールIDがあります")
        if self.audit_profile == "solo_basic_operations":
            self.validate_combined_profile()
            return self
        if self.audit_profile == "response_decline":
            self.validate_response_profile()
        elif any(r.logical_response_decline is not None for r in self.rules):
            raise ValueError("応答辞退は専用監査profileだけで使用してください")
        if self.audit_profile == "hand_search_confirmation":
            self.validate_hand_search_profile()
        elif any(r.logical_hand_search_confirmation is not None for r in self.rules):
            raise ValueError("手札searchは専用監査profileだけで使用してください")
        if self.audit_profile == "phase_transition":
            if len(self.rules) != 2:
                raise ValueError("限定phase監査は2操作のみです")
            first, last = self.rules
            if not (first.type == ActionType.CHANGE_PHASE and last.type == ActionType.CONFIRM
                    and first.logical_start and not first.logical_end and last.logical_end and not last.logical_start
                    and not first.follows and first.prompt == "none" and last.prompt == "phase.select"
                    and first.expected_prompts == ["phase.select"]
                    and last.logical_phase == Phase.END and last.follows == [first.id]
                    and first.logical_action and first.logical_action == last.logical_action
                    and all(r.logical_category == "CHANGE_PHASE" and not r.material_method
                            and r.players == [Player.SELF] and r.card_id is None and not r.facts
                            and not r.requires and r.phases == [Phase.MAIN1] and r.logical_zone_transition is None
                            and len(r.observed_facts) >= 2 for r in self.rules)):
                raise ValueError("限定phase監査の対象外操作です")
        if self.audit_profile == "normal_summon":
            self.validate_normal_profile()
        if self.audit_profile == "normal_inspect_confirmation":
            self.validate_inspect_profile()
        elif any(r.logical_inspect_confirmation is not None for r in self.rules):
            raise ValueError("inspect目的は専用監査profileだけで使用してください")
        return self

    @staticmethod
    def ordered_group(rules):
        """宣言順序に依存せず、同じ目的内の単一follow鎖を構築します。"""
        ordered = [r for r in rules if not r.follows]
        if len(ordered) != 1:
            raise ValueError("目的内の開始操作は1つ必要です")
        while len(ordered) < len(rules):
            successors = [r for r in rules if r not in ordered and r.follows == [ordered[-1].id]]
            if len(successors) != 1:
                raise ValueError("目的を跨ぐfollow・分岐・循環は使用できません")
            ordered.append(successors[0])
        return ordered

    def validate_response_profile(self):
        if self.inference_mode != "strict" or self.min_confidence < .98:
            raise ValueError("任意応答の辞退はstrictのみです")
        kinds = []
        for r in self.rules:
            g = r.logical_response_decline
            if g is None or not (r.type == ActionType.CANCEL and r.source_region == g.cancel_region
                    and r.card_id is None and r.target is None and r.players == [Player.OPPONENT]
                    and r.phases == [g.before_phase] and r.prompt == g.semantic_prompt
                    and r.logical_start and r.logical_end and r.logical_category == "CHAIN"
                    and not r.follows and not r.additional_prompts and not r.facts and not r.requires
                    and not r.material_method and r.enabled and r.expected_prompts == g.completion_prompts
                    and r.observed_facts.get(g.prompt_fact) == "true"
                    and r.observed_facts.get(g.cancel_fact) == "true"
                    and r.expected_facts.get(g.completion_fact) == "true"
                    and r.expected_facts.get(g.outcome_fact) == "true"):
                raise ValueError("意味別の一意Cancel・陽性結果の辞退条件が不足しています")
            if g.evidence_mode == "observed_self_draw" and r.expected_facts != {g.outcome_fact:"true"}:
                raise ValueError("直接Draw観測の完了は陽性Drawだけ。床色や未知promptを条件へ混ぜません")
            kinds.append(g.kind)
        if len(kinds) != len(set(kinds)) or not 1 <= len(kinds) <= 2:
            raise ValueError("任意辞退は観測済みの2promptだけです")

    def validate_combined_profile(self):
        if self.inference_mode != "strict" or self.min_confidence < .98:
            raise ValueError("共通Solo bookはstrictのみです")
        groups = {}
        for rule in self.rules:
            if not rule.logical_action:
                raise ValueError("共通bookの全操作に目的IDが必要です")
            groups.setdefault(rule.logical_action, []).append(rule)
        profiles = []
        response_kinds = []
        inspect_count = 0
        for rules in groups.values():
            if any(r.logical_hand_search_confirmation for r in rules):
                profile = "hand_search_confirmation"
            elif any(r.logical_response_decline for r in rules):
                profile = "response_decline"
                response_kinds.extend(r.logical_response_decline.kind for r in rules if r.logical_response_decline)
            elif any(r.logical_inspect_confirmation for r in rules):
                profile = "normal_inspect_confirmation"; inspect_count += 1
            elif all(r.logical_category == "CHANGE_PHASE" for r in rules):
                profile = "phase_transition"
            else:
                raise ValueError("未登録の目的型を共通bookへ混ぜられません")
            raw = self.model_dump(mode="json")
            raw.update(audit_profile=profile,rules=[r.model_dump(mode="json") for r in self.ordered_group(rules)])
            StrategyBook.model_validate(raw)
            profiles.append(profile)
        base_profiles = {"normal_inspect_confirmation", "phase_transition", "response_decline"}
        if (set(profiles) not in [base_profiles,base_profiles|{"hand_search_confirmation"}]
                or inspect_count != 1 or profiles.count("phase_transition") != 1
                or profiles.count("hand_search_confirmation") > 1
                or len(response_kinds) != 2 or len(response_kinds) != len(set(response_kinds))):
            raise ValueError("共通bookは通常召喚1目的・phase1目的・異なる意味別辞退です")

    def validate_hand_search_profile(self):
        if self.inference_mode != "strict" or self.min_confidence < .98 or len(self.rules) != 3:
            raise ValueError("限定手札searchはstrictの発動/専用chain辞退/実inspect3操作です")
        first,cancel,inspect = self.ordered_group(self.rules)
        goal = first.logical_hand_search_confirmation
        if goal is None or any(r.logical_hand_search_confirmation != goal for r in self.rules):
            raise ValueError("全childに同一hand-search目的宣言が必要です")
        required=[(first,ActionType.ACTIVATE,goal.activate_region,"13906",None),
            (cancel,ActionType.CANCEL,goal.cancel_region,None,None),
            (inspect,ActionType.SELECT_CARD,goal.inspect_region,"13906","self.hand.received")]
        if any(not (r.type==kind and r.source_region==region and r.card_id==cid and r.target==target
                and r.players==[Player.SELF] and r.phases==[Phase.MAIN1] and not r.additional_prompts
                and not r.requires and not r.facts and not r.material_method and r.enabled
                and r.logical_category=="ACTIVATE_EFFECT" and r.logical_action==first.logical_action)
                for r,kind,region,cid,target in required):
            raise ValueError("公開UI限定手札searchの種類/親/対象/未知facts分離が不整合です")
        if not (first.logical_start and not first.logical_end and not cancel.logical_start and not cancel.logical_end
                and not inspect.logical_start and inspect.logical_end and not first.follows
                and cancel.follows==[first.id] and inspect.follows==[cancel.id]
                and first.observed_facts.get(goal.source_ready_fact)=="true"
                and first.observed_facts.get(goal.detail_fact)=="13906"
                and first.expected_facts.get(goal.own_chain_fact)=="true"
                and cancel.observed_facts.get(goal.own_chain_fact)=="true"
                and cancel.expected_facts.get(goal.result_ready_fact)=="true"
                and inspect.observed_facts.get(goal.result_ready_fact)=="true"
                and inspect.expected_facts.get(goal.result_selected_fact)=="true"
                and inspect.expected_facts.get(goal.detail_fact)=="13906"):
            raise ValueError("手札searchの公開根拠/順序/結果条件が不足しています")

    def validate_normal_profile(self):
        if len(self.rules) != 3:
            raise ValueError("限定通常召喚監査は手札選択・召喚・配置の3操作のみです")
        first, summon, place = self.rules
        goal = first.logical_zone_transition
        if goal is None:
            raise ValueError("限定通常召喚には指定ゾーンの完了条件が必要です")
        occupancy = f"zone.{goal.side}.{goal.zone}.occupancy"
        common = (self.inference_mode == "strict" and self.min_confidence >= .98
                  and first.logical_action and all(
                      r.logical_action == first.logical_action and r.logical_category == "NORMAL_SUMMON"
                      and r.logical_zone_transition == goal and r.card_id == goal.card_id
                      and r.players == [Player.SELF] and r.phases == [Phase.MAIN1]
                      and r.enabled and not r.additional_prompts and not r.facts and not r.requires
                      and not r.material_method for r in self.rules))
        sequence = (first.type == ActionType.SELECT_CARD and summon.type == ActionType.NORMAL_SUMMON
                    and place.type == ActionType.CONFIRM and first.target is None and summon.target is None
                    and place.target == f"{goal.side}.{goal.zone}" and place.source_region == goal.placement_region
                    and first.logical_start and not summon.logical_start and not place.logical_start
                    and not first.logical_end and not summon.logical_end and place.logical_end
                    and not first.follows and summon.follows == [first.id] and place.follows == [summon.id]
                    and first.prompt == "none" and summon.prompt == "card.menu" and place.prompt == "placement.select"
                    and first.expected_prompts == ["card.menu"] and summon.expected_prompts == ["placement.select"]
                    and not place.expected_prompts)
        evidence = (first.observed_facts.get(occupancy) == "empty"
                    and first.observed_facts.get("normal_context.hand_layout") == "true"
                    and first.observed_facts.get("normal_context.hand_card") == goal.card_id
                    and summon.observed_facts.get(goal.selected_card_fact) == goal.card_id
                    and summon.observed_facts.get("normal_context.summon_enabled") == "true"
                    and place.observed_facts.get("normal_context.placement") == "true")
        if not (common and sequence and evidence):
            raise ValueError("限定通常召喚監査の対象外操作または陽性証拠不足です")

    def validate_inspect_profile(self):
        first = self.rules[0]
        goal = first.logical_inspect_confirmation
        if goal is None or len(self.rules) != (4 if goal.clear_region else 3):
            raise ValueError("inspect目的は召喚・配置・必要時clear・実zone選択だけです")
        place, inspect = self.rules[1], self.rules[-1]
        occupancy = f"zone.{goal.side}.{goal.zone}.occupancy"
        common = (self.inference_mode == "strict" and self.min_confidence >= .98 and all(
            r.logical_inspect_confirmation == goal and r.logical_zone_transition is None
            and r.logical_action == first.logical_action and r.logical_category == "NORMAL_SUMMON"
            and r.card_id == goal.card_id and r.players == [Player.SELF] and r.phases == [Phase.MAIN1]
            and r.enabled and not r.additional_prompts and not r.facts and not r.requires
            and not r.material_method and r.logical_start == (i == 0) and r.logical_end == (i == len(self.rules)-1)
            and r.follows == ([] if i == 0 else [self.rules[i-1].id])
            for i, r in enumerate(self.rules)))
        sequence = (first.type == ActionType.NORMAL_SUMMON and first.source_region == goal.summon_region
                    and first.target is None and first.prompt == "card.menu"
                    and first.expected_prompts == ["placement.select"]
                    and place.type == ActionType.CONFIRM and place.source_region == goal.placement_region
                    and place.target == f"{goal.side}.{goal.zone}" and place.prompt == "placement.select"
                    and place.expected_prompts == ["none"]
                    and inspect.type == ActionType.SELECT_CARD and inspect.source_region == goal.inspect_region
                    and inspect.target == f"{goal.side}.{goal.zone}" and inspect.prompt == "none"
                    and not inspect.expected_prompts)
        evidence = (first.observed_facts.get(occupancy) == "empty"
                    and first.observed_facts.get(goal.detail_card_fact) == goal.card_id
                    and first.observed_facts.get(goal.hand_selected_fact) == "true"
                    and first.observed_facts.get(goal.summon_enabled_fact) == "true"
                    and place.observed_facts.get("inspect_context.placement") == "true"
                    and place.observed_facts.get("inspect_context.placement_target") == "true"
                    and inspect.observed_facts.get(occupancy) == "occupied"
                    and inspect.observed_facts.get(goal.detail_blank_fact) == "true"
                    and inspect.expected_facts.get(goal.detail_card_fact) == goal.card_id
                    and inspect.expected_facts.get(occupancy) == "occupied")
        if goal.clear_region:
            clear = self.rules[2]
            evidence = evidence and (clear.type == ActionType.CANCEL and clear.source_region == goal.clear_region
                and clear.prompt == "none" and clear.target is None and clear.expected_prompts == ["none"]
                and clear.observed_facts.get(occupancy) == "occupied"
                and clear.expected_facts.get(goal.detail_blank_fact) == "true")
        if not (common and sequence and evidence):
            raise ValueError("inspect目的の操作順序または明示UI/zone/blank証拠が不足しています")


class RulePlanner:
    """厳密/暫定モードで条件を評価。暫定の推測は実観測とは分離する。"""
    strict = True
    recipe = None  # 従来プランナーの表示インターフェース

    def __init__(self, book: StrategyBook):
        self.book = book
        self.pending: Action | None = None
        self.last_completed: str | None = None
        self._verified_action: Action | None = None
        self.blocked: dict[str, list[str]] = {}
        self.assumptions: dict[str, list[str]] = {}
        self.inferred_used: set[str] = set()
        self.inferred_normal_used = False
        self.inferred_summon_lock = False
        self.turn_key = None
        self.reason = "盤面ごとに条件を再評価します"
        self._by_region = {r.source_region: [] for r in book.rules}
        for rule in book.rules:
            self._by_region[rule.source_region].append(rule)

    def rule_for(self, action):
        return next((r for r in self._by_region.get(action.source_region, []) if r.matches(action)), None)

    def observe(self, state):
        if state.terminal.value is True:
            self.pending = None
            self.reset()
            self._reset_inferences()
            self.turn_key = None
        elif all(o.value is not None and o.confidence >= self.book.min_confidence
                 and o.observed_at == state.captured_at for o in [state.turn, state.turn_player]):
            key = (state.turn.value, state.turn_player.value)
            if self.turn_key is not None and key != self.turn_key:
                self._reset_inferences()
                self.reset()
            self.turn_key = key

    def reset(self):
        """入力中断時にはUI手順を破棄。ターン内の使用履歴は消さない。"""
        self.pending = None
        self.last_completed = None
        self._verified_action = None

    def _reset_inferences(self):
        self.inferred_used.clear()
        self.inferred_normal_used = self.inferred_summon_lock = False

    def _infer_missing(self, rule, state, missing):
        """表示中の登録操作を根拠に未確認の展開条件だけを仮定する。観測値は書き換えない。"""
        def fresh(obs):
            return (obs is not None and obs.value is not None
                    and obs.confidence >= self.book.min_confidence and obs.observed_at == state.captured_at)
        blocked, assumed = [], []
        requirements = {f"{r.side}.{r.zone_prefix}{r.card_id}" for r in rule.requires}
        for key in missing:
            if key in rule.facts or key == "fusion.target":
                # 確認済みの不成立は楽観仮定で上書きしない。
                infer = not fresh(state.facts.get(key))
            elif key.startswith("material_set."):
                evidence = state.material_sets.get(rule.material_method)
                infer = not fresh(evidence)
                if fresh(evidence) and rule.material_method == "fusion" and not fresh(state.facts.get("fusion.target")):
                    infer = any(valid_materials(method, evidence.value) for method in ["fusion_colossus", "fusion_titan"])
            else:
                infer = key in requirements
            (assumed if infer else blocked).append(key)
        # 自分が送った操作は未使用と再推測しない。成功未確認でも重複実行を抑える。
        for key in rule.facts:
            if key in self.inferred_used:
                blocked.append("inferred_used:" + key)
        if "normal_summon.available" in rule.facts and self.inferred_normal_used:
            blocked.append("inferred_normal_summon_used")
        if "summon.allowed" in rule.facts and rule.type != ActionType.NORMAL_SUMMON and self.inferred_summon_lock:
            blocked.append("inferred_special_summon_lock")
        return blocked, assumed

    def filter_actions(self, state, actions):
        self.blocked = {}
        self.assumptions = {}
        result = []
        for action in actions:
            rule = self.rule_for(action)
            missing = rule.missing(state, self.book.min_confidence,action=action) if rule else ["unregistered_action"]
            if rule and self.book.inference_mode == "provisional":
                missing, assumed = self._infer_missing(rule, state, missing)
                if assumed:
                    self.assumptions[action.source_region] = assumed
            if rule and rule.follows and self.last_completed not in rule.follows:
                missing = missing + ["unconfirmed_predecessor"]
            if self.pending:
                missing = missing + ["pending_verification"]
            if action.confidence < self.book.min_confidence or action.observed_at != state.captured_at:
                missing = missing + ["stale_or_uncertain_action"]
            # 同一ボタンの認識が複数なら位置を勝手に選びません。
            if sum(a.source_region == action.source_region for a in actions) != 1:
                missing = missing + ["ambiguous_action"]
            if missing:
                self.blocked[action.source_region] = missing
            else:
                result.append(action)
        return result

    def decide(self, state, actions):
        allowed = self.filter_actions(state, actions) if actions else []
        if not allowed:
            return Recommendation(reason="展開条件または操作結果の確認を待っています", recognition_status="rule_blocked")
        action = min(allowed, key=lambda a: (-self.rule_for(a).priority, -a.confidence, a.source_region))
        assumed = self.assumptions.get(action.source_region, [])
        return Recommendation(action=action, target=action.target, confidence=action.confidence,
                              reason=self.rule_for(action).description + ("。暫定推測: " + ", ".join(assumed) if assumed else ""),
                              recognition_status="deck_rule_inferred" if assumed else "deck_rule")

    def issued(self, action):
        self.pending = action
        self._verified_action = None
        rule = self.rule_for(action)
        if rule and self.book.inference_mode == "provisional":
            if action.type == ActionType.ACTIVATE:
                self.inferred_used.update(k for k in rule.facts if k.startswith("unused."))
            if action.type == ActionType.SPECIAL_SUMMON:
                self.inferred_used.update(k for k in rule.facts if k.startswith("unused."))
            if action.type == ActionType.NORMAL_SUMMON:
                self.inferred_normal_used = True
            if rule.id == "verte_fusion":
                self.inferred_summon_lock = True

    def expected(self, action, state):
        self._verified_action = None
        rule = self.rule_for(action)
        valid = rule is not None and all(
            key in state.facts and state.facts[key].value == value
            and state.facts[key].confidence >= self.book.min_confidence
            and state.facts[key].observed_at == state.captured_at
            for key, value in rule.expected_facts.items())
        if valid and rule.expected_prompts:
            response_transition = rule.logical_response_decline is not None and rule.logical_response_decline.kind == "opponent_turn_end"
            valid = (state.prompt.value in rule.expected_prompts
                     and state.prompt.confidence >= self.book.min_confidence
                     and state.prompt.observed_at == state.captured_at
                     and (response_transition or (state.animation.value is False
                          and state.animation.confidence >= self.book.min_confidence
                          and state.animation.observed_at == state.captured_at))
                     and state.terminal.value is False
                     and state.terminal.confidence >= self.book.min_confidence
                     and state.terminal.observed_at == state.captured_at)
        if valid and rule.logical_response_decline is not None and rule.logical_response_decline.evidence_mode == "observed_self_draw":
            valid = (not response_ui_contradiction(state)
                and all(ob.value == value and ob.confidence >= self.book.min_confidence and ob.observed_at == state.captured_at
                    for ob,value in [(state.phase,Phase.DRAW),(state.turn_player,Player.SELF),(state.terminal,False)]))
        if valid and self.pending == action:
            self._verified_action = action
        return valid

    def feedback(self, status):
        if status == "changed" and self.pending is not None and self._verified_action == self.pending:
            self.last_completed = self.rule_for(self.pending).id
        else:
            self.last_completed = None
        self.pending = None
        self._verified_action = None
        self.reason = "最新盤面で再計画します。画面遷移だけで効果解決とは扱いません"

    def snapshot(self):
        return {"recipe": None, "goal": self.book.name, "step": None,
                "pending": self.pending is not None, "last_completed": self.last_completed,
                "reason": self.reason, "blocked": self.blocked,
                "inference_mode": self.book.inference_mode, "assumptions": self.assumptions,
                "inferred_used": sorted(self.inferred_used), "inferred_normal_used": self.inferred_normal_used,
                "inferred_summon_lock": self.inferred_summon_lock}


def load_planner(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") == "deck-strategy-v1":
        return RulePlanner(StrategyBook.model_validate(data))
    return TurnPlanner(PlanBook.load(path))
