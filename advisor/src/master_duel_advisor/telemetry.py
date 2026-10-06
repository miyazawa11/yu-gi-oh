"""目的達成単位の計測。入力数・模擬結果を実機成功標本に数えません。"""
from __future__ import annotations

import json
import hashlib
import platform
import math
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

STAGES = ("capture", "recognition", "state_build", "candidate", "decision", "coordinate", "input", "verify")
REQUIRED_CATEGORIES = ("ACTIVATE_EFFECT", "SPECIAL_SUMMON", "NORMAL_SUMMON", "SPELL_TRAP", "ATTACK", "CHANGE_PHASE")
REQUIRED_STEP_TYPES = ("ACTIVATE", "SELECT_CARD", "SELECT_TARGET", "CONFIRM", "CANCEL", "NORMAL_SUMMON",
                       "SPECIAL_SUMMON", "ATTACK", "CHANGE_PHASE", "SET")
FINGERPRINT_FIELDS = ("calibration", "template_assets", "stable_features", "strategy", "limits", "capture", "execution_conditions", "recognition_components")


def value_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def load_manifest(path):
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if (manifest.get("schema") != "acceptance-cohort-v1" or not manifest.get("cohort_id")
            or not manifest.get("source_sha256") or not manifest.get("environment")
            or not isinstance(manifest.get("runs"), list) or not manifest["runs"]):
        raise ValueError("本試験manifestのschema/cohort/source/environment/runsが必要です")
    slots = set()
    for slot in manifest["runs"]:
        key = slot.get("slot_id")
        if not isinstance(key, str) or not key or key in slots:
            raise ValueError("manifest slot_idは非空かつ一意で指定してください")
        slots.add(key)
        if (not isinstance(slot.get("trials"), list) or not slot["trials"]
                or any(not isinstance(t, str) or not t for t in slot["trials"])
                or not all(slot.get("expected_fingerprint", {}).get(name + "_sha256") for name in FINGERPRINT_FIELDS)):
            raise ValueError("manifest slotには予定目的と全設定fingerprintが必要です")
    if not all(manifest["environment"].get(key) for key in ("python", "platform")):
        raise ValueError("manifest environmentにはpython/platformが必要です")
    return manifest


def provenance_errors(metadata, manifest, slot_id):
    errors = []
    runtime = (metadata.get("execution_conditions") or {}).get("runtime") or {}
    if runtime.get("offline_cards") is not True or not runtime.get("data_files", {}).get("database"):
        errors.append("offline DB固定情報なし")
    if metadata.get("data_integrity") is not True:
        errors.append("DB/知識ファイル固定未確認")
    slot = next((s for s in manifest["runs"] if s["slot_id"] == slot_id), None)
    if slot is None:
        return ["manifest未登録slot"]
    if metadata.get("source_sha256") != manifest["source_sha256"]:
        errors.append("source不一致")
    if any(metadata.get(k) != manifest["environment"].get(k) for k in ("python", "platform")):
        errors.append("environment不一致")
    for name in FINGERPRINT_FIELDS:
        digest = metadata.get(name + "_sha256")
        if name not in metadata or digest != value_hash(metadata[name]) or digest != slot["expected_fingerprint"][name + "_sha256"]:
            errors.append(name + "不一致/欠測")
    if [t.get("logical_action") for t in metadata.get("registered_trials", [])] != slot["trials"]:
        errors.append("予定trial不一致")
    return errors


def union_ms(spans):
    intervals = sorted((s["start"], s["end"]) for s in spans if s.get("end") is not None)
    total, end = 0.0, None
    for start, stop in intervals:
        total += max(0, stop - max(start, end if end is not None else start))
        end = max(stop, end if end is not None else stop)
    return total * 1000


class MeasuredCapture:
    def __init__(self, source, telemetry, activity_probe=None):
        self.source, self.telemetry = source, telemetry
        self.activity_probe = activity_probe

    def read(self):
        self.telemetry.admit(self.telemetry.clock())
        with self.telemetry.span("capture") as span:
            self.telemetry.assert_data_unchanged()
            before_epoch = self.activity_probe() if self.activity_probe else None
            frame = self.source.read()
            after_epoch = self.activity_probe() if self.activity_probe else None
        if self.activity_probe and before_epoch != after_epoch:
            self.telemetry.event("capture_input_activity_changed", failure_category="State failure")
            return None
        if frame is None:
            self.telemetry.event("capture_empty")
            return None
        return replace(frame, capture_start=span["start"], capture_end=span["end"],
                       input_epoch=after_epoch if self.activity_probe else frame.input_epoch)

    def close(self):
        return self.source.close()


class ActionTelemetry:
    def __init__(self, output: Path, clock=time.perf_counter, mode="unclassified", trials=None,
                 run_purpose="pilot", cohort_manifest=None, cohort_slot=None):
        if mode not in {"live_autonomous", "assisted", "synthetic", "unclassified"}:
            raise ValueError("計測モードが不正です")
        self.output, self.clock, self.mode = output, clock, mode
        if run_purpose not in {"pilot", "baseline", "acceptance"}:
            raise ValueError("run-purposeが不正です")
        if run_purpose == "acceptance" and (cohort_manifest is None or not cohort_slot):
            raise ValueError("本試験には事前固定manifestとslotが必要です")
        self.manifest = load_manifest(cohort_manifest) if cohort_manifest is not None else None
        self.cohort_slot = cohort_slot
        self.provenance_frozen = False
        self.fixed_data = {}
        self.fixed_hashes = {}
        self.run_id = uuid.uuid4().hex
        self.spans, self.events, self.records = [], [], []
        self.active = None
        self.current_step = None
        self.trials = list(trials or [])
        self.trials_registered_at = self.clock()
        source = Path(__file__).parent
        digest = hashlib.sha256()
        for path in sorted(source.glob("*.py")):
            digest.update(path.name.encode()); digest.update(path.read_bytes())
        self.metadata = {"run_id": self.run_id, "mode": mode, "source_sha256": digest.hexdigest(),
                         "python": platform.python_version(), "platform": platform.platform(),
                         "clock": "perf_counter", "clock_resolution_seconds": time.get_clock_info("perf_counter").resolution,
                         "registered_trials": list(self.trials)}
        self.metadata.update(run_purpose=run_purpose, cohort_id=self.manifest["cohort_id"] if self.manifest else None,
                             cohort_manifest_sha256=value_hash(self.manifest) if self.manifest else None, cohort_slot=cohort_slot,
                             data_integrity=True)

    def configure(self, **values):
        if self.provenance_frozen:
            raise ValueError("画像取得後の計測設定変更は禁止です")
        for name, value in values.items():
            self.metadata[name + "_sha256"] = value_hash(value)
            self.metadata[name] = value

    def freeze_provenance(self):
        if self.provenance_frozen:
            return
        if self.metadata["run_purpose"] == "acceptance":
            runtime = (self.metadata.get("execution_conditions") or {}).get("runtime") or {}
            if runtime.get("offline_cards") is not True or not runtime.get("data_files", {}).get("database"):
                raise ValueError("本試験はoffline-cardsと事前充填済みDBの固定記録が必要です")
            errors = provenance_errors(self.metadata, self.manifest, self.cohort_slot)
            if errors:
                raise ValueError("本試験の事前設定不一致: " + ", ".join(errors))
            for name, spec in runtime["data_files"].items():
                path = Path(spec["path"])
                stat = path.stat()
                if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
                    raise ValueError("本試験の事前DB/知識hash不一致: " + name)
                self.fixed_data[name] = (path, stat.st_size, stat.st_mtime_ns)
                self.fixed_hashes[name] = spec["sha256"]
        for name, sha in (self.metadata.get("recognition_components") or {}).get("files", {}).items():
            path = Path(name)
            stat = path.stat()
            if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError("認識componentの取得前hash不一致: " + name)
            key = "recognition:" + name
            self.fixed_data[key] = (path, stat.st_size, stat.st_mtime_ns)
            self.fixed_hashes[key] = sha
        self.provenance_frozen = True
        self.metadata["provenance_frozen_before_capture"] = True
        if self.metadata["run_purpose"] == "acceptance":
            self.output.mkdir(parents=True, exist_ok=True)
            # 既存本試験runへ追記しない。manifestの取得前snapshotを保持する。
            with (self.output / "run-metadata.json").open("x", encoding="utf-8") as file:
                file.write(json.dumps(self.metadata, indent=2, ensure_ascii=False) + "\n")
            (self.output / "cohort-manifest.json").write_text(json.dumps(self.manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def assert_data_unchanged(self):
        # 大きいDBを毎フレーム再hashしない。通常更新のsize/mtime差で入力前に停止する。
        for name, (path, size, modified) in self.fixed_data.items():
            try:
                stat = path.stat()
                unchanged = (stat.st_size, stat.st_mtime_ns) == (size, modified)
            except OSError:
                unchanged = False
            if not unchanged:
                self.metadata["data_integrity"] = False
                self.event("knowledge_changed", failure_category="State failure", resource=name)
                raise ValueError("本試験中のDB/知識ファイル変更を検出: " + name)

    def admit(self, capture_start):
        self.freeze_provenance()
        if self.active is not None or not self.trials:
            return
        trial = self.trials.pop(0)
        self.active = {"schema": "logical-action-v1", "run_id": self.run_id,
                       "action_id": uuid.uuid4().hex, "mode": self.mode,
                       "started_utc": datetime.now(timezone.utc).isoformat(),
                       "admission": "scheduled_trial", "admitted_at": self.trials_registered_at,
                       "logical_action": trial["logical_action"], "category": trial["category"],
                       "classified": True, "capture_start": capture_start,
                       "count_fact": trial.get("count_fact"), "count_before": None,
                       "zone_transition": trial.get("zone_transition"),
                       "inspect_confirmation": trial.get("inspect_confirmation"),
                       "response_decline": trial.get("response_decline"),
                       "hand_search_confirmation":trial.get("hand_search_confirmation"),
                       "before_sequence": None, "turn_before": None, "phase_before": None,
                       "state_before": None, "steps": [], "fallback_used": False,
                       "misclick": None, "misclick_evidence": None}

    def observe(self, frame, state):
        self.admit(frame.capture_start)
        if self.active and self.active["state_before"] is None:
            self.active.update(before_sequence=state.sequence, state_before=state.model_dump(mode="json"),
                               turn_before=state.turn.model_dump(), phase_before=state.phase.model_dump(),
                               count_before=self.count(state, self.active["count_fact"]))

    @contextmanager
    def span(self, stage):
        item = {"stage": stage, "start": self.clock(), "end": None}
        self.spans.append(item)
        try:
            yield item
        except Exception as exc:
            item["error"] = type(exc).__name__
            raise
        finally:
            item["end"] = self.clock()

    def event(self, status, **values):
        if status == "fallback" and self.active is not None:
            self.active["fallback_used"] = True
        self.events.append({"at": self.clock(), "status": status, **values})

    def import_spans(self, spans):
        # 再利用した認識結果は同じ区間を二重記録しません。
        for span in spans:
            if span not in self.spans:
                self.spans.append(span)

    @staticmethod
    def count(state, key):
        observation = state.facts.get(key) if key else None
        if (observation is None or observation.confidence < .98
                or observation.observed_at != state.captured_at
                or observation.value is None):
            return None
        try:
            value = int(observation.value)
            return value if value >= 0 else None
        except (TypeError, ValueError):
            return None

    def begin_step(self, action, rule, state, frame, recommendation, capture_anchor=None):
        group = getattr(rule, "logical_action", None)
        if self.active and self.active["logical_action"] != group:
            self.finish("interrupted", "Decision failure", "別の目的へ遷移しました")
        if self.active is None:
            classified = bool(group and rule.logical_start)
            self.active = {
                "schema": "logical-action-v1", "run_id": self.run_id,
                "action_id": uuid.uuid4().hex, "mode": self.mode,
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "logical_action": group, "category": getattr(rule, "logical_category", None),
                "admission": "candidate_observed", "admitted_at": self.clock(),
                "classified": classified, "capture_start": capture_anchor if capture_anchor is not None else frame.capture_start,
                "count_fact": getattr(rule, "logical_count_fact", None),
                "zone_transition": self.zone_spec(rule),
                "inspect_confirmation": self.inspect_spec(rule),
                "response_decline": self.response_spec(rule),
                "hand_search_confirmation": self.hand_spec(rule),
                "count_before": self.count(state, getattr(rule, "logical_count_fact", None)),
                "before_sequence": state.sequence, "turn_before": state.turn.model_dump(),
                "phase_before": state.phase.model_dump(), "state_before": state.model_dump(mode="json"),
                "steps": [], "fallback_used": False,
                "misclick": None, "misclick_evidence": None,
            }
        inspection = self.inspect_spec(rule)
        if inspection is not None and self.active.get("inspect_confirmation") is None and not self.active["steps"]:
            self.active["inspect_confirmation"] = inspection
        response = self.response_spec(rule)
        if response is not None and self.active.get("response_decline") is None and not self.active["steps"]:
            self.active["response_decline"] = response
        hand = self.hand_spec(rule)
        if hand is not None and self.active.get("hand_search_confirmation") is None and not self.active["steps"]:
            self.active["hand_search_confirmation"] = hand
        self.active["fallback_used"] |= recommendation.get("recognition_status", "").startswith("llm") or any(
            event["status"] == "fallback" and event["at"] >= (self.active["capture_start"] or float("inf")) for event in self.events)
        spec = self.active.get("zone_transition")
        selection = state.facts.get(spec["selected_card_fact"]) if spec else None
        step = {"step_id": uuid.uuid4().hex, "rule_id": getattr(rule, "id", None),
                "before_sequence": state.sequence,
                "selection_evidence": selection.model_dump(mode="json") if selection and self.visual(selection, state, "template:") else None,
                "action": action.model_dump(mode="json"), "misclick": None, "capture_start": frame.capture_start,
                "capture_end": frame.capture_end, "input_sent": False,
                "retry": False, "retry_candidate": any(s["input_sent"] is not False and s["action"]["source_region"] == action.source_region and s["action"]["type"] == action.type
                             and s["action"]["card_id"] == action.card_id and s["action"]["target"] == action.target for s in self.active["steps"])}
        self.active["steps"].append(step)
        self.current_step = step
        if inspection is not None:
            step.update(inspect_before=state.model_dump(mode="json"), capture_monotonic=frame.captured_at,
                        client_rect=list((self.metadata.get("capture") or {}).get("rect", [])))
        if response is not None:
            step.update(response_before=state.model_dump(mode="json"), capture_monotonic=frame.captured_at,
                        capture_sequence=frame.sequence, capture_input_epoch=frame.input_epoch,
                        capture_source=frame.capture_source, capture_rect=list(frame.capture_rect or ()),
                        client_rect=list((self.metadata.get("capture") or {}).get("rect", [])))
        if hand is not None:
            step.update(hand_before=state.model_dump(mode="json"),capture_monotonic=frame.captured_at,
                capture_sequence=frame.sequence,capture_input_epoch=frame.input_epoch,capture_source=frame.capture_source,
                capture_rect=list(frame.capture_rect or ()),client_rect=list((self.metadata.get("capture") or {}).get("rect",[])),
                hand_episode_before=json.loads(json.dumps(self.active.get("hand_episode"))))

    def input_result(self, sent, point):
        if self.current_step:
            self.current_step.update(input_sent=sent, screen_point=list(point),
                                     retry=sent is not False and self.current_step["retry_candidate"])

    @staticmethod
    def fresh(observation, state):
        return observation.value is not None and observation.confidence >= .98 and observation.observed_at == state.captured_at

    @staticmethod
    def zone_spec(rule):
        value = getattr(rule, "logical_zone_transition", None)
        return value.model_dump(mode="json") if value is not None else None

    @staticmethod
    def inspect_spec(rule):
        value = getattr(rule, "logical_inspect_confirmation", None)
        return value.model_dump(mode="json") if value is not None else None

    @staticmethod
    def response_spec(rule):
        value = getattr(rule, "logical_response_decline", None)
        return value.model_dump(mode="json") if value is not None else None

    @staticmethod
    def hand_spec(rule):
        value=getattr(rule,"logical_hand_search_confirmation",None)
        return value.model_dump(mode="json") if value is not None else None

    @classmethod
    def visual(cls, observation, state, prefix):
        return observation is not None and cls.fresh(observation, state) and observation.source.startswith(prefix)

    def zone_confirmed(self, rule, state):
        spec = self.active.get("zone_transition")
        if not spec or spec != self.zone_spec(rule):
            return False
        from .models import GameState
        before = GameState.model_validate(self.active["state_before"])
        key = f'zone.{spec["side"]}.{spec["zone"]}.occupancy'
        empty, occupied = before.facts.get(key), state.facts.get(key)
        card = state.self.zones.get(spec["zone"])
        if not (self.visual(empty, before, "template:") and empty.value == "empty"
                and self.visual(occupied, state, "template:") and occupied.value == "occupied"
                and self.visual(card, state, "card:") and card.value.card_id == spec["card_id"]
                and state.sequence > before.sequence):
            return False
        selected = False
        placed = False
        for step in self.active["steps"]:
            evidence = step.get("selection_evidence")
            if evidence:
                selected = evidence["value"] == spec["card_id"] and step["before_sequence"] > before.sequence
                if not selected:
                    placed = False
            action = step["action"]
            if (selected and step["input_sent"] is True and action["type"] == "CONFIRM"
                    and action["source_region"] == spec["placement_region"]
                    and action["target"] == f'{spec["side"]}.{spec["zone"]}'
                    and state.sequence > step["before_sequence"]):
                placed = True
        return placed

    def goal_confirmed(self, rule, state):
        if state is None or self.active is None or self.active["state_before"] is None:
            return False
        if self.hand_spec(rule) is not None:
            return len(self.active["steps"])==3 and self.hand_step_confirmed(rule,state)
        if self.active.get("response_decline") or self.response_spec(rule) is not None:
            return self.response_confirmed(rule, state)
        if self.active.get("inspect_confirmation") or self.inspect_spec(rule) is not None:
            return self.inspect_confirmed(rule, state)
        if self.active.get("zone_transition") or getattr(rule, "logical_zone_transition", None) is not None:
            return self.zone_confirmed(rule, state)
        if getattr(rule, "logical_turn_advance", False):
            old = self.active["turn_before"]
            original = self.active["state_before"]["captured_at"]
            return (old["value"] is not None and old["confidence"] >= .98 and old["observed_at"] == original
                    and self.fresh(state.turn, state) and state.turn.value > old["value"]
                    and self.fresh(state.turn_player, state) and state.turn_player.value == "opponent")
        if getattr(rule, "logical_phase", None) is not None:
            old = self.active["phase_before"]
            original = self.active["state_before"]["captured_at"]
            return (old["value"] is not None and old["confidence"] >= .98 and old["observed_at"] == original
                    and old["value"] != rule.logical_phase and self.fresh(state.phase, state)
                    and state.phase.value == rule.logical_phase)
        before, after = self.active["count_before"], self.count(state, self.active["count_fact"])
        self.active["count_after"] = after
        return before is not None and after is not None and after > before

    def hand_step_confirmed(self,rule,state):
        from .models import GameState
        spec=self.hand_spec(rule);active=self.active
        component=(self.metadata.get("recognition_components") or {}).get("hand_search") or {}
        sha=component.get("profile_sha256")
        if (not spec or not active or active.get("hand_search_confirmation")!=spec
                or active.get("logical_action")!=rule.logical_action
                or component.get("goal")!=spec or not sha or self.metadata.get("data_integrity") is not True):return False
        steps=active["steps"];required=[("ACTIVATE",spec["activate_region"],"13906",None),
            ("CANCEL",spec["cancel_region"],None,None),("SELECT_CARD",spec["inspect_region"],"13906","self.hand.received")]
        if not 1<=len(steps)<=3:return False
        rect=(self.metadata.get("capture") or {}).get("rect")
        if not rect or len(rect)!=4 or (rect[2]-rect[0],rect[3]-rect[1])!=(1280,720):return False
        for index,step in enumerate(steps):
            kind,region,cid,target=required[index];action=step["action"]
            if (step.get("input_sent") is not True or step.get("input_epoch_verified") is not True
                    or step.get("capture_source")!="live_mss" or step.get("capture_rect")!=list(rect)
                    or step.get("client_rect")!=list(rect) or step.get("input_epoch") is None
                    or step.get("capture_input_epoch") is None or not step.get("hand_before")
                    or (action["type"],action["source_region"],action["card_id"],action["target"])!=(kind,region,cid,target)):return False
            before=GameState.model_validate(step["hand_before"])
            direct_own=(index==1 and spec.get("own_chain_mode")=="parent_activation_ui"
                and self.visual(before.facts.get("hand_search.own_chain_permission"),before,"hand_search:"+sha)
                and before.facts["hand_search.own_chain_permission"].value=="true"
                and before.facts["hand_search.own_chain_permission"].source=="hand_search:"+sha)
            if index==1 and spec.get("own_chain_mode")=="parent_activation_ui":
                from types import SimpleNamespace
                from .hand_search import activation_parent_valid
                from .strategy_rules import LogicalHandSearchConfirmation
                if (not direct_own or before.prompt.value!="hand.dragondark.own_chain"
                        or not self.fresh(before.prompt,before) or before.animation.value is True
                        or before.terminal.value is not False or not self.fresh(before.terminal,before)
                        or any(o.source=="conflicting_positive_evidence" for o in [before.phase,before.turn_player,before.animation])
                        or not activation_parent_valid({**active,"steps":steps[:1]},LogicalHandSearchConfirmation.model_validate(spec),
                            SimpleNamespace(capture_source=step.get("capture_source"),capture_rect=tuple(step.get("capture_rect") or ()),
                                input_epoch=step.get("capture_input_epoch"),sequence=before.sequence,captured_at=before.captured_at),
                            sha,logical_action=rule.logical_action)):return False
                evidence=before.facts.get("hand_search.own_chain_caption")
                try:caption=json.loads(evidence.value) if evidence is not None else {}
                except (TypeError,ValueError):caption={}
                fixed_caption=component.get("own_chain_cancel_caption") or {}
                if (evidence is None or evidence.observed_at!=before.captured_at
                        or not fixed_caption.get("config_sha256") or caption.get("config_sha256")!=fixed_caption["config_sha256"]
                        or caption.get("score",0)<.85 or caption.get("click_point")!=[545,681]):return False
            if (before.sequence!=step["before_sequence"] or step.get("capture_sequence")!=before.sequence
                    or action["observed_at"]!=before.captured_at or step.get("capture_monotonic")!=before.captured_at
                    or (not direct_own and (not self.fresh(before.phase,before) or before.phase.value!="MAIN1"))
                    or (not direct_own and (not self.fresh(before.turn_player,before) or before.turn_player.value!="self"))
                    or (direct_own and (before.phase.value not in {None,"MAIN1"} or before.turn_player.value not in {None,"self"}))):return False
            if index and steps[index-1].get("result")!="changed":return False
            if index and before.sequence<steps[index-1].get("after_sequence",before.sequence+1):return False
            point=step.get("screen_point")
            if not point or len(point)!=2:return False
            if kind!="CANCEL":
                proof=action.get("hand_search_proof") or {}
                box=proof.get("evidence_bbox");pp=proof.get("point")
                if (proof.get("profile_sha256")!=sha or proof.get("frame_seq")!=before.sequence
                        or proof.get("observed_at")!=before.captured_at or proof.get("client_rect")!=list(rect)
                        or proof.get("action_type")!=kind or proof.get("layout_id") not in {"hand6-slot3","hand7-slot3"}
                        or not box or len(box)!=4 or not pp or point!=[rect[0]+pp[0],rect[1]+pp[1]]
                        or not 0<=box[0]<=pp[0]<box[0]+box[2]<=1280 or not 0<=box[1]<=pp[1]<box[1]+box[3]<=720):return False
            elif point!=[rect[0]+545,rect[1]+681]:return False
        first=GameState.model_validate(steps[0]["hand_before"])
        def positive(s,key,value="true"):
            ob=s.facts.get(key)
            return ob is not None and ob.value==value and self.visual(ob,s,"hand_search:"+sha) and ob.source=="hand_search:"+sha
        if not positive(first,spec["source_ready_fact"]) or not positive(first,spec["detail_fact"],"13906"):return False
        last=steps[-1]
        if state.sequence<=last["before_sequence"] or state.captured_at<=last["capture_monotonic"]:return False
        if not all(positive(state,key,value) for key,value in rule.expected_facts.items()):return False
        if len(steps)>1:
            ep=active.get("hand_episode") or {};anchor=ep.get("anchor");handoff=ep.get("handoff")
            if (ep.get("action_id")!=active["action_id"] or ep.get("profile_sha256")!=sha or ep.get("failed")
                    or not anchor or not handoff or anchor.get("cid")!="13906"
                    or not steps[1]["before_sequence"]<anchor["seq"]<=handoff["seq"]<=state.sequence
                    or not 0<=state.captured_at-handoff["at"]<=3):return False
            chain=GameState.model_validate(steps[1]["hand_before"])
            if not positive(chain,spec["own_chain_fact"]):return False
            if len(steps)==3:
                third=steps[2];before=GameState.model_validate(third["hand_before"])
                old=third.get("hand_episode_before") or {};visible=old.get("current_ready_geometry") or {}
                proof=third["action"].get("hand_search_proof") or {}
                blank=before.facts.get("inspect_context.detail_blank")
                detail=before.facts.get(spec["detail_fact"])
                selected=ep.get("current_selected_geometry") or {};box=selected.get("bbox")
                if (not positive(before,spec["result_ready_fact"])
                        or not self.visual(blank,before,"template:") or blank.value!="true"
                        or detail is None or detail.value is not None
                        or old.get("action_id")!=active["action_id"] or old.get("profile_sha256")!=sha
                        or old.get("failed") or not old.get("ready") or old.get("handoff")!=handoff
                        or old.get("last_seq")!=before.sequence or old.get("last_at")!=before.captured_at
                        or visible.get("role")!="handoff_visible_interior"
                        or proof.get("evidence_bbox")!=visible.get("bbox") or proof.get("point")!=visible.get("point")
                        or ep.get("last_seq")!=state.sequence or ep.get("last_at")!=state.captured_at
                        or not box or len(box)!=4):return False
                hx,hy,hw,hh=handoff["bbox"];px,py=proof["point"]
                if (not hx<=px<hx+hw or not hy<=py<min(720,hy+hh)
                        or abs(box[0]+box[2]/2-(hx+hw/2))>20
                        or not hy-68<=box[1]<=hy-15):return False
        return True

    def response_confirmed(self, rule, state):
        """1回の実Cancel後に、意味別の陽性画面遷移を確認します。"""
        from .models import GameState
        spec = self.active.get("response_decline")
        steps = self.active["steps"]
        components = self.metadata.get("recognition_components") or {}
        if (not spec or spec != self.response_spec(rule) or len(steps) != 1
                or spec not in components.get("response_goals", []) or not components.get("files")
                or self.metadata.get("data_integrity") is not True):
            return False
        step = steps[0]; action = step["action"]
        rect = (self.metadata.get("capture") or {}).get("rect")
        if (not isinstance(rect, (list, tuple)) or len(rect) != 4
                or step.get("capture_source") != "live_mss" or step.get("capture_rect") != list(rect)
                or step.get("client_rect") != list(rect) or step.get("input_sent") is not True
                or step.get("input_epoch_verified") is not True or step.get("input_epoch") is None
                or step.get("capture_input_epoch") is None or step.get("capture_sequence") != step["before_sequence"]
                or not step.get("response_before") or action["type"] != "CANCEL"
                or action["source_region"] != spec["cancel_region"]
                or action["card_id"] is not None or action["target"] is not None
                or action["confidence"] < .98):
            return False
        before = GameState.model_validate(step["response_before"])
        if (before.sequence != step["before_sequence"] or before.captured_at != step.get("capture_monotonic")
                or action["observed_at"] != before.captured_at or state.sequence <= before.sequence
                or state.captured_at <= before.captured_at):
            return False
        region = (self.metadata.get("calibration") or {}).get("regions", {}).get(spec["cancel_region"])
        if not region or region.get("kind") != "action" or region.get("card_id") is not None or region.get("target") is not None:
            return False
        point = step.get("screen_point")
        view = (self.metadata.get("calibration") or {}).get("viewport", {"x":0,"y":0,"width":1,"height":1})
        box = region["rect"]; l,t,r,b = rect
        if (r-l,b-t) != (1280,720) or not point or len(point) != 2:
            return False
        left = l + math.floor((view["x"] + box["x"]*view["width"])*1280)
        top = t + math.floor((view["y"] + box["y"]*view["height"])*720)
        right = l + math.ceil((view["x"] + (box["x"]+box["width"])*view["width"])*1280)
        bottom = t + math.ceil((view["y"] + (box["y"]+box["height"])*view["height"])*720)
        if not left <= point[0] < right or not top <= point[1] < bottom:
            return False
        def positive(s, key):
            ob = s.facts.get(key)
            if key == "response.outcome.self_draw" and ob is not None and ob.source.startswith("draw_overlay:"):
                from .draw_outcome import PARAMETERS
                component = components.get("draw_overlay") or {}
                sha = component.get("config_sha256")
                raw = s.facts.get("response.draw_overlay_diagnostic")
                if (not sha or component.get("parameters") != PARAMETERS or raw is None
                        or raw.source != "diagnostic:not_a_legal_fact" or raw.observed_at != s.captured_at):
                    return False
                try:
                    diagnostic = json.loads(raw.value)
                except (ValueError,TypeError):
                    return False
                word,blue = diagnostic.get("word_score"),diagnostic.get("self_blue_ratio")
                return (self.visual(ob,s,"draw_overlay:"+sha) and ob.source == "draw_overlay:"+sha and ob.value == "true"
                    and diagnostic.get("config_sha256") == sha
                    and type(word) in (int,float) and .90 <= word <= 1
                    and type(blue) in (int,float) and .15 <= blue <= 1)
            return self.visual(ob, s, "template:") and ob.value == "true"
        goal = rule.logical_response_decline
        caption = components.get("cancel_caption")
        cancel_positive = positive(before,goal.cancel_fact)
        if caption:
            from .cancel_caption import PARAMETERS
            sha = caption.get("config_sha256")
            fact = before.facts.get(goal.cancel_fact)
            raw = before.facts.get("response.caption_diagnostic")
            if not sha or caption.get("parameters") != PARAMETERS or raw is None or raw.source != "diagnostic:not_a_legal_fact":
                return False
            fixed_box = PARAMETERS["click_bbox"]
            if (view != {"x":0.,"y":0.,"width":1.,"height":1.}
                    or any(abs(a-b)>1e-6 for a,b in zip([box["x"],box["y"],box["width"],box["height"]],
                        [fixed_box[0]/1280,fixed_box[1]/720,fixed_box[2]/1280,fixed_box[3]/720]))):
                return False
            try:
                diagnostic = json.loads(raw.value)
            except (TypeError,ValueError):
                return False
            cancel_positive = (self.visual(fact,before,"caption_shape:"+sha) and fact.value == "true"
                and raw.observed_at == before.captured_at and diagnostic.get("config_sha256") == sha
                and diagnostic.get("caption_bbox") == PARAMETERS["caption_bbox"]
                and diagnostic.get("click_bbox") == PARAMETERS["click_bbox"]
                and diagnostic.get("click_point") == PARAMETERS["click_point"]
                and isinstance(diagnostic.get("score"),(int,float)) and .85 <= diagnostic["score"] <= 1
                and point == [l+PARAMETERS["click_point"][0],t+PARAMETERS["click_point"][1]])
        direct_draw = goal.evidence_mode == "observed_self_draw"
        from .strategy_rules import response_ui_contradiction
        if direct_draw:
            from .draw_outcome import PARAMETERS as DRAW_PARAMETERS
            component = components.get("draw_overlay") or {}
            diagnostic = state.facts.get("response.draw_overlay_diagnostic")
            if (not component.get("config_sha256") or component.get("parameters") != DRAW_PARAMETERS
                    or diagnostic is None or diagnostic.source != "diagnostic:not_a_legal_fact"
                    or diagnostic.observed_at != state.captured_at):
                return False
            try:
                raw_draw = json.loads(diagnostic.value)
            except (ValueError,TypeError):
                return False
            blue = raw_draw.get("self_blue_ratio")
            if (raw_draw.get("config_sha256") != component["config_sha256"]
                    or type(blue) not in (float,int) or not .15 <= blue <= 1):
                return False
        after_prompt_valid = (not response_ui_contradiction(state)) if direct_draw else (
            self.fresh(state.prompt,state) and state.prompt.value == goal.completion_prompt)
        if not (self.fresh(before.prompt,before) and before.prompt.value == goal.semantic_prompt
                and self.fresh(before.turn_player,before) and before.turn_player.value == "opponent"
                and self.fresh(before.phase,before) and before.phase.value == goal.before_phase
                and self.fresh(before.animation,before) and before.animation.value is False
                and self.fresh(before.terminal,before) and before.terminal.value is False
                and positive(before,goal.prompt_fact) and cancel_positive
                and after_prompt_valid
                and self.fresh(state.terminal,state) and state.terminal.value is False
                and positive(state,goal.completion_fact) and positive(state,goal.outcome_fact)):
            return False
        if goal.outcome == "opponent_main1":
            return (self.fresh(state.turn_player,state) and state.turn_player.value == "opponent"
                    and self.fresh(state.phase,state) and state.phase.value == "MAIN1"
                    and self.fresh(state.animation,state) and state.animation.value is False)
        if goal.outcome == "opponent_end_response":
            return (self.fresh(state.turn_player,state) and state.turn_player.value == "opponent"
                    and self.fresh(state.phase,state) and state.phase.value == "END"
                    and self.fresh(state.animation,state) and state.animation.value is False)
        if not self.fresh(state.turn_player,state) or state.turn_player.value != "self":
            return False
        # Draw表示の演出中でも辞退UIが消えた陽性結果は確認可能。idleへ捏造しません。
        return goal.outcome == "self_turn_notice" or (self.fresh(state.phase,state) and state.phase.value == "DRAW")

    def inspect_confirmed(self, rule, state):
        """詳細CIDをzoneの画素IDへコピーせず、別目的の実入力遷移で確認します。"""
        from .models import GameState
        import math
        spec = self.active.get("inspect_confirmation")
        if not spec or spec != self.inspect_spec(rule) or self.metadata.get("data_integrity") is not True:
            return False
        steps = self.active["steps"]
        required = [("NORMAL_SUMMON", spec["summon_region"], None),
                    ("CONFIRM", spec["placement_region"], f'self.{spec["zone"]}')]
        if spec["clear_region"]:
            required.append(("CANCEL", spec["clear_region"], None))
        required.append(("SELECT_CARD", spec["inspect_region"], f'self.{spec["zone"]}'))
        rect = (self.metadata.get("capture") or {}).get("rect")
        if len(steps) != len(required) or not isinstance(rect, (list, tuple)) or len(rect) != 4:
            return False
        l, t, r, b = rect
        if r-l != 1280 or b-t != 720:
            return False
        before_states = []
        previous = None
        for step, (kind, region_name, target) in zip(steps, required):
            action = step["action"]
            if (step["input_sent"] is not True or action["type"] != kind
                    or action["source_region"] != region_name or action["target"] != target
                    or action["card_id"] != spec["card_id"] or step.get("client_rect") != list(rect)
                    or not step.get("inspect_before") or not step.get("screen_point")):
                return False
            observed = GameState.model_validate(step["inspect_before"])
            if (observed.sequence != step["before_sequence"] or observed.captured_at != step.get("capture_monotonic")
                    or action["observed_at"] != observed.captured_at
                    or not self.fresh(observed.phase, observed) or observed.phase.value != "MAIN1"
                    or not self.fresh(observed.turn_player, observed) or observed.turn_player.value != "self"
                    or not self.fresh(observed.animation, observed) or observed.animation.value is not False
                    or not self.fresh(observed.terminal, observed) or observed.terminal.value is not False):
                return False
            if previous is not None and (previous.get("result") != "changed"
                    or observed.sequence <= previous["before_sequence"]
                    or observed.sequence < previous.get("after_sequence", observed.sequence + 1)):
                return False
            point = step["screen_point"]
            if kind == "NORMAL_SUMMON":
                proof = action.get("coordinate_proof") or {}
                detector = (self.metadata.get("recognition_components") or {}).get("detector") or {}
                if (proof.get("frame_seq") != observed.sequence or proof.get("observed_at") != observed.captured_at
                        or proof.get("client_rect") != list(rect) or proof.get("scope") != "normal_inspect_confirmation"
                        or proof.get("action_type") != "NORMAL_SUMMON" or proof.get("profile_id") != "solar-menu-v2"
                        or not detector.get("detector_sha256") or not proof.get("profile_sha256")
                        or proof.get("detector_sha256") != detector.get("detector_sha256")
                        or proof.get("profile_sha256") != (detector.get("profile_sha256") or {}).get("solar-menu-v2")
                        or not isinstance(proof.get("score"), (int, float)) or not .98 <= proof["score"] <= 1
                        or not isinstance(proof.get("position_margin"), (int, float)) or not .03 <= proof["position_margin"] <= 1):
                    return False
                box = proof.get("evidence_bbox")
                if (not box or len(box) != 4 or any(type(v) is not int for v in box)
                        or tuple(box[2:]) != (74, 79) or not 316 <= box[0] <= 444 or not 473 <= box[1] <= 521):
                    return False
                left, top, width, height = box
                inside = l+left <= point[0] < l+left+width and t+top <= point[1] < t+top+height
            else:
                layout = self.metadata.get("calibration") or {}
                region = layout.get("regions", {}).get(region_name)
                if not region or region.get("card_id") != spec["card_id"] or region.get("target") != target:
                    return False
                view = layout.get("viewport", {"x": 0, "y": 0, "width": 1, "height": 1})
                box = region["rect"]
                left = l + math.floor((view["x"] + box["x"] * view["width"]) * 1280)
                top = t + math.floor((view["y"] + box["y"] * view["height"]) * 720)
                right = l + math.ceil((view["x"] + (box["x"]+box["width"]) * view["width"]) * 1280)
                bottom = t + math.ceil((view["y"] + (box["y"]+box["height"]) * view["height"]) * 720)
                inside = left <= point[0] < right and top <= point[1] < bottom
            if not inside:
                return False
            before_states.append(observed)
            previous = step
        initial, before_inspect = before_states[0], before_states[-1]
        key = f'zone.self.{spec["zone"]}.occupancy'
        empty, occupied, final_occupied = initial.facts.get(key), before_inspect.facts.get(key), state.facts.get(key)
        detail_before = before_inspect.facts.get(spec["detail_card_fact"])
        blank = before_inspect.facts.get(spec["detail_blank_fact"])
        detail = state.facts.get(spec["detail_card_fact"])
        registry_sha = (self.metadata.get("recognition_components") or {}).get("registry_sha256")
        inspect = steps[-1]
        initial_detail = initial.facts.get(spec["detail_card_fact"])
        hand = initial.facts.get(spec["hand_selected_fact"])
        enabled = initial.facts.get(spec["summon_enabled_fact"])
        place_before = before_states[1]
        hand_detector = (self.metadata.get("recognition_components") or {}).get("detector") or {}
        hand_prefix = "template:"
        if hand_detector.get("hand_feature") == "raised_card_lines_v1":
            geometry_sha = hand_detector.get("hand_geometry_sha256")
            if not geometry_sha:
                return False
            hand_prefix = "geometry:" + geometry_sha
        if not (registry_sha and self.visual(initial_detail, initial, "detail_registry:" + registry_sha)
                and initial_detail.value == spec["card_id"]
                and self.visual(hand, initial, hand_prefix) and hand.value == "true"
                and self.visual(enabled, initial, "readonly_detector:") and enabled.value == "true"
                and self.fresh(initial.prompt, initial) and initial.prompt.value == "card.menu"
                and self.fresh(place_before.prompt, place_before) and place_before.prompt.value == "placement.select"
                and self.visual(place_before.facts.get("inspect_context.placement"), place_before, "template:")
                and place_before.facts["inspect_context.placement"].value == "true"
                and self.visual(place_before.facts.get("inspect_context.placement_target"), place_before, "template:")
                and place_before.facts["inspect_context.placement_target"].value == "true"
                and self.fresh(before_inspect.prompt, before_inspect) and before_inspect.prompt.value == "none"
                and self.fresh(state.phase, state) and state.phase.value == "MAIN1"
                and self.fresh(state.turn_player, state) and state.turn_player.value == "self"
                and self.fresh(state.animation, state) and state.animation.value is False
                and self.fresh(state.terminal, state) and state.terminal.value is False
                and self.fresh(state.prompt, state) and state.prompt.value == "field.inspect"
                and all(s.get("input_epoch_verified") is True and s.get("input_epoch") is not None for s in steps)):
            return False
        return (self.visual(empty, initial, "template:") and empty.value == "empty"
                and self.visual(occupied, before_inspect, "template:") and occupied.value == "occupied"
                and self.visual(final_occupied, state, "template:") and final_occupied.value == "occupied"
                and self.visual(blank, before_inspect, "template:") and blank.value == "true"
                and detail_before is not None and detail_before.value is None
                and registry_sha is not None and self.visual(detail, state, "detail_registry:" + registry_sha)
                and detail.value == spec["card_id"] and state.sequence > before_inspect.sequence
                and state.captured_at >= before_inspect.captured_at
                and inspect.get("input_epoch_verified") is True and inspect.get("input_epoch") is not None
                and not self.visual(state.facts.get(spec["detail_blank_fact"]), state, "template:"))

    def complete_step(self, status, rule, state, at=None):
        at = self.clock() if at is None else at
        if self.current_step:
            self.current_step.update(result=status, end=at, after_sequence=state.sequence if state else None)
        if status == "changed" and getattr(rule, "logical_end", False):
            self.active["state_after"] = state.model_dump(mode="json") if state else None
            if self.active["classified"] and self.goal_confirmed(rule, state):
                self.finish("success", None, None, end=at)
            else:
                self.finish("unverified", "Verification failure", "目的の新鮮な状態差分を確認できません", end=at)
        elif status in {"duel_ended", "unexpected_state", "esc", "input_blocked", "input_error_outcome_unknown"}:
            category = "Input failure" if status.startswith("input") else "Verification failure"
            self.finish("interrupted" if status == "esc" else "unverified", category, status, end=at)
        elif not getattr(rule, "logical_action", None):
            self.finish("unclassified", "Verification failure", "目的単位の開始・完了条件が未登録です", end=at)

    def finish(self, result, category, reason, end=None):
        if self.active is None:
            return
        entry, self.active = self.active, None
        entry.update({key: self.metadata[key] for key in ("run_purpose", "cohort_id", "cohort_manifest_sha256", "cohort_slot")})
        end = self.clock() if end is None else end
        start = entry["capture_start"]
        spans = [{**s, "start": max(start, s["start"]), "end": min(end, s["end"])}
                 for s in self.spans if start is not None and s["end"] is not None and s["end"] >= start and s["start"] <= end]
        entry.update(result=result, failure_category=category, failure_reason=reason,
                     ended_at=end, total_ms=(end-start)*1000 if start is not None else None, spans=spans,
                     steps_count=len(entry["steps"]), input_count=sum(s["input_sent"] is True for s in entry["steps"]),
                     retry_count=sum(s["retry"] for s in entry["steps"]))
        for stage in STAGES:
            selected = [s for s in spans if s["stage"] == stage]
            entry[stage + "_start"] = start if stage == "capture" else min((s["start"] for s in selected), default=None)
            entry[stage + "_end"] = max((s["end"] for s in selected), default=None)
        entry["verify_attempt_end"] = entry["verify_end"]
        entry["verify_end"] = end if result == "success" else None
        entry["successful_e2e_ms"] = entry["total_ms"] if result == "success" else None
        # verifyはwall区間。内部のcapture/recognition等と重複加算しません。
        internal = [s for s in spans if s["stage"] not in {"verify", "poll_wait"}]
        entry["system_internal_ms"] = union_ms(internal)
        entry["measured_internal_span_ms"] = entry["system_internal_ms"]
        windows = [s for s in spans if s["stage"] == "verify"]
        waiting = union_ms(windows)
        overlaps = [{"start": max(s["start"], v["start"]), "end": min(s["end"], v["end"])}
                    for s in internal for v in windows if s["start"] < v["end"] and s["end"] > v["start"]]
        entry["input_after_verify_wall_ms"] = waiting
        entry["game_wait_estimate_ms"] = max(0, waiting-union_ms(overlaps))
        entry["verification_wall_ms"] = waiting
        entry["verification_residual_ms"] = entry["game_wait_estimate_ms"]
        entry["poll_wait_ms"] = union_ms([s for s in spans if s["stage"] == "poll_wait"])
        entry["verification_unmeasured_ms"] = max(0, entry["verification_residual_ms"]-entry["poll_wait_ms"])
        entry["child_stage_ms"] = {name: union_ms([s for s in spans if s["stage"] == name])
            for name in ("poll_wait", "frontmost_stop_check", "verify_input_control", "predicate",
                         "artifact_write", "log_write", "pre_input_control", "post_input_control", "normal_ui_bank")}
        entry["wait_estimate_limitation"] = "ゲーム待機・poll待機・未計測Python処理の残差。通信/演出の真因は未計測"
        entry["unattributed_ms"] = max(0, entry["total_ms"]-entry["system_internal_ms"]-entry["game_wait_estimate_ms"]) if start is not None else None
        entry["clock_domain"] = "python_perf_counter_seconds"
        entry["stage_ms"] = {stage: union_ms([s for s in spans if s["stage"] == stage]) for stage in STAGES}
        entry["measurement_complete"] = start is not None and all(entry[s+"_start"] is not None for s in STAGES)
        self.records.append(entry)
        self.output.mkdir(parents=True, exist_ok=True)
        with (self.output / "logical-actions.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False, allow_nan=False) + "\n")
        self.current_step = None

    def close(self, reason):
        if self.fixed_data:
            for name, (path, _, _) in self.fixed_data.items():
                try:
                    unchanged = hashlib.sha256(path.read_bytes()).hexdigest() == self.fixed_hashes[name]
                except OSError:
                    unchanged = False
                if not unchanged:
                    self.metadata["data_integrity"] = False
                    self.event("knowledge_changed", failure_category="State failure", resource=name)
        failures = [span for span in self.spans if span.get("error")]
        categories = {"capture": "Recognition failure", "recognition": "Recognition failure", "state_build": "State failure",
                      "decision": "Decision failure", "candidate": "Decision failure", "coordinate": "Coordinate failure", "input": "Input failure"}
        category = categories.get(failures[-1]["stage"], "Verification failure") if failures else "Verification failure"
        classified_events = [event for event in self.events if event.get("failure_category")
                             and self.active and event["at"] >= (self.active["capture_start"] or 0)]
        if classified_events:
            category = classified_events[-1]["failure_category"]
        self.finish("interrupted", category, reason)
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / "run-metadata.json").write_text(json.dumps(self.metadata, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        (self.output / "logical-actions.jsonl").touch(exist_ok=True)
        with (self.output / "telemetry-spans.jsonl").open("a", encoding="utf-8") as log:
            for span in self.spans:
                log.write(json.dumps({"run_id": self.run_id, "mode": self.mode, **span}, ensure_ascii=False) + "\n")
        with (self.output / "telemetry-events.jsonl").open("a", encoding="utf-8") as log:
            for event in self.events:
                log.write(json.dumps({"run_id": self.run_id, "mode": self.mode, **event}, ensure_ascii=False) + "\n")


def cohort_errors(rows, metadata_by_run, manifest):
    if manifest is None:
        return ["事前固定manifestなし（参考統計のみ）"]
    errors, used_slots = [], set()
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get("run_id"), []).append(row)
    for run_id, actions in grouped.items():
        metadata = metadata_by_run.get(run_id)
        if not metadata:
            errors.append("run-metadata欠測/不一致")
            continue
        slot_id = metadata.get("cohort_slot")
        if slot_id in used_slots:
            errors.append("同slotの複数run混入")
        used_slots.add(slot_id)
        errors.extend(provenance_errors(metadata, manifest, slot_id))
        if not metadata.get("provenance_frozen_before_capture"):
            errors.append("取得前の設定固定なし")
        for record in [metadata, *actions]:
            if (record.get("run_purpose") != "acceptance" or record.get("cohort_id") != manifest["cohort_id"]
                    or record.get("cohort_manifest_sha256") != value_hash(manifest) or record.get("cohort_slot") != slot_id):
                errors.append("purpose/cohort/manifest不一致")
        registered = metadata.get("registered_trials", [])
        if len(actions) != len(registered) or any(
                (r.get("logical_action"), r.get("category")) != (t.get("logical_action"), t.get("category"))
                for r, t in zip(actions, registered)):
            errors.append("予定trialの欠落/追加/順序・カテゴリ不一致")
    if used_slots != {s["slot_id"] for s in manifest["runs"]}:
        errors.append("manifest全slot未完了")
    return sorted(set(errors))


def summarize(paths, required_categories=REQUIRED_CATEGORIES, reviews=None, required_step_types=REQUIRED_STEP_TYPES,
              cohort_manifest=None):
    rows = []
    metadata_by_run = {}
    for path in paths:
        metadata_path = Path(path).parent / "run-metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            run_id = metadata.get("run_id")
            if run_id in metadata_by_run and metadata_by_run[run_id] != metadata:
                raise ValueError("同run_idのmetadataが異なります")
            metadata_by_run[run_id] = metadata
        for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if value.get("schema") != "logical-action-v1":
                raise ValueError(f"目的単位ログではありません: {path}:{number}")
            rows.append(value)
    ids = [r["action_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("重複action_idを合算できません")
    review_map = {}
    if reviews:
        for path in reviews:
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                review = json.loads(line)
                if (not isinstance(review.get("misclick"), bool) or not review.get("evidence")
                        or not review.get("reviewer") or review.get("step_id") in review_map):
                    raise ValueError("誤クリックレビューの証拠/担当/一意step_idが必要です")
                review_map[review["step_id"]] = review
    known_step_ids = {s["step_id"] for r in rows for s in r["steps"]}
    if set(review_map) - known_step_ids:
        raise ValueError("レビューが存在しない子入力を参照しています")
    live = [r for r in rows if r["mode"] == "live_autonomous"]
    manifest = load_manifest(cohort_manifest) if cohort_manifest is not None else None
    integrity_errors = cohort_errors(live, metadata_by_run, manifest)
    valid = [r for r in live if isinstance(r.get("total_ms"), (float, int)) and math.isfinite(r["total_ms"]) and r["total_ms"] >= 0]
    values = [r["total_ms"] for r in valid]
    n = len(live)
    success = sum(r["result"] == "success" for r in live)
    clicks = sum(r["input_count"] for r in live)
    input_steps = [s for r in live for s in r["steps"] if s["input_sent"] is not False]
    reviewed = [review_map[s["step_id"]] for s in input_steps if s["step_id"] in review_map]
    review_complete = bool(input_steps) and len(reviewed) == len(input_steps)
    misclick_rate = sum(r["misclick"] for r in reviewed)/len(input_steps) if review_complete else None
    categories = sorted({r.get("category") for r in live if r.get("category")})
    step_types = sorted({s.get("action", {}).get("type") for s in input_steps if s.get("action", {}).get("type")})
    stats = {"average_ms": float(np.mean(values)) if values else None,
             **{f"p{p}_ms": float(np.percentile(values, p)) if values else None for p in (50, 90, 95)},
             "max_ms": max(values, default=None)}
    successful_values = [r["total_ms"] for r in valid if r["result"] == "success"]
    successful_stats = {"samples": len(successful_values), "average_ms": float(np.mean(successful_values)) if successful_values else None,
                        **{f"p{p}_ms": float(np.percentile(successful_values, p)) if successful_values else None for p in (50, 90, 95)},
                        "max_ms": max(successful_values, default=None)}
    gates = {"samples": n >= 100, "timings_complete": bool(n) and len(valid) == n and all(r["measurement_complete"] for r in live),
             "acceptance_cohort_integrity": bool(n) and not integrity_errors,
             "classification_complete": bool(n) and all(r["classified"] for r in live),
             "pre_admitted_trials": bool(n) and all(r.get("admission") == "scheduled_trial" for r in live),
             "coverage": set(required_categories) <= set(categories),
             "step_coverage": set(required_step_types) <= set(step_types),
             "average": bool(values) and stats["average_ms"] <= 3000 and bool(successful_values) and successful_stats["average_ms"] <= 3000,
             "p50": bool(values) and stats["p50_ms"] <= 2500 and bool(successful_values) and successful_stats["p50_ms"] <= 2500,
             "p95": bool(values) and stats["p95_ms"] <= 5000 and bool(successful_values) and successful_stats["p95_ms"] <= 5000,
             "success": bool(n) and success/n >= .99,
             "misclick_review_complete": review_complete,
             "misclick": misclick_rate is not None and misclick_rate <= .005}
    return {"schema": "logical-benchmark-v1", "samples": n, "all_records": len(rows),
            "excluded_modes": {mode: sum(r["mode"] == mode for r in rows) for mode in sorted({r["mode"] for r in rows}) if mode != "live_autonomous"},
            **stats, "success_rate": success/n if n else None,
            "misoperation_rate": sum(any(review_map[s["step_id"]]["misclick"] for s in r["steps"] if s["input_sent"] is not False) for r in live)/n if n and review_complete else None,
            "misclick_rate": misclick_rate, "misclick_rate_note": "確定送信Trueと送信不明Noneの子入力数を分母とする独立レビュー。確定未送信Falseのみ除外。未レビューは0件扱いにしない",
            "misclick_denominator": len(input_steps), "unknown_input_count": sum(s["input_sent"] is None for s in input_steps),
            "cohort_integrity_errors": integrity_errors,
            "run_purposes": sorted({r.get("run_purpose", "legacy_unknown") for r in live}),
            "input_count": clicks, "retry_rate": sum(r["retry_count"] > 0 for r in live)/n if n else None,
            "fallback_rate": sum(r["fallback_used"] for r in live)/n if n else None,
            "observed_categories": categories, "required_categories": list(required_categories),
            "observed_step_types": step_types, "required_step_types": list(required_step_types),
            "stage_average_ms": {stage: float(np.mean([r["stage_ms"][stage] for r in live if stage in r.get("stage_ms", {})]))
                                 if any(stage in r.get("stage_ms", {}) for r in live) else None for stage in STAGES},
            "gates": gates, "passed": all(gates.values()),
            "successful_e2e_ms": successful_stats, "all_attempt_elapsed_ms": stats,
            "failure_cases": [{"action_id": r["action_id"], "result": r["result"], "reason": r["failure_reason"]} for r in live if r["result"] != "success"],
            "limitations": ["全試行の経過時間と成功時E2Eを別々に集計し、失敗を分母から除外しない。欠測はKPI不合格", "目的分類の網羅は必要条件。試験シナリオの代表性は別途レビューが必要",
                             "misoperation_rateは誤クリックの目的別率。意味的な行動判断の誤りを網羅する独立監査は未実装",
                             "候補起点の未登録目的では、入力に到達しないfallbackを目的分母に含められない。予定trial必須",
                             "verification_residual_msはpoll待機・未計測処理を含む残差。通信/演出の直接実測ではない"]}


def load_trials(path, planner):
    """capture前に予定目的を登録。操作/推薦の順序は変更しません。"""
    ids = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(ids, list) or not ids or any(not isinstance(key, str) for key in ids):
        raise ValueError("試験予定は目的IDの非空JSON配列で指定してください")
    rules = getattr(getattr(planner, "book", None), "rules", [])
    starts = {rule.logical_action: rule for rule in rules if rule.logical_start}
    if set(ids) - set(starts):
        raise ValueError("試験予定に開始条件未登録の目的IDがあります")
    return [{"logical_action": key, "category": starts[key].logical_category,
             "count_fact": starts[key].logical_count_fact,
             "zone_transition": ActionTelemetry.zone_spec(starts[key]),
             "inspect_confirmation": ActionTelemetry.inspect_spec(starts[key]),
             "response_decline": ActionTelemetry.response_spec(starts[key]),
             **({"hand_search_confirmation":ActionTelemetry.hand_spec(starts[key])}
                if ActionTelemetry.hand_spec(starts[key]) is not None else {})} for key in ids]
