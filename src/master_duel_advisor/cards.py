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


class CardDatabase:
    def __init__(self, path: Path | str = ":memory:"):
        self.connection = sqlite3.connect(str(path))
        self.connection.execute("CREATE TABLE IF NOT EXISTS cards (card_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        self.connection.commit()

    def import_cards(self, cards: list[Card]):
        with self.connection:
            self.connection.executemany("INSERT INTO cards VALUES (?, ?) ON CONFLICT(card_id) DO UPDATE SET data=excluded.data", [(c.card_id, c.model_dump_json()) for c in cards])

    def get(self, card_id: str) -> Card | None:
        row = self.connection.execute("SELECT data FROM cards WHERE card_id=?", (card_id,)).fetchone()
        return Card.model_validate_json(row[0]) if row else None

    def close(self):
        self.connection.close()
