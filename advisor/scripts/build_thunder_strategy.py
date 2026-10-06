"""保存済みデッキ専用の展開条件表を生成。通信・画面操作は行いません。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/decks/thunder-dragon-review"
rules = []
MAIN = ["MAIN1", "MAIN2"]
ALL = ["DRAW", "STANDBY", "MAIN1", "BATTLE", "MAIN2", "END"]


def add(cid, key, description, priority, conditions="", *, kind="ACTIVATE", zone=None,
        group=None, both=False, opponent=False, phases=None, prompt="none", enabled=True):
    facts = {c: "true" for c in conditions.split()}
    # チェーン・ダメージステップ・残存制約を含めた、実際の発動/選択可能表示。
    facts[f"window.{key}"] = "open"
    if group:
        facts[f"unused.{group}"] = "true"
    if kind in {"NORMAL_SUMMON", "SPECIAL_SUMMON"}:
        facts["summon.allowed"] = "true"
        if kind == "NORMAL_SUMMON":
            facts["normal_summon.available"] = "true"
    rules.append(dict(id=key, card_id=cid, description=description, type=kind,
                      source_region=f"action.{key}", priority=priority, facts=facts,
                      requires=[dict(zone_prefix=zone, card_id=cid)] if zone else [],
                      players=["self", "opponent"] if both else ["opponent"] if opponent else ["self"],
                      phases=phases or (ALL if both or opponent else MAIN), prompt=prompt, enabled=enabled))


# 使用回数はカード名単位と個体単位を分ける。使用済み/未使用は履歴の確認が必要。
add("4431", "td_discard", "サンダー・ドラゴンで手札雷族発動条件を作る。1枚/2枚の選択は後続に合わせる", 700,
    "deck.td.available hand_effect.allowed", zone="hand_")
add("13905", "matrix_normal", "手札雷族発動後の雷源龍通常召喚で超雷龍のリリースを用意", 690,
    "hand_thunder.activated", kind="NORMAL_SUMMON", zone="hand_")
for cid, key, text, cond, priority, quick in [
    ("13905", "matrix_hand", "雷源龍を捨て、自分の雷族を強化。雷神龍用の手札効果を残す", "target.own_thunder.face_up", 420, True),
    ("13906", "dark_hand", "雷電龍の同名サーチ。除外時サーチとの同一ターン併用は禁止", "deck.dark.available", 410, True),
    ("13907", "hawk_hand", "雷鳥龍で墓地/表側除外の別名雷龍を特殊召喚", "target.hawk.revivable summon.allowed", 800, False),
    ("13908", "roar_hand", "雷獣龍で墓地/表側除外の別名雷龍カードを回収", "target.roar.recoverable", 670, False),
]:
    add(cid, key, text, priority, cond + " hand_effect.allowed", zone="hand_", group=cid, both=quick)
for cid, key, text, cond in [
    ("13905", "matrix_trigger", "雷源龍の除外/場から墓地の誘発で同名を確保", "event.matrix.banished_or_field_to_gy deck.matrix.available"),
    ("13906", "dark_trigger", "雷電龍の誘発で雷鳥龍/雷龍融合/後続を選ぶ", "event.dark.banished_or_field_to_gy deck.other_td_card.available"),
    ("13907", "hawk_trigger", "雷鳥龍の誘発で不要手札を戻す。確保済みの初動や誘発は保持", "event.hawk.banished_or_field_to_gy hand.replaceable"),
    ("13908", "roar_trigger", "雷獣龍の誘発で雷龍をデッキから守備で出す。エンド時回収を記録", "event.roar.banished_or_field_to_gy deck.td_monster.available summon.allowed"),
]:
    add(cid, key, text, 900, cond, group=cid, both=True, prompt=f"trigger.{key}")
add("14107", "aloof_normal", "孤高除獣を通常召喚し、手札とデッキの雷龍を除外する初動", 740,
    "hand.aloof_cost.available deck.same_race.available", kind="NORMAL_SUMMON", zone="hand_")
add("14107", "aloof_banish", "手札の雷獣龍をコストに雷電龍をデッキ除外する線を優先", 910,
    "event.aloof.normal_summoned hand.aloof_cost.available deck.same_race.available", group="aloof_banish", both=True, prompt="trigger.aloof_banish")
add("14107", "aloof_recover", "戦闘/相手効果で破壊された場合だけ、除外モンスターを回収", 850,
    "event.aloof.destroyed_by_battle_or_opponent target.aloof.recoverable", group="aloof_recover", both=True, prompt="trigger.aloof_recover")
add("13581", "solar_normal", "太陽電池メンを通常召喚して雷龍を墓地へ準備", 730,
    "deck.thunder.available", kind="NORMAL_SUMMON", zone="hand_")
add("13581", "solar_send", "太陽電池メンで雷獣龍等を墓地へ。デッキから送るだけでは雷龍誘発を使わない", 900,
    "event.solar.summoned deck.thunder.available", group="solar_send", both=True, prompt="trigger.solar_send")
add("13581", "solar_token", "雷族召喚後のトークン生成を処理。効果モンスター素材としては使わない", 950,
    "event.thunder.summoned_while_solar_face_up summon.allowed zone.monster.free", group="solar_token", both=True, prompt="trigger.solar_token")
add("13581", "solar_copy", "太陽電池メンの名称変更は必要な素材条件を満たす時だけ", 100,
    "target.batteryman.effect_monster copy_name.useful", group="solar_copy", zone="monster_")
for cid, key, attr, other in [("10458", "white", "dark", "black"), ("10463", "black", "light", "white")]:
    add(cid, key+"_summon", "墓地の反対属性を除外し小型カオス竜を展開", 650,
        f"gy.{attr}.banishable", kind="SPECIAL_SUMMON", zone="hand_", group=key+"_summon")
    add(cid, key+"_search", "場から墓地へ送られた小型カオス竜で相方を確保", 880,
        f"event.{key}.field_to_gy deck.{other}.available", both=True, prompt=f"trigger.{key}_search")
for cid, key in [("13909", "duo"), ("15475", "creator")]:
    add(cid, key+"_summon", "墓地の光・闇各1体を除外してカオス大型を展開", 620,
        "gy.light_dark.distinct_banishable", kind="SPECIAL_SUMMON", zone="hand_")
add("15475", "creator_revive", "異なる名前の除外3体から1体を蘇生し、残りをデッキ底へ", 790,
    "creator.summoned_from_hand banished.three_distinct_monsters target.creator.revivable summon.allowed", group="creator_revive", zone="monster_")
add("13909", "duo_boost", "手札モンスター効果発動に伴う攻撃力上昇", 500,
    "event.monster_hand_effect.activated", group="instance.duo_boost", both=True, prompt="trigger.duo_boost")
add("13909", "duo_search", "戦闘破壊後に墓地1枚を除外し雷族を確保", 840,
    "event.duo.destroyed_monster_by_battle gy.one.banishable deck.thunder.available", phases=["BATTLE"], prompt="trigger.duo_search")
add("13909", "duo_recycle", "相手エンドに除外カードをデッキ上/下へ戻す", 450,
    "target.duo.recyclable", opponent=True, phases=["END"], group="instance.duo_recycle")
add("15011", "lord_summon", "手札雷族発動済みなら手札/表側場のレベル8以下雷族を除外して天雷震龍", 500,
    "hand_thunder.activated lord.cost.valid", kind="SPECIAL_SUMMON", zone="hand_")
add("15011", "lord_protect", "相手ターンに墓地2枚（雷族含む）を除外し、自分雷族の対象耐性を付ける", 830,
    "lord.cost.two_gy_including_thunder target.own_thunder.face_up", group="instance.lord_protect", opponent=True, zone="monster_")
add("15011", "lord_end", "自分エンドに雷龍融合等を墓地へ送って次ターンに備える", 550,
    "deck.td_card.available", phases=["END"], zone="monster_")
add("15478", "space_search", "光/闇手札を墓地へ送り反対属性のレベル4〜8特殊召喚モンスターをサーチ", 710,
    "hand.space_cost.valid deck.space_target.valid", zone="hand_", group="space_search")
add("15478", "space_recycle", "除外の通常召喚できない光/闇をデッキ底へ戻して1ドロー", 560,
    "target.space.recyclable draw.allowed", zone="graveyard_", group="space_recycle")
add("7570", "allure", "闇の誘惑で2ドロー。現在の手札に闇が確認できる場合を基本とする", 600,
    "hand.dark.available draw.two_allowed", zone="hand_")
add("13947", "fusion", "場・墓地・表側除外の正しい素材を戻して雷族融合", 820,
    "materials.fusion.valid summon.allowed", zone="hand_", group="fusion")
add("13947", "fusion_search", "前ターン以前に墓地へ送られた雷龍融合を除外して雷族をサーチ", 780,
    "fusion.not_sent_this_turn deck.thunder.available gy.this.banishable", zone="graveyard_", group="fusion_search")
add("4842", "reborn", "蘇生制限を満たす対象を蘇生。超雷龍・雷神龍は選択しない", 610,
    "target.reborn.revivable summon.allowed", zone="hand_")
add("14876", "storm", "自分に表側カードがない時だけ、公開脅威に合う除去モードを選ぶ", 960,
    "self.no_face_up storm.mode.useful", zone="hand_", group="storm_activation")
add("15296", "talent", "自分メイン中に相手がモンスター効果を使ったターンだけ三戦の才", 760,
    "opponent.monster_effect_during_own_main talent.mode.useful", zone="hand_", group="talent_activation")
add("9455", "maxx", "相手の特殊召喚に合わせ増殖するG。展開未確認の決め打ちはしない", 970,
    "opponent.special_summon_expected", zone="hand_", group="maxx", both=True)
add("12950", "ash", "デッキから加える/特殊召喚/墓地送りを含む効果へうらら", 980,
    "chain.ash_eligible chain.negation.useful", zone="hand_", group="ash", both=True)
add("12070", "gamma", "自分モンスターなし・相手モンスター効果へγ。ドライバーと2枠が必要", 980,
    "self.no_monsters chain.opponent_monster_activation driver.available zone.monster.two_free summon.allowed", zone="hand_", both=True)
add("12067", "driver_normal", "ドライバーの通常召喚はリリース2体が必要。基本展開では採用しない", 0,
    "tribute.two.valid", kind="NORMAL_SUMMON", zone="hand_", enabled=False)
add("13631", "imperm_hand", "自分のカードがない時だけ手札から無限泡影", 980,
    "self.no_cards target.opponent_face_up_effect_monster chain.negation.useful", zone="hand_", both=True)
add("13631", "imperm_set", "セット済み泡影で対象を無効。列無効は解決時に場に残る場合だけ", 980,
    "trap.set_before_this_turn target.opponent_face_up_effect_monster chain.negation.useful", zone="spell_", both=True)
add("4861", "judgment", "召喚または魔法・罠カード発動を神の宣告で無効。モンスター効果には使わない", 990,
    "trap.set_before_this_turn chain.judgment_eligible lp.half_payable", zone="spell_", both=True)
for cid, key in [("13631", "set_imperm"), ("4861", "set_judgment")]:
    add(cid, key, "展開終了前に罠をセット。泡影の手札発動を残すかは盤面で判断", 180,
        "zone.spell.free set.useful", kind="SET", zone="hand_")
add("13923", "colossus", "手札雷族発動済み＋表側の非融合雷族効果1体で超雷龍", 850,
    "hand_thunder.activated materials.colossus.valid", kind="SPECIAL_SUMMON")
add("13924", "titan", "手札雷族と場の雷神龍以外の雷族融合を除外して雷神龍。超雷龍維持を比較", 580,
    "materials.titan_alternative.valid titan.replace_colossus.useful", kind="SPECIAL_SUMMON")
add("13924", "titan_destroy", "手札雷族効果に直接チェーンできる時に雷神龍で除去。対象を取らない", 990,
    "chain.immediately_after_thunder_hand_effect field.destructible_card", zone="monster_", both=True)
for cid, key, cond, desc in [
    ("13923", "colossus_protect", "event.this.battle_or_effect_destruction gy.thunder.banishable", "雷族1体を墓地除外して超雷龍の破壊を代替"),
    ("13924", "titan_protect", "event.this.effect_destruction gy.two.banishable", "墓地2枚で雷神龍の効果破壊を代替。戦闘破壊には使わない"),
    ("14195", "mech_protect", "event.own_thunder.battle_or_effect_destruction gy.three.banishable", "墓地3枚で自分の雷族の破壊を代替"),
]:
    add(cid, key, desc, 1000, cond, kind="CONFIRM", both=True, prompt=f"replace.{key}")
for cid, key, text, priority in [
    ("14721", "striker", "レベル4以下ドラゴン1体をストライカーへ変換し相方サーチを誘発", 640),
    ("13936", "summer", "雷族2体で常夏。トークンを利用可能", 630),
    ("14856", "sheep", "異なる名前2体でクロシープ。融合をリンク先へ出せる配置を確保", 625),
    ("14944", "verte", "効果モンスター2体でヴェルテ。コピー効果は最後に回す", 570),
    ("13601", "unicorn", "異なる名前2体以上でリンク3。除去コスト1枚を残す", 660),
    ("13750", "sword", "効果モンスター3体以上でリンク4。リンク2×2だけでは不可", 550),
    ("14195", "mech", "雷族2体以上でリンク4。手札効果の適用を手札発動扱いしない", 400),
    ("15032", "access", "効果モンスター2体以上でリンク4。リンク素材と除外属性を確保", 680),
    ("13344", "ogre", "剛鬼2体以上が必要。提供デッキに剛鬼がないため基本展開では無効", 0),
]:
    add(cid, key+"_link", text, priority, f"materials.{key}.valid zone.extra_summon.valid", kind="SPECIAL_SUMMON", enabled=key != "ogre")
add("13936", "summer_revive", "相手ターンに手札1枚を捨て、墓地の非リンク雷族をリンク先へ蘇生", 870,
    "hand.discardable target.summer.revivable zone.linked.free summon.allowed", group="instance.summer_revive", opponent=True, zone="monster_")
add("14856", "sheep_revive", "リンク先への特殊召喚時、融合を指しているならレベル4以下を蘇生", 920,
    "event.summoned_to_sheep_arrow sheep.points_to_fusion target.sheep.revivable summon.allowed", group="sheep", both=True, prompt="trigger.sheep_revive")
add("14944", "verte_dark", "ヴェルテの属性変更は明確な用途がある場合だけ", 100,
    "target.face_up_monster change_attribute.useful", group="verte_dark", zone="monster_")
add("14944", "verte_fusion", "2000LPを払いデッキの雷龍融合をコピー。その解決後は特殊召喚を止める", 300,
    "lp.over_2000 deck.fusion.available materials.fusion.valid summon.allowed no_more_special_summons_planned", group="verte_fusion", zone="monster_")
add("13601", "unicorn_shuffle", "リンク召喚時に手札を捨て、対象カードをデッキへ戻す", 950,
    "event.unicorn.link_summoned hand.discardable target.unicorn.returnable", group="unicorn", both=True, prompt="trigger.unicorn_shuffle")
add("13750", "sword_defense", "攻撃表示の非リンクを守備にし2回攻撃を得る", 810,
    "target.attack_position.non_link target.position_change.allowed", group="instance.sword_defense", both=True, zone="monster_")
add("13750", "sword_boost", "表側モンスターへの攻撃宣言時に攻撃力を操作", 930,
    "event.sword.attacks_face_up", group="instance.sword_boost", phases=["BATTLE"], prompt="trigger.sword_boost")
add("14195", "mech_copy", "リンク召喚された轟雷機龍で墓地/除外雷龍の手札効果を適用", 550,
    "mech.link_summoned target.mech.effect_applicable", group="mech_copy", zone="monster_")
add("15032", "access_boost", "アクセスコードのリンク素材だったリンクを対象に強化", 930,
    "event.access.link_summoned target.link_used_as_material", group="access_boost", both=True, prompt="trigger.access_boost")
add("15032", "access_destroy", "場/墓地のリンクを除外し相手カードを破壊。同じ属性の再使用は禁止", 950,
    "access.cost.link_banishable access.cost.attribute_unused target.opponent.destructible", zone="monster_")

# 選択UIの意味を固定。別の「カードを選んでください」には流用しない。
for key, cid, prompt, text, cond, priority in [
    ("aloof_cost_roar", "13908", "aloof.hand_cost", "孤高除獣の手札コストに雷獣龍", "unused.13908 deck.dark.available", 920),
    ("aloof_deck_dark", "13906", "aloof.deck_banish", "同じ雷族の雷電龍をデッキ除外", "unused.13906 aloof.cost_was_thunder", 920),
    ("dark_search_hawk", "13907", "dark.search", "蘇生初動が不足していれば雷鳥龍を確保", "unused.13907 target.hawk.revivable need.extender", 900),
    ("dark_search_fusion", "13947", "dark.search", "素材が揃えば雷龍融合を確保", "unused.fusion materials.fusion.valid", 880),
    ("dark_search_matrix", "13905", "dark.search", "雷神龍の相手ターン除去用に雷源龍を確保", "titan.on_field need.quick_thunder", 870),
    ("roar_deck_dark", "13906", "roar.deck_summon", "雷電龍を出し、場から墓地へ送るサーチを準備", "unused.13906 summon.allowed", 920),
    ("solar_send_roar", "13908", "solar.deck_send", "蘇生/除外する雷獣龍を墓地へ", "need.gy_thunder", 910),
    ("allure_banish_roar", "13908", "allure.banish", "闇の誘惑の効果で雷獣龍を除外", "unused.13908", 920),
    ("allure_banish_dark", "13906", "allure.banish", "闇の誘惑の効果で雷電龍を除外", "unused.13906", 910),
    ("space_search_white", "10458", "space.search", "闇を墓地へ送った混沌領域から輝白竜", "space.cost_was_dark", 900),
    ("space_search_black", "10463", "space.search", "光を墓地へ送った混沌領域から暗黒竜", "space.cost_was_light", 900),
]:
    add(cid, key, text, priority, cond, kind="SELECT_CARD", both=True, prompt=prompt)
for key in ["fusion", "colossus", "titan", "striker", "summer", "sheep", "verte", "unicorn", "sword", "mech", "access"]:
    add(None, key+"_materials_confirm", "選択済み素材の枚数・種類・合計・召喚先を再検査して確定", 1000,
        f"selection.{key}.valid summon.allowed", kind="CONFIRM", prompt=f"materials.{key}")


if __name__ == "__main__":
    for rule in rules:
        key = rule["id"]
        if key == "maxx":
            rule["additional_prompts"] = ["chain.response"]
        if key == "colossus":
            rule["additional_prompts"] = ["extra.summon_select"]
        if key in {"colossus", "titan", "fusion", "verte_fusion"}:
            rule["material_method"] = {"titan": "titan_alternative", "verte_fusion": "fusion"}.get(key, key)
        elif key.endswith("_link"):
            rule["material_method"] = key.removesuffix("_link")
        elif key.endswith("_materials_confirm"):
            method = key.removesuffix("_materials_confirm")
            rule["material_method"] = "titan_alternative" if method == "titan" else method
    book = dict(format="deck-strategy-v1", name="サンドラ・条件付き展開ルール", min_confidence=.98, inference_mode="provisional",
                source="cards.sqlite3: 35種類 / docs/thunder-strategy.md", rules=rules)
    from master_duel_advisor.strategy_rules import StrategyBook
    StrategyBook.model_validate(book)
    DEST.joinpath("strategy-book.json").write_text(json.dumps(book, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# 展開条件一覧（生成ファイル）", "", "scripts/build_thunder_strategy.py から再生成。現在は暫定モード: 未確認の展開条件を推測し、確認済みの不成立は拒否します。", "",
             "|ルール|カードID|優先度|内容|必要な事実（すべてAND）|", "|---|---|---:|---|---|"]
    for r in rules:
        conditions = ", ".join(f"{k}={v}" for k,v in r["facts"].items())
        lines.append(f"|{r['id']}|{r['card_id'] or 'UI'}|{r['priority']}|{'【無効】' if not r['enabled'] else ''}{r['description']}|{conditions}|")
    ROOT.joinpath("docs/thunder-strategy-rules.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(f"{len(rules)} rules / {len({r['card_id'] for r in rules if r['card_id']})} cards")
