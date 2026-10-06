"""英語検索候補を公式DBの日本語名と照合し、デッキの原文とIDを保存します。"""
import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.request

from master_duel_advisor.card_knowledge import CardKnowledge, DEFAULT_CACHE
from master_duel_advisor.cards import Card, CardDatabase
from master_duel_advisor.deck import DeckProfile
from master_duel_advisor.pipeline import save_json


def normalized_name(name):
    return "".join(unicodedata.normalize("NFKC", name).split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-list", type=Path, required=True)
    parser.add_argument("--lookups", type=Path, required=True, help="日本語名と英語正式名の検索候補JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args()
    deck = json.loads(args.deck_list.read_text(encoding="utf-8"))
    lookups = json.loads(args.lookups.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    aliases_path = args.output / "verified-aliases.json"
    aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    store = CardKnowledge(args.cache)
    cards, failures = [], []
    for entry in deck["cards"]:
        name = entry["name"]
        try:
            previous = aliases.get(name)
            record = (store.ensure("konami_id", previous["konami_id"]) if previous else
                      store.ensure("name", lookups[name]))
            cid = record["konami_id"]
            if cid is None:
                raise ValueError("KONAMI IDがないため日本語名を照合できません")
            url = f"https://www.db.yugioh-card.com/yugiohdb/card_search.action?cid={cid}&ope=2&request_locale=ja"
            if not previous or previous["konami_id"] != cid:
                time.sleep(.5)
                with urllib.request.urlopen(url, timeout=8) as response:
                    page = response.read(2 * 1024 * 1024 + 1)
                if len(page) > 2 * 1024 * 1024:
                    raise ValueError("公式ページが上限を超えました")
                match = re.search(r"<title>(.*?)</title>", page.decode("utf-8"), re.S | re.I)
                title_name = html.unescape(match.group(1)).split("|")[0].strip() if match else ""
                if normalized_name(title_name) != normalized_name(name):
                    raise ValueError(f"日本語名が不一致です: {title_name}")
                aliases[name] = {"konami_id": cid, "ygoprodeck_id": record["provider_id"],
                                 "english_name": record["card"]["name"], "official_name": title_name,
                                 "source_url": url, "checked_at": datetime.now(timezone.utc).isoformat(),
                                 "page_sha256": hashlib.sha256(page).hexdigest()}
                # 途中中断後にも、照合済みの名前を再取得しません。
                save_json(aliases_path, aliases)
            entry.update(card_id=cid, external_ids=record["card"]["external_ids"],
                         identity_status="official_name_and_api_id_matched")
            values = dict(record["card"], card_id=cid, name=name)
            cards.append(Card.model_validate(values))
            print(json.dumps({"name": name, "status": "saved", "konami_id": cid}, ensure_ascii=False), flush=True)
        except (RuntimeError, ValueError, OSError, KeyError) as exc:
            failures.append({"name": name, "error": str(exc)})
            print(json.dumps(failures[-1], ensure_ascii=False), flush=True)
    deck["status"] = "identity_and_effect_source_saved" if not failures else "partially_resolved"
    deck["note"] = "名前は公式DBの同一IDと照合。効果原文はYGOPRODeck英語版。Master Duelの効果・現行規制・操作手順の検証は別途必要です。"
    deck["failures"] = failures
    save_json(args.output / "deck-list.resolved.json", deck)
    db = CardDatabase(args.output / "cards.sqlite3")
    try:
        db.import_cards(cards)
    finally:
        db.close()
    if not failures:
        profile = DeckProfile(name=deck["name"], card_ids=sorted({c.card_id for c in cards}))
        save_json(args.output / "deck-profile.json", profile.model_dump())
    save_json(args.output / "sync-report.json", {"saved": len(cards), "failures": failures,
                                                 "cache": str(args.cache.resolve())})
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
