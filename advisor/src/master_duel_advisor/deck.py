"""認識対象を1デッキと登録済み汎用カードへ絞る設定。"""
from pathlib import Path
from pydantic import Field
from .models import Model


class DeckProfile(Model):
    name: str = Field(min_length=1)
    card_ids: list[str] = Field(min_length=1)
    generic_card_ids: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, path: Path):
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    @property
    def recognition_ids(self):
        return set(self.card_ids) | set(self.generic_card_ids)
