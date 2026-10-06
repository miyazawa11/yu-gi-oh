from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import Field

from .models import Model


class Card(Model):
    card_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str
    attribute: str | None = None
    race: str | None = None
    level: int | None = Field(default=None, ge=0)
    rank: int | None = Field(default=None, ge=0)
    link: int | None = Field(default=None, ge=0)
    atk: int | None = None
    defense: int | None = None
    effect_text: str = ""
    effect_language: str | None = None
    effect_source: str | None = None
    effect_fetched_at: str | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)
    master_duel_verified: bool = False


class CardDatabase:
    def __init__(self, path: Path | str = ":memory:", knowledge=None):
        self.knowledge = knowledge
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("CREATE TABLE IF NOT EXISTS cards (card_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.connection.commit()

    def import_cards(self, cards: list[Card]):
        with self.connection:
            self.connection.executemany("INSERT INTO cards VALUES (?, ?) ON CONFLICT(card_id) DO UPDATE SET data=excluded.data", [(c.card_id, c.model_dump_json()) for c in cards])

    def get(self, card_id: str) -> Card | None:
        row = self.connection.execute("SELECT data FROM cards WHERE card_id=?", (card_id,)).fetchone()
        card = Card.model_validate_json(row[0]) if row else None
        if self.knowledge is not None and (card is None or not card.effect_text.strip()):
            fetched = self.knowledge.lookup(card_id, card)
            if fetched is not None:
                # 校正が参照するIDと既存の日本語名を変えず、英語原文の出典を保持します。
                values = fetched.model_dump()
                values.update(card_id=card_id, name=card.name if card else fetched.name)
                card = Card.model_validate(values)
                self.import_cards([card])
        return card

    def close(self):
        if self.knowledge is not None:
            self.knowledge.close()
        self.connection.close()
