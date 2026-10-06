# 展開条件一覧（生成ファイル）

scripts/build_thunder_strategy.py から再生成。現在は暫定モード: 未確認の展開条件を推測し、確認済みの不成立は拒否します。

|ルール|カードID|優先度|内容|必要な事実（すべてAND）|
|---|---|---:|---|---|
|td_discard|4431|700|サンダー・ドラゴンで手札雷族発動条件を作る。1枚/2枚の選択は後続に合わせる|deck.td.available=true, hand_effect.allowed=true, window.td_discard=open|
|matrix_normal|13905|690|手札雷族発動後の雷源龍通常召喚で超雷龍のリリースを用意|hand_thunder.activated=true, window.matrix_normal=open, summon.allowed=true, normal_summon.available=true|
|matrix_hand|13905|420|雷源龍を捨て、自分の雷族を強化。雷神龍用の手札効果を残す|target.own_thunder.face_up=true, hand_effect.allowed=true, window.matrix_hand=open, unused.13905=true|
|dark_hand|13906|410|雷電龍の同名サーチ。除外時サーチとの同一ターン併用は禁止|deck.dark.available=true, hand_effect.allowed=true, window.dark_hand=open, unused.13906=true|
|hawk_hand|13907|800|雷鳥龍で墓地/表側除外の別名雷龍を特殊召喚|target.hawk.revivable=true, summon.allowed=true, hand_effect.allowed=true, window.hawk_hand=open, unused.13907=true|
|roar_hand|13908|670|雷獣龍で墓地/表側除外の別名雷龍カードを回収|target.roar.recoverable=true, hand_effect.allowed=true, window.roar_hand=open, unused.13908=true|
|matrix_trigger|13905|900|雷源龍の除外/場から墓地の誘発で同名を確保|event.matrix.banished_or_field_to_gy=true, deck.matrix.available=true, window.matrix_trigger=open, unused.13905=true|
|dark_trigger|13906|900|雷電龍の誘発で雷鳥龍/雷龍融合/後続を選ぶ|event.dark.banished_or_field_to_gy=true, deck.other_td_card.available=true, window.dark_trigger=open, unused.13906=true|
|hawk_trigger|13907|900|雷鳥龍の誘発で不要手札を戻す。確保済みの初動や誘発は保持|event.hawk.banished_or_field_to_gy=true, hand.replaceable=true, window.hawk_trigger=open, unused.13907=true|
|roar_trigger|13908|900|雷獣龍の誘発で雷龍をデッキから守備で出す。エンド時回収を記録|event.roar.banished_or_field_to_gy=true, deck.td_monster.available=true, summon.allowed=true, window.roar_trigger=open, unused.13908=true|
|aloof_normal|14107|740|孤高除獣を通常召喚し、手札とデッキの雷龍を除外する初動|hand.aloof_cost.available=true, deck.same_race.available=true, window.aloof_normal=open, summon.allowed=true, normal_summon.available=true|
|aloof_banish|14107|910|手札の雷獣龍をコストに雷電龍をデッキ除外する線を優先|event.aloof.normal_summoned=true, hand.aloof_cost.available=true, deck.same_race.available=true, window.aloof_banish=open, unused.aloof_banish=true|
|aloof_recover|14107|850|戦闘/相手効果で破壊された場合だけ、除外モンスターを回収|event.aloof.destroyed_by_battle_or_opponent=true, target.aloof.recoverable=true, window.aloof_recover=open, unused.aloof_recover=true|
|solar_normal|13581|730|太陽電池メンを通常召喚して雷龍を墓地へ準備|deck.thunder.available=true, window.solar_normal=open, summon.allowed=true, normal_summon.available=true|
|solar_send|13581|900|太陽電池メンで雷獣龍等を墓地へ。デッキから送るだけでは雷龍誘発を使わない|event.solar.summoned=true, deck.thunder.available=true, window.solar_send=open, unused.solar_send=true|
|solar_token|13581|950|雷族召喚後のトークン生成を処理。効果モンスター素材としては使わない|event.thunder.summoned_while_solar_face_up=true, summon.allowed=true, zone.monster.free=true, window.solar_token=open, unused.solar_token=true|
|solar_copy|13581|100|太陽電池メンの名称変更は必要な素材条件を満たす時だけ|target.batteryman.effect_monster=true, copy_name.useful=true, window.solar_copy=open, unused.solar_copy=true|
|white_summon|10458|650|墓地の反対属性を除外し小型カオス竜を展開|gy.dark.banishable=true, window.white_summon=open, unused.white_summon=true, summon.allowed=true|
|white_search|10458|880|場から墓地へ送られた小型カオス竜で相方を確保|event.white.field_to_gy=true, deck.black.available=true, window.white_search=open|
|black_summon|10463|650|墓地の反対属性を除外し小型カオス竜を展開|gy.light.banishable=true, window.black_summon=open, unused.black_summon=true, summon.allowed=true|
|black_search|10463|880|場から墓地へ送られた小型カオス竜で相方を確保|event.black.field_to_gy=true, deck.white.available=true, window.black_search=open|
|duo_summon|13909|620|墓地の光・闇各1体を除外してカオス大型を展開|gy.light_dark.distinct_banishable=true, window.duo_summon=open, summon.allowed=true|
|creator_summon|15475|620|墓地の光・闇各1体を除外してカオス大型を展開|gy.light_dark.distinct_banishable=true, window.creator_summon=open, summon.allowed=true|
|creator_revive|15475|790|異なる名前の除外3体から1体を蘇生し、残りをデッキ底へ|creator.summoned_from_hand=true, banished.three_distinct_monsters=true, target.creator.revivable=true, summon.allowed=true, window.creator_revive=open, unused.creator_revive=true|
|duo_boost|13909|500|手札モンスター効果発動に伴う攻撃力上昇|event.monster_hand_effect.activated=true, window.duo_boost=open, unused.instance.duo_boost=true|
|duo_search|13909|840|戦闘破壊後に墓地1枚を除外し雷族を確保|event.duo.destroyed_monster_by_battle=true, gy.one.banishable=true, deck.thunder.available=true, window.duo_search=open|
|duo_recycle|13909|450|相手エンドに除外カードをデッキ上/下へ戻す|target.duo.recyclable=true, window.duo_recycle=open, unused.instance.duo_recycle=true|
|lord_summon|15011|500|手札雷族発動済みなら手札/表側場のレベル8以下雷族を除外して天雷震龍|hand_thunder.activated=true, lord.cost.valid=true, window.lord_summon=open, summon.allowed=true|
|lord_protect|15011|830|相手ターンに墓地2枚（雷族含む）を除外し、自分雷族の対象耐性を付ける|lord.cost.two_gy_including_thunder=true, target.own_thunder.face_up=true, window.lord_protect=open, unused.instance.lord_protect=true|
|lord_end|15011|550|自分エンドに雷龍融合等を墓地へ送って次ターンに備える|deck.td_card.available=true, window.lord_end=open|
|space_search|15478|710|光/闇手札を墓地へ送り反対属性のレベル4〜8特殊召喚モンスターをサーチ|hand.space_cost.valid=true, deck.space_target.valid=true, window.space_search=open, unused.space_search=true|
|space_recycle|15478|560|除外の通常召喚できない光/闇をデッキ底へ戻して1ドロー|target.space.recyclable=true, draw.allowed=true, window.space_recycle=open, unused.space_recycle=true|
|allure|7570|600|闇の誘惑で2ドロー。現在の手札に闇が確認できる場合を基本とする|hand.dark.available=true, draw.two_allowed=true, window.allure=open|
|fusion|13947|820|場・墓地・表側除外の正しい素材を戻して雷族融合|materials.fusion.valid=true, summon.allowed=true, window.fusion=open, unused.fusion=true|
|fusion_search|13947|780|前ターン以前に墓地へ送られた雷龍融合を除外して雷族をサーチ|fusion.not_sent_this_turn=true, deck.thunder.available=true, gy.this.banishable=true, window.fusion_search=open, unused.fusion_search=true|
|reborn|4842|610|蘇生制限を満たす対象を蘇生。超雷龍・雷神龍は選択しない|target.reborn.revivable=true, summon.allowed=true, window.reborn=open|
|storm|14876|960|自分に表側カードがない時だけ、公開脅威に合う除去モードを選ぶ|self.no_face_up=true, storm.mode.useful=true, window.storm=open, unused.storm_activation=true|
|talent|15296|760|自分メイン中に相手がモンスター効果を使ったターンだけ三戦の才|opponent.monster_effect_during_own_main=true, talent.mode.useful=true, window.talent=open, unused.talent_activation=true|
|maxx|9455|970|相手の特殊召喚に合わせ増殖するG。展開未確認の決め打ちはしない|opponent.special_summon_expected=true, window.maxx=open, unused.maxx=true|
|ash|12950|980|デッキから加える/特殊召喚/墓地送りを含む効果へうらら|chain.ash_eligible=true, chain.negation.useful=true, window.ash=open, unused.ash=true|
|gamma|12070|980|自分モンスターなし・相手モンスター効果へγ。ドライバーと2枠が必要|self.no_monsters=true, chain.opponent_monster_activation=true, driver.available=true, zone.monster.two_free=true, summon.allowed=true, window.gamma=open|
|driver_normal|12067|0|【無効】ドライバーの通常召喚はリリース2体が必要。基本展開では採用しない|tribute.two.valid=true, window.driver_normal=open, summon.allowed=true, normal_summon.available=true|
|imperm_hand|13631|980|自分のカードがない時だけ手札から無限泡影|self.no_cards=true, target.opponent_face_up_effect_monster=true, chain.negation.useful=true, window.imperm_hand=open|
|imperm_set|13631|980|セット済み泡影で対象を無効。列無効は解決時に場に残る場合だけ|trap.set_before_this_turn=true, target.opponent_face_up_effect_monster=true, chain.negation.useful=true, window.imperm_set=open|
|judgment|4861|990|召喚または魔法・罠カード発動を神の宣告で無効。モンスター効果には使わない|trap.set_before_this_turn=true, chain.judgment_eligible=true, lp.half_payable=true, window.judgment=open|
|set_imperm|13631|180|展開終了前に罠をセット。泡影の手札発動を残すかは盤面で判断|zone.spell.free=true, set.useful=true, window.set_imperm=open|
|set_judgment|4861|180|展開終了前に罠をセット。泡影の手札発動を残すかは盤面で判断|zone.spell.free=true, set.useful=true, window.set_judgment=open|
|colossus|13923|850|手札雷族発動済み＋表側の非融合雷族効果1体で超雷龍|hand_thunder.activated=true, materials.colossus.valid=true, window.colossus=open, summon.allowed=true|
|titan|13924|580|手札雷族と場の雷神龍以外の雷族融合を除外して雷神龍。超雷龍維持を比較|materials.titan_alternative.valid=true, titan.replace_colossus.useful=true, window.titan=open, summon.allowed=true|
|titan_destroy|13924|990|手札雷族効果に直接チェーンできる時に雷神龍で除去。対象を取らない|chain.immediately_after_thunder_hand_effect=true, field.destructible_card=true, window.titan_destroy=open|
|colossus_protect|13923|1000|雷族1体を墓地除外して超雷龍の破壊を代替|event.this.battle_or_effect_destruction=true, gy.thunder.banishable=true, window.colossus_protect=open|
|titan_protect|13924|1000|墓地2枚で雷神龍の効果破壊を代替。戦闘破壊には使わない|event.this.effect_destruction=true, gy.two.banishable=true, window.titan_protect=open|
|mech_protect|14195|1000|墓地3枚で自分の雷族の破壊を代替|event.own_thunder.battle_or_effect_destruction=true, gy.three.banishable=true, window.mech_protect=open|
|striker_link|14721|640|レベル4以下ドラゴン1体をストライカーへ変換し相方サーチを誘発|materials.striker.valid=true, zone.extra_summon.valid=true, window.striker_link=open, summon.allowed=true|
|summer_link|13936|630|雷族2体で常夏。トークンを利用可能|materials.summer.valid=true, zone.extra_summon.valid=true, window.summer_link=open, summon.allowed=true|
|sheep_link|14856|625|異なる名前2体でクロシープ。融合をリンク先へ出せる配置を確保|materials.sheep.valid=true, zone.extra_summon.valid=true, window.sheep_link=open, summon.allowed=true|
|verte_link|14944|570|効果モンスター2体でヴェルテ。コピー効果は最後に回す|materials.verte.valid=true, zone.extra_summon.valid=true, window.verte_link=open, summon.allowed=true|
|unicorn_link|13601|660|異なる名前2体以上でリンク3。除去コスト1枚を残す|materials.unicorn.valid=true, zone.extra_summon.valid=true, window.unicorn_link=open, summon.allowed=true|
|sword_link|13750|550|効果モンスター3体以上でリンク4。リンク2×2だけでは不可|materials.sword.valid=true, zone.extra_summon.valid=true, window.sword_link=open, summon.allowed=true|
|mech_link|14195|400|雷族2体以上でリンク4。手札効果の適用を手札発動扱いしない|materials.mech.valid=true, zone.extra_summon.valid=true, window.mech_link=open, summon.allowed=true|
|access_link|15032|680|効果モンスター2体以上でリンク4。リンク素材と除外属性を確保|materials.access.valid=true, zone.extra_summon.valid=true, window.access_link=open, summon.allowed=true|
|ogre_link|13344|0|【無効】剛鬼2体以上が必要。提供デッキに剛鬼がないため基本展開では無効|materials.ogre.valid=true, zone.extra_summon.valid=true, window.ogre_link=open, summon.allowed=true|
|summer_revive|13936|870|相手ターンに手札1枚を捨て、墓地の非リンク雷族をリンク先へ蘇生|hand.discardable=true, target.summer.revivable=true, zone.linked.free=true, summon.allowed=true, window.summer_revive=open, unused.instance.summer_revive=true|
|sheep_revive|14856|920|リンク先への特殊召喚時、融合を指しているならレベル4以下を蘇生|event.summoned_to_sheep_arrow=true, sheep.points_to_fusion=true, target.sheep.revivable=true, summon.allowed=true, window.sheep_revive=open, unused.sheep=true|
|verte_dark|14944|100|ヴェルテの属性変更は明確な用途がある場合だけ|target.face_up_monster=true, change_attribute.useful=true, window.verte_dark=open, unused.verte_dark=true|
|verte_fusion|14944|300|2000LPを払いデッキの雷龍融合をコピー。その解決後は特殊召喚を止める|lp.over_2000=true, deck.fusion.available=true, materials.fusion.valid=true, summon.allowed=true, no_more_special_summons_planned=true, window.verte_fusion=open, unused.verte_fusion=true|
|unicorn_shuffle|13601|950|リンク召喚時に手札を捨て、対象カードをデッキへ戻す|event.unicorn.link_summoned=true, hand.discardable=true, target.unicorn.returnable=true, window.unicorn_shuffle=open, unused.unicorn=true|
|sword_defense|13750|810|攻撃表示の非リンクを守備にし2回攻撃を得る|target.attack_position.non_link=true, target.position_change.allowed=true, window.sword_defense=open, unused.instance.sword_defense=true|
|sword_boost|13750|930|表側モンスターへの攻撃宣言時に攻撃力を操作|event.sword.attacks_face_up=true, window.sword_boost=open, unused.instance.sword_boost=true|
|mech_copy|14195|550|リンク召喚された轟雷機龍で墓地/除外雷龍の手札効果を適用|mech.link_summoned=true, target.mech.effect_applicable=true, window.mech_copy=open, unused.mech_copy=true|
|access_boost|15032|930|アクセスコードのリンク素材だったリンクを対象に強化|event.access.link_summoned=true, target.link_used_as_material=true, window.access_boost=open, unused.access_boost=true|
|access_destroy|15032|950|場/墓地のリンクを除外し相手カードを破壊。同じ属性の再使用は禁止|access.cost.link_banishable=true, access.cost.attribute_unused=true, target.opponent.destructible=true, window.access_destroy=open|
|aloof_cost_roar|13908|920|孤高除獣の手札コストに雷獣龍|unused.13908=true, deck.dark.available=true, window.aloof_cost_roar=open|
|aloof_deck_dark|13906|920|同じ雷族の雷電龍をデッキ除外|unused.13906=true, aloof.cost_was_thunder=true, window.aloof_deck_dark=open|
|dark_search_hawk|13907|900|蘇生初動が不足していれば雷鳥龍を確保|unused.13907=true, target.hawk.revivable=true, need.extender=true, window.dark_search_hawk=open|
|dark_search_fusion|13947|880|素材が揃えば雷龍融合を確保|unused.fusion=true, materials.fusion.valid=true, window.dark_search_fusion=open|
|dark_search_matrix|13905|870|雷神龍の相手ターン除去用に雷源龍を確保|titan.on_field=true, need.quick_thunder=true, window.dark_search_matrix=open|
|roar_deck_dark|13906|920|雷電龍を出し、場から墓地へ送るサーチを準備|unused.13906=true, summon.allowed=true, window.roar_deck_dark=open|
|solar_send_roar|13908|910|蘇生/除外する雷獣龍を墓地へ|need.gy_thunder=true, window.solar_send_roar=open|
|allure_banish_roar|13908|920|闇の誘惑の効果で雷獣龍を除外|unused.13908=true, window.allure_banish_roar=open|
|allure_banish_dark|13906|910|闇の誘惑の効果で雷電龍を除外|unused.13906=true, window.allure_banish_dark=open|
|space_search_white|10458|900|闇を墓地へ送った混沌領域から輝白竜|space.cost_was_dark=true, window.space_search_white=open|
|space_search_black|10463|900|光を墓地へ送った混沌領域から暗黒竜|space.cost_was_light=true, window.space_search_black=open|
|fusion_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.fusion.valid=true, summon.allowed=true, window.fusion_materials_confirm=open|
|colossus_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.colossus.valid=true, summon.allowed=true, window.colossus_materials_confirm=open|
|titan_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.titan.valid=true, summon.allowed=true, window.titan_materials_confirm=open|
|striker_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.striker.valid=true, summon.allowed=true, window.striker_materials_confirm=open|
|summer_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.summer.valid=true, summon.allowed=true, window.summer_materials_confirm=open|
|sheep_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.sheep.valid=true, summon.allowed=true, window.sheep_materials_confirm=open|
|verte_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.verte.valid=true, summon.allowed=true, window.verte_materials_confirm=open|
|unicorn_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.unicorn.valid=true, summon.allowed=true, window.unicorn_materials_confirm=open|
|sword_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.sword.valid=true, summon.allowed=true, window.sword_materials_confirm=open|
|mech_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.mech.valid=true, summon.allowed=true, window.mech_materials_confirm=open|
|access_materials_confirm|UI|1000|選択済み素材の枚数・種類・合計・召喚先を再検査して確定|selection.access.valid=true, summon.allowed=true, window.access_materials_confirm=open|
