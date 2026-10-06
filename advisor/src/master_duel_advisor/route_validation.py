"""段階付き展開手順と画面校正の接続不足を、入力開始前に列挙する。"""
from pathlib import Path

from .regions import Calibration
from .strategy_rules import StrategyBook


def audit_route(book: StrategyBook, calibration: Calibration, base: Path) -> dict:
    missing = []
    hands=[r.logical_hand_search_confirmation for r in book.rules if r.logical_hand_search_confirmation is not None]
    hand=hands[0] if hands else None
    if hand:
        try:
            from .hand_search import HandSearchVision
            HandSearchVision(base/"hand-search.json")
        except (OSError,ValueError,KeyError) as exc:
            missing.append({"region":"hand-search.json","reason":str(exc)})

    def require(name, labels, kind="template", card_id=None, target=None):
        if hand and kind=="template":
            if name.startswith("fact.hand_search."):return
            if name=="ui.prompt":labels=set(labels)-{"hand.dragondark.effect_menu","hand.dragondark.own_chain","hand.dragondark.result_ready"}
            if not labels:return
        region = calibration.regions.get(name)
        if region is None and kind == "template":
            derived = {c.emit[name] for c in calibration.composites if name in c.emit
                       and all(any(e.label == label and (base / e.image).is_file()
                                   and (base / e.image).resolve().is_relative_to(base.resolve())
                                   for e in calibration.regions[key].exemplars) for key, label in c.when.items())}
            if set(labels) <= derived:
                return
        if region is None or region.kind != kind:
            missing.append({"region": name, "reason": "missing_region", "labels": sorted(labels)})
            return
        available = {e.label for e in region.exemplars if (base / e.image).is_file()
                     and (base / e.image).resolve().is_relative_to(base.resolve())}
        if kind == "template":
            available |= {c.emit[name] for c in calibration.composites if name in c.emit
                          and all(any(e.label == label and (base / e.image).is_file()
                                      and (base / e.image).resolve().is_relative_to(base.resolve())
                                      for e in calibration.regions[key].exemplars) for key, label in c.when.items())}
        absent = set(labels) - available
        if absent:
            missing.append({"region": name, "reason": "missing_exemplar", "labels": sorted(absent)})
        if kind == "action" and (region.card_id, region.target) != (card_id, target):
            missing.append({"region": name, "reason": "action_identity_mismatch"})

    prompts, facts = set(), {}
    inspections = [r.logical_inspect_confirmation for r in book.rules if r.logical_inspect_confirmation is not None]
    inspection = inspections[0] if inspections else None
    for rule in book.rules:
        if not rule.enabled:
            continue
        prompts.update([rule.prompt, *rule.additional_prompts, *rule.expected_prompts])
        require(rule.source_region, {rule.type.value}, "action", rule.card_id, rule.target)
        for key, value in [*rule.observed_facts.items(), *rule.expected_facts.items()]:
            facts.setdefault(key, set()).add(value)
    require("ui.prompt", prompts)
    limited = book.audit_profile in {"phase_transition", "normal_summon", "normal_inspect_confirmation",
                                   "response_decline", "hand_search_confirmation", "solo_basic_operations"}
    require("ui.animation", {"idle"} if limited else {"idle", "playing"})
    require("game.terminal", {"active"} if limited else {"active", "ended"})
    phase_labels = {p.value for r in book.rules for p in r.phases}
    if limited:
        phase_labels |= {r.logical_phase.value for r in book.rules if r.logical_phase is not None}
        if any(r.logical_response_decline and r.logical_response_decline.outcome == "self_draw" for r in book.rules):
            phase_labels.add("DRAW")
    require("phase", phase_labels)
    players = {p.value for r in book.rules for p in r.players}
    if any(r.logical_response_decline and r.logical_response_decline.outcome != "opponent_main1" for r in book.rules):
        players.add("self")
    require("turn_player", players)
    turn = calibration.regions.get("turn")
    if limited:
        pass  # 使用回数やturn数を根拠にしない、専用validatorで制限された操作だけ。
    elif turn is None or turn.kind not in {"template", "number"}:
        missing.append({"region": "turn", "reason": "missing_region"})
    elif turn.kind == "template":
        require("turn", {"1", "2"})
    for key, values in sorted(facts.items()):
        if inspection and key == inspection.detail_card_fact:
            continue  # 詳細CIDは別componentのhash/登録CIDを下で監査します。
        require("fact." + key, values)
    if book.audit_profile == "normal_summon":
        goal = book.rules[0].logical_zone_transition
        require(f"fact.zone.{goal.side}.{goal.zone}.occupancy", {"empty", "occupied"})
        require(f"{goal.side}.zones.{goal.zone}", {goal.card_id}, "card")
        require("fact." + goal.selected_card_fact, {goal.card_id})
    if inspection:
        import hashlib
        import json
        for name in ("detail_name_registry", "action_evidence_detector"):
            spec = calibration.recognition_assets.get(name)
            if spec is None:
                missing.append({"region": name, "reason": "missing_recognition_component"})
                continue
            path = (base / spec.path).resolve()
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != spec.sha256:
                missing.append({"region": name, "reason": "recognition_hash_mismatch"})
            elif name == "detail_name_registry":
                raw = json.loads(path.read_text(encoding="utf-8"))
                if inspection.card_id not in {str(item["cid"]) for item in raw.get("references", [])}:
                    missing.append({"region": name, "reason": "unregistered_card_id"})
        require(f"fact.zone.self.{inspection.zone}.occupancy", {"empty", "occupied"})
        require("fact." + inspection.detail_blank_fact, {"true"})
    return {"book": book.name, "calibration": calibration.name, "ui_steps": len(book.rules),
            "structural_ready": not missing, "real_game_validated": False, "missing": missing, "audit_profile": book.audit_profile,
            "note": "構造検査のみ。画像の識別精度・同じ外観の競合・位置変動・10秒以内の実動作は別途検証が必要"}
