import copy
from threading import Event

import pytest

from master_duel_advisor.card_knowledge import CardKnowledge, BackgroundKnowledge, KnowledgeError, normalize, validate_lookup
from master_duel_advisor.cards import Card, CardDatabase


PAYLOAD = {"data": [{"id": 12345678, "name": "Fixture Dragon", "type": "Effect Monster",
                     "desc": "An effect used only in tests.", "level": 8, "atk": 2600,
                     "def": 2000, "race": "Thunder", "attribute": "DARK",
                     "misc_info": [{"konami_id": 13923, "md_rarity": "Ultra Rare"}],
                     "card_images": [{"id": 12345678, "image_url": "https://example.invalid/card.jpg"}]}]}


class Client:
    def __init__(self, payload=None):
        self.payload = payload or copy.deepcopy(PAYLOAD)
        self.calls = 0

    def fetch(self, kind, value):
        self.calls += 1
        return self.payload, "https://db.ygoprodeck.com/api/v7/cardinfo.php?fixture"


def test_cache_survives_restart_and_all_ids_use_same_record(tmp_path):
    client = Client()
    path = tmp_path / "cache.sqlite3"
    first = CardKnowledge(path, client).ensure("konami_id", "13923")
    second = CardKnowledge(path, client)
    assert second.ensure("id", "12345678") == first
    assert second.ensure("name", "fixture dragon") == first
    assert client.calls == 1
    assert first["card"]["effect_language"] == "en"
    assert first["card"]["external_ids"] == {"konami": "13923", "ygoprodeck": "12345678"}
    assert not first["master_duel_verified"]
    assert first["raw"]["card_images"] == PAYLOAD["data"][0]["card_images"]


def test_empty_or_wrong_response_is_not_cached_and_retry_is_bounded(tmp_path):
    client = Client({"data": []})
    ticks = [100]
    store = CardKnowledge(tmp_path / "cache.sqlite3", client, clock=lambda: ticks[0])
    with pytest.raises(KnowledgeError):
        store.ensure("konami_id", "13923")
    with pytest.raises(KnowledgeError, match="再要求待機"):
        store.ensure("konami_id", "13923")
    assert store.get("konami_id", "13923") is None
    assert client.calls == 1
    ticks[0] += 3600
    client.payload = PAYLOAD
    assert store.ensure("konami_id", "13923")["card"]["effect_text"]
    assert client.calls == 2


@pytest.mark.parametrize("kind,value", [("id", "13923"), ("konami_id", "12345678"), ("name", "Another Dragon")])
def test_namespaces_and_exact_identity_are_checked(kind, value):
    with pytest.raises(KnowledgeError, match="一致"):
        normalize(PAYLOAD, kind, value, "fixture")


@pytest.mark.parametrize("kind,value", [("id", "-1"), ("id", "1,2"), ("name", "A|B"), ("name", "サンダー・ドラゴン"), ("fname", "Dragon")])
def test_ambiguous_or_unsupported_lookup_is_rejected(kind, value):
    with pytest.raises(ValueError):
        validate_lookup(kind, value)


def test_failed_refresh_preserves_saved_data(tmp_path):
    client = Client()
    store = CardKnowledge(tmp_path / "cache.sqlite3", client)
    original = store.ensure("id", "12345678")
    client.payload = {"data": []}
    with pytest.raises(KnowledgeError):
        store.ensure("id", "12345678", refresh=True)
    assert store.ensure("id", "12345678") == original
    assert client.calls == 2


def test_xyz_rank_and_link_are_not_confused_with_level():
    payload = copy.deepcopy(PAYLOAD)
    payload["data"][0]["type"] = "XYZ Monster"
    record = normalize(payload, "id", "12345678", "fixture")
    assert record["card"]["level"] is None and record["card"]["rank"] == 8
    payload["data"][0].update(type="Link Monster", linkval=4)
    payload["data"][0].pop("level")
    assert normalize(payload, "id", "12345678", "fixture")["card"]["link"] == 4


def test_background_does_not_block_or_duplicate_and_preserves_japanese_name(tmp_path):
    entered, release = Event(), Event()
    client = Client()
    fetch = client.fetch
    def delayed(*args):
        entered.set()
        assert release.wait(2)
        return fetch(*args)
    client.fetch = delayed
    background = BackgroundKnowledge(CardKnowledge(tmp_path / "cache.sqlite3", client))
    db = CardDatabase(knowledge=background)
    db.import_cards([Card(card_id="13923", name="既存の日本語名", type="monster")])
    try:
        assert db.get("13923").effect_text == ""
        assert entered.wait(1)
        assert db.get("13923").effect_text == ""
        assert len(background.pending) == 1
        release.set()
        list(background.pending.values())[0].result(timeout=2)
        card = db.get("13923")
        assert card.name == "既存の日本語名"
        assert card.card_id == "13923"
        assert card.effect_text == PAYLOAD["data"][0]["desc"]
        assert card.effect_language == "en"
        assert db.get("13923") == card
        assert client.calls == 1
    finally:
        release.set()
        db.close()


def test_legacy_database_remains_offline_and_known_effect_is_not_replaced():
    class Forbidden:
        def lookup(self, *args):
            raise AssertionError("保存済み原文にAPIは不要")
        def close(self):
            pass
    db = CardDatabase(knowledge=Forbidden())
    try:
        card = Card(card_id="13923", name="保存済み", type="monster", effect_text="手動確認済み")
        db.import_cards([card])
        assert db.get("13923") == card
    finally:
        db.close()
    with_db = CardDatabase()
    assert with_db.get("13923") is None
    with_db.close()
