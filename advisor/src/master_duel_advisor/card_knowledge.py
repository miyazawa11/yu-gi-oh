"""YGOPRODeckのカード原文をローカル優先で保存します。対戦中の取得は非同期です。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .cards import Card

ENDPOINT = "https://db.ygoprodeck.com/api/v7/cardinfo.php"
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / "data" / "card-knowledge.sqlite3"


class KnowledgeError(RuntimeError):
    pass


def validate_lookup(kind, value):
    value = str(value).strip()
    if kind not in {"konami_id", "id", "name"} or not value:
        raise ValueError("KONAMI ID、パスコード、英語正式名のいずれかが必要です")
    if kind != "name" and (not value.isascii() or not value.isdecimal() or int(value) <= 0):
        raise ValueError("カードIDは正の整数で指定してください")
    if kind == "name" and ("|" in value or len(value) > 200 or not value.isascii()):
        raise ValueError("名前検索は英語正式名1件のみ対応します。日本語名はIDとの対応を確認してください")
    return str(int(value)) if kind != "name" else value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise KnowledgeError("カードAPIのリダイレクトは採用しません")


class YgoProDeckClient:
    # 同じプロセスの複数キャッシュでも通信を直列化し、最大2要求/秒に抑えます。
    _lock = threading.Lock()
    _last_request = 0.0

    def __init__(self):
        self.opener = urllib.request.build_opener(NoRedirect())

    def fetch(self, kind, value):
        value = validate_lookup(kind, value)
        url = ENDPOINT + "?" + urllib.parse.urlencode({kind: value, "misc": "yes"})
        with self._lock:
            delay = .5 - (time.monotonic() - type(self)._last_request)
            if delay > 0:
                time.sleep(delay)
            type(self)._last_request = time.monotonic()
            request = urllib.request.Request(url, headers={"User-Agent": "MasterDuelAdvisor/0.1 local-card-cache"})
            try:
                with self.opener.open(request, timeout=8) as response:
                    raw = response.read(2 * 1024 * 1024 + 1)
            except (urllib.error.URLError, OSError) as exc:
                raise KnowledgeError(f"カードAPI取得失敗: {exc}") from exc
        if len(raw) > 2 * 1024 * 1024:
            raise KnowledgeError("カードAPIの応答が上限を超えました")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise KnowledgeError("カードAPIのJSONを解析できません") from exc
        return payload, url


def normalize(payload, kind, value, source_url):
    """完全一致だけを保存し、画像別IDやKONAMI IDの混同を防ぎます。"""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise KnowledgeError("カードを一意に確認できません")
    raw = rows[0]
    provider_id = raw.get("id")
    if type(provider_id) is not int or provider_id <= 0:
        raise KnowledgeError("APIのカード番号が不正です")
    if not all(isinstance(raw.get(k), str) and raw[k].strip() for k in ("name", "type", "desc")):
        raise KnowledgeError("カード名・種別・原文が不足しています")
    misc = raw.get("misc_info", [])
    if not isinstance(misc, list) or not all(isinstance(m, dict) for m in misc):
        raise KnowledgeError("追加カード情報が不正です")
    konami_ids = {str(m["konami_id"]) for m in misc if type(m.get("konami_id")) is int and m["konami_id"] > 0}
    if len(konami_ids) > 1:
        raise KnowledgeError("KONAMI IDが競合しています")
    konami_id = next(iter(konami_ids), None)
    if ((kind == "id" and str(provider_id) != value)
            or (kind == "konami_id" and konami_id != value)
            or (kind == "name" and raw["name"].casefold() != value.casefold())):
        raise KnowledgeError("要求したカードと応答が一致しません")
    ids = {"ygoprodeck": str(provider_id)}
    if konami_id:
        ids["konami"] = konami_id
    fetched = datetime.now(timezone.utc).isoformat()
    card = Card(card_id=f"konami:{konami_id}" if konami_id else f"ygoprodeck:{provider_id}",
                name=raw["name"], type=raw["type"], attribute=raw.get("attribute"), race=raw.get("race"),
                level=None if "XYZ" in raw["type"].upper() else raw.get("level"),
                rank=raw.get("level") if "XYZ" in raw["type"].upper() else None,
                link=raw.get("linkval"), atk=raw.get("atk"), defense=raw.get("def"),
                effect_text=raw["desc"], effect_language="en", effect_source=source_url,
                effect_fetched_at=fetched, external_ids=ids)
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return {"schema_version": 1, "provider": "ygoprodeck", "provider_version": "v7",
            "provider_id": str(provider_id), "konami_id": konami_id,
            "language": "en", "fetched_at": fetched, "source_url": source_url,
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "master_duel_verified": False, "raw": raw, "card": card.model_dump(mode="json")}


class CardKnowledge:
    def __init__(self, path=DEFAULT_CACHE, client=None, clock=time.time):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.client = client or YgoProDeckClient()
        self.clock = clock
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS knowledge (provider_id TEXT PRIMARY KEY, konami_id TEXT UNIQUE, name_key TEXT UNIQUE, record TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS failures (kind TEXT, value TEXT, retry_at REAL, error TEXT, PRIMARY KEY(kind,value))")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, kind, value):
        value = validate_lookup(kind, value)
        column = {"id": "provider_id", "konami_id": "konami_id", "name": "name_key"}[kind]
        with self._connect() as db:
            row = db.execute(f"SELECT record FROM knowledge WHERE {column}=?",
                             (value.casefold() if kind == "name" else value,)).fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        Card.model_validate(record["card"])
        return record

    def ensure(self, kind, value, refresh=False):
        value = validate_lookup(kind, value)
        with self._lock:
            cached = self.get(kind, value)
            if cached is not None and not refresh:
                return cached
            with self._connect() as db:
                failure = db.execute("SELECT retry_at,error FROM failures WHERE kind=? AND value=?", (kind, value)).fetchone()
            if failure and self.clock() < failure[0]:
                raise KnowledgeError(f"取得失敗後の再要求待機中: {failure[1]}")
            try:
                payload, url = self.client.fetch(kind, value)
                record = normalize(payload, kind, value, url)
                encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
                with self._connect() as db:
                    db.execute("INSERT INTO knowledge VALUES (?,?,?,?) ON CONFLICT(provider_id) DO UPDATE SET konami_id=excluded.konami_id,name_key=excluded.name_key,record=excluded.record",
                               (record["provider_id"], record["konami_id"], record["card"]["name"].casefold(), encoded))
                    db.execute("DELETE FROM failures WHERE kind=? AND value=?", (kind, value))
                return record
            except (KnowledgeError, ValueError, TypeError, sqlite3.IntegrityError) as exc:
                with self._connect() as db:
                    db.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?,?)", (kind, value, self.clock()+3600, str(exc)))
                raise KnowledgeError(str(exc)) from exc


class BackgroundKnowledge:
    """ゲームループは取得完了を待たず、未取得は未知として次回観測で再照合します。"""
    def __init__(self, store, id_namespace="konami", max_pending=64):
        if id_namespace not in {"konami", "ygoprodeck"}:
            raise ValueError("カードIDの種類が不正です")
        self.store, self.id_namespace, self.max_pending = store, id_namespace, max_pending
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="card-knowledge")
        self.pending = {}
        self.ready = {}
        self.failed_until = {}
        self.last_error = None

    def lookup(self, card_id, existing=None):
        namespace, value = self.id_namespace, card_id
        if existing and existing.external_ids:
            namespace = "konami" if "konami" in existing.external_ids else "ygoprodeck"
            value = existing.external_ids.get(namespace, "")
        elif ":" in card_id:
            namespace, value = card_id.split(":", 1)
        if namespace not in {"konami", "ygoprodeck"} or not value.isascii() or not value.isdecimal():
            return None
        kind = "konami_id" if namespace == "konami" else "id"
        key = kind, value
        if key in self.ready:
            return self.ready[key]
        future = self.pending.get(key)
        if future is not None:
            if not future.done():
                return None
            del self.pending[key]
            try:
                card = Card.model_validate(future.result()["card"])
                self.ready[key] = card
                return card
            except Exception as exc:
                self.last_error = str(exc)
                self.failed_until[key] = time.monotonic() + 3600
                return None
        if time.monotonic() < self.failed_until.get(key, 0) or len(self.pending) >= self.max_pending:
            return None
        # ensure自身がローカルを先に検査するため、保存済みカードには通信しません。
        self.pending[key] = self.executor.submit(self.store.ensure, kind, value)
        return None

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
