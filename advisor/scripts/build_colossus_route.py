"""実機で確認した混沌領域→超雷龍のUI手順を生成する（座標は含まない）。"""
from __future__ import annotations

import json
from pathlib import Path

from master_duel_advisor.strategy_rules import StrategyBook

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/decks/thunder-dragon-review"


def build_route() -> StrategyBook:
    base = json.loads((DEST / "strategy-book.json").read_text(encoding="utf-8"))
    source = {r["id"]: r for r in base["rules"]}
    rules = []

    def step(key, text, prompt, after, *, previous=(), kind="CONFIRM", cid=None,
             evidence=None, result=None, base_rule=None, target=None):
        rule = dict(source[base_rule]) if base_rule else {}
        rule.update(id=key, description=text, type=kind, card_id=cid, target=target,
                    source_region="action." + key, priority=1000, prompt=prompt,
                    additional_prompts=[], follows=list(previous),
                    expected_prompts=list(after), observed_facts=evidence or {},
                    expected_facts=result or {}, players=["self"], phases=["MAIN1", "MAIN2"])
        rules.append(rule)

    # 同じ「決定」ボタンでも、前の操作・現在の選択・遷移先を区別する。
    step("route_space_open", "手札の混沌領域の操作メニューを開く", "none", ["card.menu"],
         kind="SELECT_CARD", cid="15478", evidence={"route.space_dark_ready": "true"},
         result={"menu.card": "15478"})
    rules[-1]["facts"] = {"unused.space_search": "true"}
    step("route_space_activate", "混沌領域を発動", "card.menu", ["spell.place"],
         previous=["route_space_open"], kind="ACTIVATE", cid="15478", base_rule="space_search",
         evidence={"menu.card": "15478"})
    step("route_space_place", "混沌領域を空いた魔法罠ゾーンへ配置", "spell.place", ["card.select"],
         previous=["route_space_activate"], target="spell_2", evidence={"zone.spell_2.free": "true"})
    step("route_space_cost", "手札コストとして雷電龍を選ぶ", "card.select", ["card.selected"],
         previous=["route_space_place"], kind="SELECT_CARD", cid="13906",
         evidence={"selection.location": "hand"}, result={"selection.card": "13906", "selection.count": "1"})
    step("route_space_cost_confirm", "雷電龍1枚の手札コストを確定", "card.selected", ["chain.response", "card.select"],
         previous=["route_space_cost"], evidence={"selection.card": "13906", "selection.count": "1"})
    step("route_space_chain_pass", "自分の混沌領域への追加チェーンを行わない", "chain.response", ["card.select"],
         previous=["route_space_cost_confirm"], kind="CANCEL", evidence={"chain.owner": "self", "chain.card": "15478"})
    step("route_space_white", "ワイバースターをサーチ対象に選ぶ", "card.select", ["card.selected"],
         previous=["route_space_cost_confirm", "route_space_chain_pass"], kind="SELECT_CARD", cid="10458",
         evidence={"selection.location": "deck"}, result={"selection.card": "10458", "selection.count": "1"})
    step("route_space_white_confirm", "ワイバースターのサーチを確定", "card.selected", ["none"],
         previous=["route_space_white"], evidence={"selection.card": "10458", "selection.count": "1"},
         result={"hand.white.present": "true"})
    step("route_white_open", "ワイバースターの操作メニューを開く", "none", ["card.menu"],
         previous=["route_space_white_confirm"], kind="SELECT_CARD", cid="10458", result={"menu.card": "10458"})
    step("route_white_summon", "ワイバースターを特殊召喚", "card.menu", ["monster.place"],
         previous=["route_white_open"], kind="SPECIAL_SUMMON", cid="10458", base_rule="white_summon",
         evidence={"menu.card": "10458"})
    step("route_white_place", "ワイバースターの配置位置を選ぶ", "monster.place", ["card.select"],
         previous=["route_white_summon"], target="monster_1", evidence={"zone.monster_1.free": "true"})
    step("route_white_banish", "墓地の雷電龍を除外コストに選ぶ", "card.select", ["card.selected"],
         previous=["route_white_place"], kind="SELECT_CARD", cid="13906", evidence={"selection.location": "graveyard"},
         result={"selection.card": "13906", "selection.count": "1"})
    step("route_white_banish_confirm", "雷電龍の除外を確定", "card.selected", ["summon.position"],
         previous=["route_white_banish"], evidence={"selection.card": "13906", "selection.count": "1"})
    step("route_white_attack", "ワイバースターを攻撃表示にする", "summon.position", ["trigger.select"],
         previous=["route_white_banish_confirm"], target="attack", result={"field.white.present": "true"})
    step("route_dark_trigger", "除外された雷電龍の誘発を選ぶ", "trigger.select", ["trigger.selected"],
         previous=["route_white_attack"], kind="SELECT_CARD", cid="13906",
         result={"selection.card": "13906", "selection.count": "1"})
    step("route_dark_activate", "雷電龍の誘発効果を発動", "trigger.selected", ["chain.response", "card.select"],
         previous=["route_dark_trigger"], kind="ACTIVATE", cid="13906", base_rule="dark_trigger",
         evidence={"selection.card": "13906", "selection.count": "1"})
    step("route_dark_chain_pass", "自分の雷電龍への追加チェーンを行わない", "chain.response", ["card.select"],
         previous=["route_dark_activate"], kind="CANCEL", evidence={"chain.owner": "self", "chain.card": "13906"})
    step("route_dark_hawk", "雷鳥龍をサーチ対象に選ぶ", "card.select", ["card.selected"],
         previous=["route_dark_activate", "route_dark_chain_pass"], kind="SELECT_CARD", cid="13907",
         evidence={"selection.location": "deck"}, result={"selection.card": "13907", "selection.count": "1"})
    step("route_dark_hawk_confirm", "雷鳥龍のサーチを確定", "card.selected", ["none"],
         previous=["route_dark_hawk"], evidence={"selection.card": "13907", "selection.count": "1"},
         result={"hand.hawk.present": "true"})
    step("route_hawk_open", "雷鳥龍の操作メニューを開く", "none", ["card.menu"],
         previous=["route_dark_hawk_confirm"], kind="SELECT_CARD", cid="13907", result={"menu.card": "13907"})
    step("route_hawk_activate", "雷鳥龍の手札効果を発動", "card.menu", ["card.select", "chain.response"],
         previous=["route_hawk_open"], kind="ACTIVATE", cid="13907", base_rule="hawk_hand",
         evidence={"menu.card": "13907"})
    step("route_hawk_chain_pass", "自分の雷鳥龍への追加チェーンを行わない", "chain.response", ["card.select"],
         previous=["route_hawk_activate"], kind="CANCEL", evidence={"chain.owner": "self", "chain.card": "13907"})
    step("route_hawk_dark", "除外されている雷電龍を蘇生対象に選ぶ", "card.select", ["card.selected"],
         previous=["route_hawk_activate", "route_hawk_chain_pass"], kind="SELECT_CARD", cid="13906",
         evidence={"selection.location": "banished"}, result={"selection.card": "13906", "selection.count": "1"})
    step("route_hawk_dark_confirm", "雷電龍の蘇生対象を確定", "card.selected", ["summon.position"],
         previous=["route_hawk_dark"], evidence={"selection.card": "13906", "selection.count": "1"})
    step("route_hawk_attack", "雷電龍を攻撃表示にする", "summon.position", ["monster.place"],
         previous=["route_hawk_dark_confirm"], target="attack")
    step("route_hawk_place", "雷電龍を空いたモンスターゾーンへ配置", "monster.place", ["none"],
         previous=["route_hawk_attack"], target="monster_2", evidence={"zone.monster_2.free": "true"},
         result={"field.dark.present": "true"})
    step("route_extra_open", "EXデッキの操作メニューを開く", "none", ["extra.menu"],
         previous=["route_hawk_place"], kind="SELECT_CARD", target="extra")
    step("route_extra_candidates", "EXの特殊召喚候補を表示", "extra.menu", ["extra.summon_select"],
         previous=["route_extra_open"])
    step("route_colossus_select", "超雷龍を特殊召喚候補から選ぶ", "extra.summon_select", ["extra.summon_selected"],
         previous=["route_extra_candidates"], kind="SELECT_CARD", cid="13923",
         result={"selection.card": "13923", "selection.count": "1"})
    step("route_colossus_summon", "超雷龍の特殊召喚を確定", "extra.summon_selected", ["tribute.select"],
         previous=["route_colossus_select"], kind="SPECIAL_SUMMON", cid="13923", base_rule="colossus",
         evidence={"selection.card": "13923", "selection.count": "1"})
    step("route_colossus_tribute", "場の雷電龍をリリース素材に選ぶ", "tribute.select", ["tribute.selected"],
         previous=["route_colossus_summon"], kind="SELECT_CARD", cid="13906",
         evidence={"selection.location": "field"}, result={"selection.card": "13906", "selection.count": "1"})
    step("route_colossus_tribute_confirm", "雷電龍1体のリリースを確定", "tribute.selected", ["summon.position"],
         previous=["route_colossus_tribute"], evidence={"selection.card": "13906", "selection.count": "1"})
    step("route_colossus_attack", "超雷龍を攻撃表示にする", "summon.position", ["monster.place"],
         previous=["route_colossus_tribute_confirm"], target="attack")
    step("route_colossus_place", "超雷龍を配置して召喚完了を確認", "monster.place", ["none"],
         previous=["route_colossus_attack"], target="monster_2", evidence={"zone.monster_2.free": "true"},
         result={"field.colossus.present": "true"})
    groups = [
        ("space_search", "ACTIVATE_EFFECT", "route_space_open", "route_space_white_confirm", "count.self.hand.10458"),
        ("white_summon", "SPECIAL_SUMMON", "route_white_open", "route_white_attack", "count.self.field.10458"),
        ("dark_search", "ACTIVATE_EFFECT", "route_dark_trigger", "route_dark_hawk_confirm", "count.self.hand.13907"),
        ("hawk_revive", "SPECIAL_SUMMON", "route_hawk_open", "route_hawk_place", "count.self.field.13906"),
        ("colossus_summon", "SPECIAL_SUMMON", "route_extra_open", "route_colossus_place", "count.self.field.13923"),
    ]
    ids = [rule["id"] for rule in rules]
    for group, category, first, last, count_fact in groups:
        for rule in rules[ids.index(first):ids.index(last) + 1]:
            rule.update(logical_action=group, logical_category=category,
                        logical_start=rule["id"] == first, logical_end=rule["id"] == last,
                        logical_count_fact=count_fact)
    return StrategyBook.model_validate(dict(format="deck-strategy-v1", name="混沌領域から超雷龍・実画面手順",
        source="evaluation/live-provisional-test.md（UI校正は別途必要）", inference_mode="provisional", rules=rules))


if __name__ == "__main__":
    book = build_route()
    (DEST / "colossus-route.json").write_text(book.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"{len(book.rules)} UI steps")
